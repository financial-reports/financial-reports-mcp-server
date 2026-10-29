"""`filings_markdown_search_batch` — one query across N filings in one call.

Why the tool exists: 90.7% of `filings_markdown_search` calls in prod sit in
(user, hour) EPISODES spanning 2+ filings — 53 episodes averaging 287 calls each,
worst 1,401 calls over 565 filings. See financial-reports/web#8000 for the
measurements and for the server-side endpoint that would make this cheaper still.

⚠ Not "the same query repeated": I first wrote that and withdrew it. It came from
grouping on `arguments->>'query'`, which is 100% `<redacted>` in telemetry — a
constant column groups nothing, so the grouping was (user, hour) ONLY. Query
identity stays unmeasured until #163's text logging accumulates traffic.

The load-bearing behaviours, none of which the single-filing tool has to get right:
  1. per-filing outcomes are distinct — HIT vs NO MATCH vs NOT SEARCHED. Collapsing
     the third into the second turns "we could not read it" into "it isn't there".
  2. the three bounds (filing count, total bytes, wall clock) actually bound.
  3. one bad filing does not fail the batch.
  4. matching is identical to the single-filing tool (shared `_md_scan_hits`).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

DOC = "Intro. Total revenue was 19,409. Costs rose. Total Revenue reached 21,000. End."
OTHER = "Nothing of interest in this filing at all."


def _tool(mcp_module, name):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _mock_md(respx_router, fid, text=DOC, status=200):
    respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/").mock(
        return_value=httpx.Response(status, text=text)
    )


# --- 1. the three outcomes stay distinct ------------------------------------

@pytest.mark.asyncio
async def test_hit_nomatch_and_unavailable_are_reported_separately(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    _mock_md(respx_router, 2, OTHER)
    _mock_md(respx_router, 3, "", status=404)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )

    assert "filing 1" in out
    assert "No match in: 2" in out
    # The distinction this tool exists to preserve: 3 was never read, so it must NOT
    # be reported as an absence.
    assert "Not searched" in out and "3" in out.split("Not searched")[1]
    assert "1 with hits, 1 with none, 0 searched only in part, 1 not searched" in out


@pytest.mark.asyncio
async def test_one_bad_filing_does_not_fail_the_batch(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    _mock_md(respx_router, 2, "boom", status=500)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "filing 1" in out, "a 500 on one filing swallowed the other's answer"


# --- 2. the bounds bound ------------------------------------------------------

@pytest.mark.asyncio
async def test_filing_cap_is_enforced_and_the_overflow_is_announced(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    ids = list(range(1, 26))
    for fid in ids:
        _mock_md(respx_router, fid, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=ids, query="total revenue"
    )
    cap = mcp_module._BATCH_MAX_FILINGS
    assert f"across {cap} filing(s)" in out
    # Silently dropping 5 filings would read as "searched everything, found this".
    assert f"{len(ids) - cap} filing id(s) beyond" in out


@pytest.mark.asyncio
async def test_duplicate_ids_are_searched_once(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(200, text=DOC)
    )
    await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[7, 7, 7], query="total revenue"
    )
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_byte_budget_stops_the_batch_spending(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 10)
    monkeypatch.setattr(mcp_module, "_BATCH_CONCURRENCY", 1)
    for fid in (1, 2, 3):
        _mock_md(respx_router, fid, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )
    assert "byte budget" in out, "the budget did not stop anything"


# --- 3. matching is the single-filing tool's, not a second implementation -----

@pytest.mark.parametrize("query", ["19409", "19,409"])
@pytest.mark.asyncio
async def test_thousands_comma_forms_match_as_in_the_single_filing_tool(
    mcp_module, monkeypatch, fake_access_token, respx_router, query
):
    """Filings render figures as '19,409'. Both spellings must hit, and must hit the
    same way here as in `filings_markdown_search` — the shared `_md_scan_hits` is
    what guarantees a batch miss means the same thing as a single-filing miss."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query=query
    )
    assert "1 match(es)" in out or "filing 1" in out
    assert "No match in: 1" not in out


def test_both_tools_share_one_scanner(mcp_module):
    hits = mcp_module._md_scan_hits(DOC, "19409", 5)
    assert hits and hits[0][1].find("19,409") >= 0


# --- 4. input validation ------------------------------------------------------

@pytest.mark.parametrize(
    "ids,query",
    [([], "x"), ([0], "x"), ([-1], "x"), (["7"], "x"), ([1], "  ")],
)
@pytest.mark.asyncio
async def test_bad_input_is_rejected(
    mcp_module, monkeypatch, fake_access_token, ids, query
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=ids, query=query
    )
    assert "invalid argument" in out.lower(), out


# --- 5. SPECHT #165: the three ways a bound could manufacture a false absence ---

@pytest.mark.asyncio
async def test_truncated_filing_is_partial_not_no_match(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The byte cap cuts the read. A match living past the cap must NOT come back as
    'No match' — that is the false absence this whole tool exists to reduce, and the
    first version of it had exactly that bug."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 40)
    doc = ("x" * 400) + " total revenue was 19,409."   # match sits far past the cap
    _mock_md(respx_router, 1, doc)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    assert "No match in: 1" not in out, "a truncated read was reported as a confirmed absence"
    assert "Searched only in part" in out and "UNKNOWN" in out
    assert "searched only in part" in out.splitlines()[0]


@pytest.mark.asyncio
async def test_untruncated_miss_is_still_a_definite_no_match(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the test above: if the whole document was read, 'no match' must stay
    a definite answer. Otherwise the fix would make every result uncertain."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, OTHER)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    assert "No match in: 1" in out
    assert "Searched only in part" not in out


@pytest.mark.asyncio
async def test_a_stalled_stream_is_not_searched_rather_than_no_match(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The deadline must bound the READ, not just the decision to start one. A stream
    that outlives the batch deadline is an unknown, never an absence.

    Filing 2 is a SURVIVOR, added in SPECHT r8: a batch in which NOTHING could be
    searched now raises (it is not an empty result), so a one-filing batch would
    exercise that path instead of the per-filing reporting this test is about."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_DEADLINE_SECONDS", 0.25)

    async def _slow(*_a, **_kw):
        await asyncio.sleep(5)

    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(side_effect=_slow)
    _mock_md(respx_router, 2, DOC)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "No match in: 1" not in out
    assert "Not searched" in out and "deadline" in out.lower()


@pytest.mark.asyncio
async def test_concurrent_workers_cannot_overspend_the_shared_byte_budget(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Each worker used to compute its allowance from the same unreserved balance before
    awaiting, so N concurrent reads could collectively exceed the batch bound by up to
    (concurrency x per-filing cap). The reservation happens under a lock now."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 300)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 100)
    monkeypatch.setattr(mcp_module, "_BATCH_CONCURRENCY", 5)

    served = {"bytes": 0}
    body = "y" * 1000

    def _count(request):
        served["bytes"] += len(body)
        return httpx.Response(200, text=body)

    for fid in range(1, 6):
        respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/").mock(side_effect=_count)

    await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 4, 5], query="total revenue"
    )
    # 300-byte budget / 100-byte per-filing cap => at most THREE workers are ever
    # admitted; the fourth finds budget["bytes"] == 0 and is skipped.
    # NB the earlier bound here was `<= 5 * 1000`, which only five registered
    # responses can ever produce — it passed even with the budget ignored
    # entirely, i.e. it could not fail for the reason it names. (SPECHT S4,
    # head 651b3b3f.) Assumes the mock delivers each body as one 1,000-byte
    # chunk; revisit if the stream mock changes.
    assert served["bytes"] <= 3 * 1000, (
        f"budget admitted more than 3 fetches: {served['bytes']} bytes served"
    )


# --- 6. SPECHT round 2: bounds that hide incompleteness -----------------------

@pytest.mark.asyncio
async def test_hit_cap_reached_is_announced(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """4 occurrences, cap of 3. Reporting '3 match(es)' silently lets a client read an
    incomplete answer as a complete one — the same false-completeness class as the
    truncation bug, one level down."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "revenue " * 4)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue", max_hits_per_filing=3
    )
    assert "MORE MATCHES EXIST" in out
    assert "3 match(es)" in out, "it should still return only the capped number"


@pytest.mark.asyncio
async def test_exactly_at_the_cap_is_not_announced_as_overflow(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: exactly 3 of 3 is complete. Without this, the fix could mark every
    capped result as uncertain and the signal would carry no information."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "revenue " * 3)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue", max_hits_per_filing=3
    )
    assert "MORE MATCHES EXIST" not in out


@pytest.mark.asyncio
async def test_upstream_status_is_reported_not_swallowed(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """UpstreamHTTPError carries `upstream_status`, NOT `status_code`. Reading the
    wrong attribute made 404, 429 and 500 all render as a bare 'upstream error', so
    the caller could not tell a missing filing from a rate limit.

    Filing 2 is a SURVIVOR (SPECHT r8) — see the stalled-stream test. Note the 429
    here is a BURST limit by classification (`nope` is not a JSON prefix, so it
    falls through to `rate_limited`), which is why it still degrades per-filing
    rather than ending the batch."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "nope", status=429)
    _mock_md(respx_router, 2, DOC)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="revenue"
    )
    assert "429" in out, f"upstream status was swallowed: {out!r}"


# --- 7. the SAME rule applied to the single-filing tool (the #1 tool by volume) ---
# "empty + notice != empty" (ui-fr, web#7880): a restricted or partial result must
# announce its restriction in a way the consumer acts on. ~46-58% of live calls to
# filings_markdown_search land exactly ON the hit cap, so reporting the capped count
# as a total was wrong about half the time.

@pytest.mark.asyncio
async def test_single_tool_announces_the_hit_cap(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "revenue " * 6)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="revenue", max_hits=3
    )
    assert "MORE MATCHES EXIST" in out
    assert "3 match(es)" in out


@pytest.mark.asyncio
async def test_single_tool_exactly_at_cap_is_not_flagged(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: without this the fix marks every capped result uncertain and the
    signal carries no information."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "revenue " * 3)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="revenue", max_hits=3
    )
    assert "MORE MATCHES EXIST" not in out


@pytest.mark.asyncio
async def test_single_tool_truncated_miss_is_unknown_not_absent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A document cut at the size cap was only partly searched. Reporting a bare
    'No match' turns an unread tail into a confirmed absence."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_MAX_FILING_BYTES", 40)
    _mock_md(respx_router, 1, ("x" * 400) + " total revenue was 19,409.")
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="total revenue"
    )
    assert "TRUNCATED" in out and "unknown" in out.lower()


@pytest.mark.asyncio
async def test_single_tool_untruncated_miss_stays_definite(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, OTHER)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="total revenue"
    )
    assert "No match for" in out
    assert "TRUNCATED" not in out


# --- 8. SPECHT round 4: a whole-batch failure must not read as 20 per-filing ones ---

@pytest.mark.asyncio
async def test_auth_failure_raises_rather_than_degrading(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A revoked token 403s every filing. Degrading that to 20 'unavailable' rows
    reports the CALL as successful and hides an auth failure from any client that
    branches on MCP error status. Matches the single-filing tool's #104 contract."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    for fid in (1, 2):
        _mock_md(respx_router, fid, "forbidden", status=403)
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )


@pytest.mark.asyncio
async def test_a_missing_filing_still_degrades_per_filing(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the above: 404 is a per-filing fact and must NOT end the batch,
    or the fix would trade one failure mode for a worse one."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    _mock_md(respx_router, 2, "gone", status=404)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "filing 1" in out and "Not searched" in out


@pytest.mark.asyncio
async def test_error_bodies_are_bounded_and_charged(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`aread()` buffered the whole 5xx body while the budget charged len(buf)==0,
    so N failing filings downloaded unbounded data for free. The read is capped at
    _MAX_ERROR_BODY and the bytes are charged to the batch budget."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_MAX_ERROR_BODY", 50)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 120)
    monkeypatch.setattr(mcp_module, "_BATCH_CONCURRENCY", 1)
    served = {"n": 0}

    def _big(request):
        served["n"] += 1
        return httpx.Response(500, text="E" * 100_000)

    for fid in range(1, 6):
        respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/").mock(side_effect=_big)

    # Every filing fails here, which since SPECHT r8 is an error rather than a
    # successful "0 match(es)" — the charging this test is about happens either way.
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2, 3, 4, 5], query="revenue"
        )
    # Error bytes are charged, so the budget runs out and later filings are skipped
    # rather than each pulling a 100kB body.
    assert served["n"] < 5, f"error bodies were not charged: {served['n']} fetched"
    # The per-filing reasons move into the error message, so the skip is still
    # stated rather than silently dropped.
    assert "budget" in str(exc.value) or "Not searched" in str(exc.value)


@pytest.mark.asyncio
async def test_429_body_is_bounded_inside_the_stream_helper(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`_api_stream_get` reads the 429 body to classify it, INSIDE the helper and
    before yielding — so no caller-side byte budget can see it, and a concurrent
    caller buffers one body per in-flight request. Our own 429 is small; an
    intermediary's (a CDN error page) is not bounded by us.

    A prefix is enough only because `_429_type_from_prefix` recovers `type` from an
    unparseable body — `_classify_upstream_429` itself parses the WHOLE document.
    This docstring claimed the prefix sufficed before that was true (SPECHT r7).
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_MAX_ERROR_BODY", 100)
    huge = "Z" * 500_000
    seen = {}

    real_delay = mcp_module._retry_delay

    def _spy(status, body_text, retry_after):
        seen["len"] = len(body_text)
        return real_delay(status, body_text, retry_after)

    monkeypatch.setattr(mcp_module, "_retry_delay", _spy)
    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(
        return_value=httpx.Response(429, text=huge)
    )
    try:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1], query="revenue"
        )
    except Exception:
        pass
    assert seen.get("len") is not None, "classification never ran"
    assert seen["len"] <= 100, f"429 body was not bounded: {seen['len']} chars buffered"


def test_batch_per_filing_cap_matches_the_single_filing_tool(mcp_module):
    """The two search tools must truncate at the same point, or a miss means
    different things depending on which one you called — the ambiguity
    _md_scan_hits exists to prevent, re-created at the byte level.

    A smaller batch cap was also redundant: aggregate memory is bounded by
    _BATCH_MAX_TOTAL_BYTES through the reservation, not by the per-filing cap.
    """
    assert mcp_module._BATCH_MAX_FILING_BYTES == mcp_module._MAX_FILING_BYTES


def test_total_budget_still_bounds_memory_at_the_larger_cap(mcp_module):
    """Control for the above: raising the per-filing cap must not raise the
    aggregate bound. The reservation admits floor(total/cap) workers."""
    total = mcp_module._BATCH_MAX_TOTAL_BYTES
    per = mcp_module._BATCH_MAX_FILING_BYTES
    assert per <= total, "a single filing could exhaust the whole batch budget"
    admitted = total // per
    assert admitted >= 1, "the budget admits no workers at this cap"
    assert admitted * per <= total, "concurrent reservations can exceed the stated bound"


# --- 9. SPECHT round 6: two regressions I introduced in the two prior commits ---

@pytest.mark.asyncio
async def test_non_retryable_429_raises_rather_than_yielding_a_consumed_stream(
    mcp_module, monkeypatch
):
    """Bounding the 429 classification read replaced `aread()` (which CACHES) with
    `aiter_bytes()` (which CONSUMES), so a non-retryable 429 could be yielded with
    a body the caller can no longer read. `quota_exhausted` is non-retryable and
    ~90% of all upstream errors, so this was the most common error path.

    ⚠ This test took three attempts and both failures are worth keeping:
      1. a respx mock — its body is already buffered, so `.text` kept working and
         the test passed with the fix REVERTED. Vacuous. SPECHT's own second pass
         had warned: "verify with a real streamed 429, not an already-buffered
         mock response".
      2. asserting on `r.text` of a yielded response — the RETRY path opens a
         FRESH stream, and `.text` on an unread streaming response raises
         `ResponseNotRead` by design. That fails identically with or without the
         fix, so it isolates nothing.
    The body must therefore be one the classifier actually recognises: it keys on
    `type`, not `error_kind`, and only `_NON_RETRYABLE_429` reaches `delay=None`.
    """
    import contextlib

    class _Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"type": "quota_limit_exceeded", "detail": "monthly limit"}'

    @contextlib.asynccontextmanager
    async def _fake_stream(method, url, **kw):
        yield httpx.Response(429, stream=_Stream(), request=httpx.Request(method, url))

    monkeypatch.setattr(mcp_module._api_client, "stream", _fake_stream)

    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        async with mcp_module._api_stream_get("/filings/1/markdown/"):
            pass
    assert exc.value.upstream_status == 429, "the quota status must survive"


def test_budget_admits_every_concurrent_worker_at_the_per_filing_cap(mcp_module):
    """Reservation is up-front, so a total below per-filing x concurrency lets the
    first workers reserve everything and a later one be told "budget spent" while
    the earlier reads refund almost all of it moments later — a filing silently
    missing from the answer despite ample real budget.

    Raising the per-filing cap to 10MB against a 40MB total created exactly that:
    four workers reserved the lot and the fifth skipped immediately.
    """
    assert (
        mcp_module._BATCH_MAX_TOTAL_BYTES
        >= mcp_module._BATCH_MAX_FILING_BYTES * mcp_module._BATCH_CONCURRENCY
    ), "a concurrent worker can be falsely skipped while reservations are outstanding"


# --- 10. SPECHT round 7 ------------------------------------------------------

@pytest.mark.asyncio
async def test_account_wide_429_raises_rather_than_degrading(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`quota_exhausted` / spend-cap / spend-ceiling are facts about the ACCOUNT,
    not about a filing, so every filing in the batch gets the same 429. Degrading
    them to per-filing "unavailable: 429" rows returned a SUCCESSFUL
    "0 match(es) across N filing(s)" and discarded the one actionable sentence
    the upstream sent (its own remediation copy).

    Same class as the 401/403 fix two rounds earlier — and my own comment there,
    "Anything else IS per-filing", is what made this read as already handled.
    `quota_exhausted` is ~90% of all upstream errors on this surface.
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    for fid in (1, 2):
        respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/").mock(
            return_value=httpx.Response(
                429, json={"type": "quota_limit_exceeded", "detail": "monthly limit"}
            )
        )
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    assert exc.value.error_kind == "quota_exhausted"


@pytest.mark.asyncio
async def test_a_burst_429_still_degrades_per_filing(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """CONTROL for the above, and the reason the fix keys on `error_kind` rather
    than on the 429 status: a burst limit DOES clear, `_api_stream_get` has
    already spent its single retry on it, and one throttled filing must not cost
    the caller the other answers."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    respx_router.get(f"{TEST_API_BASE}/filings/2/markdown/").mock(
        return_value=httpx.Response(
            429, json={"type": "burst_limit_exceeded", "detail": "slow down"}
        )
    )
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "filing 1" in out and "Not searched" in out


@pytest.mark.asyncio
async def test_a_filing_over_the_per_filing_cap_is_not_told_to_retry(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A filing larger than `_BATCH_MAX_FILING_BYTES` cannot be searched to its end
    by a narrower batch (the allowance is already the full per-filing cap) nor by
    `filings_markdown_search` (same cap, asserted elsewhere in this file). Offering
    both buys the client nothing but repeat calls, which is what this tool exists
    to reduce."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 50)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 50 * mcp_module._BATCH_CONCURRENCY)
    _mock_md(respx_router, 1, "nothing here. " * 200)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )

    assert "searched only in part" in out.lower()
    assert "re-run with a narrower filing set" not in out
    assert "filings_markdown_search on these" not in out
    assert "retrying will not change" in out.lower()


@pytest.mark.asyncio
async def test_a_budget_reduced_allowance_still_gets_the_retry_advice(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """CONTROL for the above: when the SHARED budget — not the filing's size — is
    what cut the read short, a narrower filing set really does help, so that
    advice must survive. One truncation symptom, two causes, two remedies."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 10_000)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 50)
    _mock_md(respx_router, 1, "nothing here. " * 200)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )

    assert "re-run with a narrower filing set" in out
    assert "retrying will not change" not in out.lower()


# --- 11. SPECHT round 8 ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_batch_where_nothing_was_searched_is_an_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Per-filing degradation exists to protect answers the batch DID get. With
    zero successes there is no answer to protect, and "0 match(es) across 2
    filing(s)" tells a client branching on error status that the corpus was
    searched and is empty — the false absence this tool exists to reduce, at the
    batch boundary instead of the filing boundary (#104).

    The per-filing reasons are carried into the error message, so nothing the
    successful-looking string would have said is lost."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    for fid in (1, 2):
        _mock_md(respx_router, fid, "gone", status=404)
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    assert "1" in str(exc.value) and "2" in str(exc.value), "per-filing reasons lost"

    # The one-filing shape too — it is where "0 match(es)" is least defensible, and
    # it is what three pre-existing tests in this file were relying on. The
    # single-filing tool already raises on a 404 (#104); this makes the batch agree.
    _mock_md(respx_router, 9, "gone", status=404)
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[9], query="revenue"
        )


@pytest.mark.asyncio
async def test_one_survivor_still_returns_the_partial_answer(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """CONTROL for the above, and the line the fix must not cross: ONE readable
    filing is an answer, so the other nineteen failing must not cost the caller
    it."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    for fid in (2, 3):
        _mock_md(respx_router, fid, "gone", status=404)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )
    assert "filing 1" in out and "Not searched" in out


@pytest.mark.asyncio
async def test_every_filing_searched_with_no_match_is_not_an_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """SECOND CONTROL, and the one that matters most: a definite "searched it all,
    it isn't there" is a RESULT. Keying the new error on "no hits" instead of on
    "nothing was searched" would turn every honest negative answer into an error —
    a far worse bug than the one being fixed."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    for fid in (1, 2):
        _mock_md(respx_router, fid, OTHER)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "0 match(es)" in out and "No match in: 1, 2" in out


@pytest.mark.asyncio
async def test_an_account_wide_failure_cancels_the_queued_workers(
    mcp_module, monkeypatch, fake_access_token
):
    """`asyncio.gather` propagates the first exception but does NOT cancel its
    siblings, so an account-wide 429 left queued workers fetching filings that
    cannot succeed — each with its own retry, on the account that just told us it
    is out of allowance.

    Asserted on leftover TASKS rather than on request counts, which would make the
    test a race: with cancellation the call leaves nothing pending behind it.

    ⚠ The leak assertion ALONE is vacuous against a half-fix, and mutation testing
    is what showed it: dropping the `cancel()` while keeping the `await gather(...)`
    left the test GREEN, because the blocked workers are then waited out until the
    batch DEADLINE and no task leaks either way. It only took 52s instead of 3s to
    say so. Hence the elapsed-time bound below — promptness is the thing
    cancellation actually buys, so it is the thing to assert."""
    import contextlib
    import time as _time

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_DEADLINE_SECONDS", 5.0)
    never = asyncio.Event()

    class _Quota(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"type": "quota_limit_exceeded", "detail": "monthly limit"}'

    @contextlib.asynccontextmanager
    async def _fake_stream(method, url, **kw):
        if "/filings/1/" in str(url):
            yield httpx.Response(429, stream=_Quota(), request=httpx.Request(method, url))
        else:
            await never.wait()          # a filing that never answers
            yield httpx.Response(200, text=DOC, request=httpx.Request(method, url))

    monkeypatch.setattr(mcp_module._api_client, "stream", _fake_stream)

    before = {t for t in asyncio.all_tasks() if not t.done()}
    started = _time.monotonic()
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2, 3, 4, 5, 6, 7], query="revenue"
        )
    elapsed = _time.monotonic() - started
    leaked = {t for t in asyncio.all_tasks() if not t.done()} - before
    assert not leaked, f"{len(leaked)} worker(s) still running after the batch raised"
    assert elapsed < 2.0, (
        f"took {elapsed:.1f}s against a 5s deadline — the blocked workers were "
        "waited out rather than cancelled"
    )


# --- 12. SPECHT round 9 ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_truncated_filing_with_a_hit_is_also_counted_as_partial(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A hit BEFORE the byte cap and an unread tail after it are both true of the
    same filing. The summary counted it only under 'with hits', so the headline read
    '0 searched only in part' — and the headline is what an LLM summarises from. The
    per-filing detail line did say 'document truncated', which is exactly why this
    survived nine rounds: the two halves of the same output disagreed."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 60)
    doc = "Total revenue was 19,409. " + ("x" * 400) + " total revenue again."
    _mock_md(respx_router, 1, doc)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    head = out.splitlines()[0]
    assert "1 with hits" in head
    assert "0 searched only in part" not in head, (
        "a filing with an unread tail was summarised as fully searched"
    )
    assert "1 searched only in part" in head
    # The per-filing detail must SURVIVE the fix, not be replaced by it.
    assert "document truncated" in out
    # And the overlap has to be named, or the four counts silently stop summing.
    assert "counted BOTH" in out


@pytest.mark.asyncio
async def test_a_fully_read_filing_with_hits_is_not_counted_as_partial(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the test above — the one that fails if the fix over-fires. A
    filing read to the end is not partial, and the overlap note must stay absent."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    head = out.splitlines()[0]
    assert "1 with hits" in head and "0 searched only in part" in head
    assert "counted BOTH" not in out
    assert "document truncated" not in out


@pytest.mark.asyncio
async def test_a_zero_balance_waits_for_outstanding_reservations_before_skipping(
    mcp_module, monkeypatch, fake_access_token
):
    """A zero BALANCE is not a spent BUDGET.

    The budget sits at its floor (per-filing x concurrency) and reservations are
    up-front, so a worker that fills its WHOLE allowance refunds nothing. A later
    worker then found `budget["bytes"] <= 0` and reported its filing as not
    searched while the other reservations were still outstanding and about to
    refund almost all of them — the exact failure the `_BATCH_MAX_TOTAL_BYTES`
    comment claimed the floor made impossible.

    Filing 1 fills its full allowance (refund 0). Filing 2 still holds its
    reservation when filing 3 is admitted. Filing 3 must be SEARCHED."""
    import contextlib

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 100)
    monkeypatch.setattr(mcp_module, "_BATCH_CONCURRENCY", 2)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 200)
    monkeypatch.setattr(mcp_module, "_BATCH_DEADLINE_SECONDS", 5.0)

    @contextlib.asynccontextmanager
    async def _fake_stream(method, url, **kw):
        s = str(url)
        if "/filings/1/" in s:
            # 500 bytes against a 100-byte allowance: spends it all, refunds none.
            yield httpx.Response(200, text="z" * 500, request=httpx.Request(method, url))
        elif "/filings/2/" in s:
            # Holds its 100-byte reservation open past filing 3's admission.
            await asyncio.sleep(0.2)
            yield httpx.Response(200, text=OTHER, request=httpx.Request(method, url))
        else:
            yield httpx.Response(200, text=DOC, request=httpx.Request(method, url))

    monkeypatch.setattr(mcp_module._api_client, "stream", _fake_stream)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )
    assert "budget spent" not in out, (
        "filing 3 was called unsearchable while 100 bytes were still reserved by "
        "a read that had not finished"
    )
    assert "=== filing 3" in out


@pytest.mark.asyncio
async def test_a_truncated_filing_with_no_hits_is_not_double_counted(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The other control on the partial count — the one that fails if the fix is
    written as "every result with a truncation marker" without excluding the ones
    the two advice lists already carry. That version counts a truncated miss twice
    and fires the overlap note on a filing that has no hits to overlap with."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 40)
    doc = ("x" * 400) + " total revenue was 19,409."   # match sits past the cap
    _mock_md(respx_router, 1, doc)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    head = out.splitlines()[0]
    assert "0 with hits" in head and "1 searched only in part" in head
    assert "counted BOTH" not in out


@pytest.mark.asyncio
async def test_the_budget_wait_does_not_extend_the_batch_deadline(
    mcp_module, monkeypatch, fake_access_token
):
    """Time spent waiting for a reservation is time spent. The read that follows
    must be bounded by what is LEFT of the deadline, so `remaining` is re-read
    after the wait — reusing the value measured before it lets a worker that
    waited run a stream for the full original window and the call overruns its
    advertised bound by up to the wait.

    Filing 3 waits for filing 2's refund and then never answers; the whole call
    must still end at the deadline, not at deadline + wait."""
    import contextlib
    import time as _time

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 100)
    monkeypatch.setattr(mcp_module, "_BATCH_CONCURRENCY", 2)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_TOTAL_BYTES", 200)
    monkeypatch.setattr(mcp_module, "_BATCH_DEADLINE_SECONDS", 1.0)
    never = asyncio.Event()

    @contextlib.asynccontextmanager
    async def _fake_stream(method, url, **kw):
        s = str(url)
        if "/filings/1/" in s:
            yield httpx.Response(200, text="z" * 500, request=httpx.Request(method, url))
        elif "/filings/2/" in s:
            await asyncio.sleep(0.6)
            yield httpx.Response(200, text=OTHER, request=httpx.Request(method, url))
        else:
            await never.wait()
            yield httpx.Response(200, text=DOC, request=httpx.Request(method, url))

    monkeypatch.setattr(mcp_module._api_client, "stream", _fake_stream)

    started = _time.monotonic()
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )
    elapsed = _time.monotonic() - started
    assert elapsed < 1.3, (
        f"took {elapsed:.2f}s against a 1.0s deadline — the 0.6s budget wait was "
        "added to the read window instead of taken out of it"
    )
    assert "Not searched" in out and "3" in out


# --- 13. SPECHT round 12 -----------------------------------------------------

@pytest.mark.asyncio
async def test_the_result_is_bounded_and_says_what_it_dropped(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`_md_scan_hits` spans are `200 + len(query) + 240`, the hit cap is 5 and the
    filing cap is 20, so the result grows as 100 x (475 + len(query)) — past the
    client's documented 150,000-char ceiling for any query over ~1,025 characters.

    Being too long is not the real damage. The host truncates from the END, and
    the per-filing hit details used to be emitted BEFORE the 'No match',
    'Searched only in part' and 'Not searched' blocks — so a truncated result
    drops exactly the disclosure this tool exists to provide, and does it
    invisibly. The bound is ours now, and what it drops is announced."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 1500)
    for fid in (1, 2, 3, 4):
        _mock_md(respx_router, fid, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 4], query="total revenue"
    )
    assert len(out) <= 1500, f"result was {len(out)} chars against a 1500 ceiling"
    assert "hit detail" in out and "omitted" in out, "the drop was silent"
    # An omitted DETAIL must never read as an absence: the headline still counts
    # every filing that matched.
    assert "4 with hits" in out.splitlines()[0]


@pytest.mark.asyncio
async def test_the_disclosure_blocks_outrank_the_hit_details(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The ordering half of the fix, and the half a size assertion cannot see.
    Whatever the budget drops, 'Not searched' and 'Searched only in part' must
    survive — they are the difference between a real absence and an unread
    filing, and they were the last thing in the output."""
    import contextlib

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 900)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_FILING_BYTES", 40)

    @contextlib.asynccontextmanager
    async def _fake_stream(method, url, **kw):
        s = str(url)
        if "/filings/9/" in s:
            yield httpx.Response(404, text="gone", request=httpx.Request(method, url))
        elif "/filings/8/" in s:
            # Truncated at the byte cap with no hit in the part read.
            yield httpx.Response(
                200, text=("x" * 400) + " total revenue", request=httpx.Request(method, url)
            )
        else:
            yield httpx.Response(200, text=DOC, request=httpx.Request(method, url))

    monkeypatch.setattr(mcp_module._api_client, "stream", _fake_stream)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 8, 9], query="total revenue"
    )
    assert len(out) <= 900
    assert "Not searched" in out and "9" in out
    assert "Searched only in part" in out
    assert "UNKNOWN" in out


@pytest.mark.asyncio
async def test_an_ordinary_batch_keeps_every_hit_detail(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: the bound must not fire on a normal call. A cap that trims a
    three-filing search would be a worse bug than the one it fixes."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    for fid in (1, 2, 3):
        _mock_md(respx_router, fid, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="total revenue"
    )
    assert "omitted" not in out
    for fid in (1, 2, 3):
        assert f"=== filing {fid}" in out
    assert "near offset" in out


def test_batch_result_ceiling_matches_the_single_filing_tool(mcp_module):
    """Both reading tools answer to the same host ceiling, so they must hold the
    same number. It lived as a bare `150000` inside filings_markdown_retrieve
    while the batch carried its own copy, and the two agreed only by
    coincidence — a mutation moving the batch's value broke no test (SPECHT
    round 12, mutation Q4). One constant now, and this asserts the identity
    rather than the literal, so raising the host ceiling is a one-line change."""
    assert mcp_module._BATCH_MAX_RESULT_CHARS == mcp_module._MAX_RESULT_CHARS
    assert mcp_module._MAX_RESULT_CHARS == 150_000, (
        "the documented Claude.ai tool-result ceiling; change both tools together"
    )


# --- 14. SPECHT round 13 -----------------------------------------------------

@pytest.mark.asyncio
async def test_a_huge_query_cannot_blow_the_result_ceiling_through_the_headline(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Round 12 budgeted the hit SPANS and left the headline, which echoes the
    query with `!r` and is emitted unconditionally before the budget is computed.
    The schema accepts `query: str` of any length, so the echo alone can pass the
    ceiling — and then host truncation hides the filing outcomes, which is the
    exact failure round 12 existed to prevent, re-entered through the one line
    round 12's own comment called 'fixed prose'."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)
    _mock_md(respx_router, 2, OTHER)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="z" * 200_000
    )
    assert len(out) <= mcp_module._BATCH_MAX_RESULT_CHARS, f"result was {len(out)} chars"
    assert "truncated for display" in out
    assert "200000 chars total" in out, "the real length must still be reported"
    # The outcome blocks are the thing the ceiling protects.
    assert "No match in:" in out


@pytest.mark.asyncio
async def test_bounding_the_echo_does_not_change_what_matches(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The control that matters: only the DISPLAY is cut. A long query that really
    occurs must still be found, or the bound would have changed the search."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    phrase = "material adverse change in the business " * 8   # 320 chars
    _mock_md(respx_router, 1, f"Intro. {phrase} Tail.")

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query=phrase
    )
    assert "1 match(es)" in out
    assert "truncated for display" in out
    assert "=== filing 1" in out


@pytest.mark.asyncio
async def test_the_single_filing_tool_bounds_its_echo_too(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The same defect is in `filings_markdown_search`, which SPECHT did not flag
    because it reviews the diff and that tool's echo is untouched by this PR. It
    is the #1 tool by call volume, and ALL THREE of its result lines quote the
    query back unbounded. Same rule, both tools — as with the hit cap and the
    truncation disclosure before it.

    All three lines are exercised, not one. The first version of this test used a
    non-matching document, so it covered only the two no-match lines: reverting
    the echo on the HIT line left it green, and the mutation pass is what said so
    (R2). That is the fourth time in this PR a control probed only the inputs the
    fix was already thinking about."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    long_q = "y" * 5_000
    single = _tool(mcp_module, "filings_markdown_search")

    # (a) the HIT line — the one R2 showed was uncovered.
    phrase = "material adverse change in the business " * 8   # 320 chars
    _mock_md(respx_router, 1, f"Intro. {phrase} Tail.")
    hit = await single(filing_id=1, query=phrase)
    head = hit.splitlines()[0]
    assert "match(es) for" in head
    assert "truncated for display" in head
    # Asserted on the HEADLINE, not the whole result: the hit's context span is
    # SUPPOSED to contain the matched phrase, so `phrase not in hit` would fail
    # on correct code. The echo is the only thing under test here.
    assert phrase not in head, "the full query was echoed back on the hit line"

    # (b) the untruncated NO-MATCH line.
    _mock_md(respx_router, 2, OTHER)
    miss = await single(filing_id=2, query=long_q)
    assert "truncated for display" in miss
    assert "y" * 1_000 not in miss, "the full query was echoed back on the miss line"

    # (c) the TRUNCATED no-match line, which carries its own echo.
    monkeypatch.setattr(mcp_module, "_MAX_FILING_BYTES", 40)
    _mock_md(respx_router, 3, "x" * 400)
    cut = await single(filing_id=3, query=long_q)
    assert "truncated for display" in cut
    assert "y" * 1_000 not in cut, "the full query was echoed back on the cut-miss line"


@pytest.mark.asyncio
async def test_an_ordinary_query_is_echoed_verbatim(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: a normal query must still appear exactly, with no marker. A bound
    that rewrote every echo would be a worse regression than the one it fixes."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, DOC)

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    assert "'total revenue'" in out
    assert "truncated for display" not in out
