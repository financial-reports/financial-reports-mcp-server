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
  1. per-filing outcomes are distinct — HIT vs NO MATCH vs UNAVAILABLE vs NOT
     SEARCHED. Collapsing the last two into the second turns "we could not read it"
     into "it isn't there".
  2. the bounds that remain actually bound: the filing count, and the result string.
  3. one unreadable filing does not cost the caller the other answers.
  4. matching is identical to the single-filing tool — now because both reach the
     SAME SERVER MATCHER, not because they share a local scanner.

⛔ #213 MOVED THIS TOOL ONTO `POST /filings/markdown/search/` AND DELETED NINETEEN
TESTS FROM THIS FILE. They are named here rather than quietly dropped, because a
reviewer counting tests sees a suite that got smaller and cannot tell a retirement
from a weakening:

  - the byte budget, its reservation/refund, the `inflight` counter, the condition
    variable, the concurrency semaphore and the local deadline — ten tests across
    SPECHT rounds 7-9 (`..._overspend_the_shared_byte_budget`,
    `..._zero_balance_waits_for_outstanding_reservations...`,
    `..._budget_wait_does_not_extend_the_batch_deadline`, and their siblings). The
    machinery they pinned no longer exists: nothing is downloaded here, so there is
    no shared byte budget to overspend and no worker to starve.
  - the four truncation/partial-counting tests. A byte cap could cut a document, so
    a miss had to be hedged as "searched only in part"; the server reads the whole
    document, so there is no partial read left to disclose and `no_match` is now a
    definite absence. ⇒ THE TESTS WENT BECAUSE THE FALSE-ABSENCE CLASS WENT, which
    is the opposite of a coverage loss.
  - `test_both_tools_share_one_scanner` and `..._per_filing_cap_matches_the_single_
    filing_tool`: the shared local scanner `_md_scan_hits` is gone. Its JOB —
    a batch miss means what a single miss means — is now pinned structurally in
    `tests/test_server_side_search.py`, against the two tools' call sites.
  - `test_a_burst_429_still_degrades_per_filing`: with ONE request there is no
    per-filing degradation to do, so a burst 429 fails the whole call. Replaced by
    `test_a_burst_429_is_retried_once_then_raises` in section 15, which asserts the
    behaviour that actually replaced it rather than leaving the axis untested.
"""
from __future__ import annotations

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


def _mock_search(respx_router, fid, *, hits, total_hits=None, total_chars=1000, status=200):
    """Mock the SERVER-SIDE search endpoint (#166).

    `filings_markdown_search` no longer downloads `/markdown/`, so mocking that
    route leaves the search route unmocked — which makes the tool ERROR. That
    matters for any test asserting an ABSENCE: an erroring tool satisfies
    "X not in out" for free. Every absence assertion below is therefore paired
    with a positive one proving the tool actually ran.
    """
    import json as _json

    body = {
        "filing_id": fid,
        "query": "q",
        "total_chars": total_chars,
        "total_hits": total_hits if total_hits is not None else len(hits),
        "hits": [{"offset": o, "context": c} for o, c in hits],
    }
    respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/search/").mock(
        return_value=httpx.Response(status, text=_json.dumps(body))
    )


def _mock_md(respx_router, fid, text=DOC, status=200):
    respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/").mock(
        return_value=httpx.Response(status, text=text)
    )


def _row(fid, query, status="hit", *, hits=(), total_hits=None, reason=None):
    """ONE row of the endpoint's `results`, in the endpoint's own shape.

    Note `snippet`, NOT `context`: the batch endpoint names the field
    differently from the single-filing one (`_mock_search` above uses
    `context`), and reading the wrong key yields EMPTY snippets rather than an
    error — `...` with nothing between, which renders as a passage that exists
    and is blank. The difference is pinned in section 15.
    """
    row = {"filing_id": fid, "query": query, "status": status}
    if status == "hit":
        row["hits"] = [{"offset": o, "snippet": s} for o, s in hits]
        row["total_hits"] = total_hits if total_hits is not None else len(hits)
    if reason is not None:
        row["reason"] = reason
    return row


def _mock_batch(respx_router, rows, *, status=200, body=None):
    """Mock POST /filings/markdown/search/ and return the respx route.

    Nothing about `rows` is inferred — a test that wants a malformed row says so,
    because surviving a malformed row is itself a behaviour under test. The
    aggregate counters are filled in consistently so a test can never pass by
    accidentally agreeing with a counter the tool deliberately ignores.
    """
    import json as _json

    payload = {
        "results": list(rows),
        "pairs": len(rows),
        "searched": sum(1 for r in rows if r.get("status") in ("hit", "no_match")),
        "hit": sum(1 for r in rows if r.get("status") == "hit"),
        "no_match": sum(1 for r in rows if r.get("status") == "no_match"),
        "unavailable": sum(1 for r in rows if r.get("status") == "unavailable"),
        "skipped": sum(1 for r in rows if r.get("status") == "skipped"),
        "truncated": any(r.get("status") == "skipped" for r in rows),
        "billed_credits": 0,
    }
    return respx_router.post(f"{TEST_API_BASE}/filings/markdown/search/").mock(
        return_value=httpx.Response(
            status, text=_json.dumps(payload if body is None else body)
        )
    )


def _posted(route):
    """The JSON body of the single POST the batch tool made."""
    import json as _json

    assert route.call_count == 1, f"expected exactly 1 POST, got {route.call_count}"
    return _json.loads(route.calls[0].request.content)


# --- 1. the three outcomes stay distinct ------------------------------------

@pytest.mark.asyncio
async def test_hit_nomatch_and_unavailable_are_reported_separately(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The four outcomes the endpoint distinguishes must stay distinct here. Only
    `no_match` is evidence about the document; folding `unavailable` or `skipped`
    into it turns "we could not read it" into "it isn't there"."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "total revenue", "hit", hits=[(12, "...Total revenue was 19,409...")]),
        _row(2, "total revenue", "no_match"),
        _row(3, "total revenue", "unavailable", reason="not_found"),
        _row(4, "total revenue", "skipped", reason="quota"),
    ])

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 4], query="total revenue"
    )

    assert "=== filing 1" in out
    assert "No match" in out and "2" in out.split("No match")[1]
    assert "Unavailable" in out and "not_found" in out
    assert "Not searched in this request" in out and "quota" in out
    assert (
        "1 with hits, 1 with none, 0 searched for only some spellings, "
        "1 unavailable, 1 not searched." in out
    )


@pytest.mark.asyncio
async def test_one_bad_filing_does_not_fail_the_batch(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """One unreadable filing must not cost the caller the others' answers. The
    mechanism moved -- the endpoint reports it per pair instead of a worker
    catching an exception -- and the guarantee is the same."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "total revenue", "hit", hits=[(12, "...Total revenue...")]),
        _row(2, "total revenue", "unavailable", reason="content_missing"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "=== filing 1" in out, "an unavailable filing swallowed the other's answer"
    assert "content_missing" in out


# --- 2. the bounds bound ------------------------------------------------------

@pytest.mark.asyncio
async def test_filing_cap_is_enforced_and_the_overflow_is_announced(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The cap is now the ENDPOINT's `maxItems` (50), not our byte budget's (20).
    Over-long lists must be trimmed HERE and said out loud: sending 51 ids is a
    400, so without the trim the overflow becomes an upstream error instead of a
    note, and silently dropping ids reads as "searched everything, found this"."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    cap = mcp_module._BATCH_MAX_FILINGS
    assert cap == 50, "the endpoint's filing_ids maxItems is 50"
    ids = list(range(1, cap + 6))
    route = _mock_batch(
        respx_router, [_row(f, "total revenue", "no_match") for f in ids[:cap]]
    )

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=ids, query="total revenue"
    )
    assert f"across {cap} filing(s)" in out
    assert f"{len(ids) - cap} filing id(s) beyond" in out
    # And the trim happened before the wire, not just in the prose.
    assert len(_posted(route)["filing_ids"]) == cap


@pytest.mark.asyncio
async def test_duplicate_ids_are_searched_once(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """De-duplication used to be visible as one fetch per filing. With a single
    request the only place it shows is the POST body -- so that is what is
    asserted, rather than a call count that is now always 1."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = _mock_batch(respx_router, [_row(7, "total revenue", "no_match")])
    await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[7, 7, 7], query="total revenue"
    )
    assert _posted(route)["filing_ids"] == [7]


# --- 3. matching is the single-filing tool's, not a second implementation -----

@pytest.mark.parametrize("query,other", [("19409", "19,409"), ("19,409", "19409")])
@pytest.mark.asyncio
async def test_thousands_comma_forms_match_as_in_the_single_filing_tool(
    mcp_module, monkeypatch, fake_access_token, respx_router, query, other
):
    """Filings render figures as "19,409", so both spellings must be tried -- and
    since #213 they go in ONE request as two of the endpoint's three `queries`,
    TYPED FIRST. The old client-side loop sent one request per candidate and
    stopped at the first hit, which cannot work across 50 filings: the typed form
    may hit filing A while only the bare form hits filing B."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = _mock_batch(respx_router, [
        _row(1, query, "no_match"),
        _row(1, other, "hit", hits=[(25, "...was 19,409. Costs...")]),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query=query
    )
    body = _posted(route)
    assert body["queries"] == [query, other], "typed spelling must go first"
    assert "=== filing 1" in out
    assert "No match" not in out.splitlines()[0]
    # WHICH spelling matched is load-bearing: the offsets are hits on that string.
    assert f"matched as {other!r}" in out


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
async def test_untruncated_miss_is_still_a_definite_no_match(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`no_match` is now the ONLY uncertainty-free outcome, and it must read that
    way. Before #213 a miss could have come from a byte-capped read, so the copy
    hedged; the server reads the whole document, so the hedge would now be false
    in the other direction -- telling a model an absence is unreliable sends it to
    re-run 50 single searches."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [_row(1, "total revenue", "no_match")])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    assert "searched IN FULL" in out and "1" in out
    assert "searched only in part" not in out.lower()
    assert "UNKNOWN" not in out, "a definite absence must carry no hedge"


# --- 6. SPECHT round 2: bounds that hide incompleteness -----------------------

@pytest.mark.asyncio
async def test_hit_cap_reached_is_announced(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Four occurrences, cap of three. Reporting "3 match(es)" silently lets a
    client read an incomplete answer as a complete one.

    ⭐ AND THE NUMBER IS NOW EXACT. The local scanner could only ever say "more
    than the cap", because it stopped at cap+1; the server counts every match in
    the document, so the caller learns HOW MANY were hidden instead of merely
    that some were."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "revenue", "hit",
             hits=[(0, "a"), (8, "b"), (16, "c")], total_hits=4),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue", max_hits_per_filing=3
    )
    assert "showing the first 3 of 4" in out
    assert "exact total" in out
    assert "=== filing 1 — 3 match(es)" in out


@pytest.mark.asyncio
async def test_exactly_at_the_cap_is_not_announced_as_overflow(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: exactly three of three is complete. Without this the signal could
    fire on every capped result and would carry no information."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "revenue", "hit",
             hits=[(0, "a"), (8, "b"), (16, "c")], total_hits=3),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue", max_hits_per_filing=3
    )
    assert "showing the first" not in out
    assert "=== filing 1 — 3 match(es) ===" in out


@pytest.mark.asyncio
async def test_upstream_status_is_reported_not_swallowed(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A non-2xx on the batch POST fails the WHOLE call now -- there is no per-filing
    degradation left to do -- and the upstream status must survive into the error.
    Reading the wrong attribute (`status_code` instead of `upstream_status`) made
    404, 429 and 500 all render as a bare "upstream error"."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [], status=500, body={"detail": "boom"})
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    assert exc.value.upstream_status == 500


# --- 7. the SAME rule applied to the single-filing tool (the #1 tool by volume) ---
# "empty + notice != empty" (ui-fr, web#7880): a restricted or partial result must
# announce its restriction in a way the consumer acts on. ~46-58% of live calls to
# filings_markdown_search land exactly ON the hit cap, so reporting the capped count
# as a total was wrong about half the time.

@pytest.mark.asyncio
async def test_single_tool_announces_the_hit_cap(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Re-pointed for #166: the count is now EXACT. Scanning cap+1 could only say
    "more than cap"; the endpoint returns total_hits over the whole document, so
    the notice says how many were hidden."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(respx_router, 1, hits=[(i, f"revenue {i}") for i in (0, 8, 16)], total_hits=6)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="revenue", max_hits=3
    )
    assert "3 match(es)" in out
    assert "hit cap reached" in out and "6 match(es) exist in total" in out


@pytest.mark.asyncio
async def test_single_tool_exactly_at_cap_is_not_flagged(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: without this the fix marks every capped result uncertain and the
    signal carries no information."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(respx_router, 1, hits=[(i, f"revenue {i}") for i in (0, 8, 16)], total_hits=3)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="revenue", max_hits=3
    )
    # ⚠ POSITIVE GUARD FIRST. This test asserts an ABSENCE, and when #166
    # switched the tool to the search endpoint this file still mocked
    # `/markdown/` — so the tool returned "Error calling …" and the assertion
    # passed on an error string. It stayed green and meant nothing. An absence
    # assertion needs proof the subject ran.
    assert "3 match(es)" in out, f"the tool did not run: {out!r}"
    assert "hit cap reached" not in out


@pytest.mark.asyncio
async def test_the_truncated_miss_CANNOT_HAPPEN_any_more(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """RETIRED AND REPLACED, not re-pointed — the condition it guarded is gone.

    It asserted that a miss in a document cut at `_MAX_FILING_BYTES` reports
    TRUNCATED and unknown rather than a bare "No match". #166 moved the match
    server-side, so the client never truncates and the whole document is always
    searched. ⇒ The old assertion is unsatisfiable by correct code, and keeping
    it re-pointed would have meant inventing a truncation path to keep a test.

    So this asserts the STRONGER property that replaced it: the tool no longer
    has a truncation story to tell, and says how much it searched."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(respx_router, 1, hits=[], total_hits=0, total_chars=480000)
    out = await _tool(mcp_module, "filings_markdown_search")(
        filing_id=1, query="total revenue"
    )
    assert "No match for" in out, f"the tool did not run: {out!r}"
    assert "truncat" not in out.lower() and "unknown" not in out.lower()
    assert "480000" in out, "the searched size is not reported"


@pytest.mark.asyncio
async def test_single_tool_untruncated_miss_stays_definite(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(respx_router, 1, hits=[], total_hits=0, total_chars=len(OTHER))
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
    """A revoked token 403s the request. Rendering that as "0 match(es) across 2
    filing(s)" reports the CALL as successful and hides an auth failure from any
    client branching on MCP error status (#104).

    ⚠ 403 is ALSO what the endpoint's own access gate returns for a plan that does
    not include it -- but NOT what its allowlist gate returns, which is a 404 by
    design so there is no 403 oracle. Either way it is a whole-call fact, never a
    per-filing one."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [], status=403, body={"detail": "forbidden"})
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )


@pytest.mark.asyncio
async def test_a_missing_filing_still_degrades_per_filing(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the above: a missing FILING is a per-filing fact and must not
    end the batch. The endpoint says so with `unavailable`/`not_found` inside a
    200, so the discrimination that used to live in a worker's except clause now
    lives in the response -- and must still be rendered rather than collapsed."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "total revenue", "hit", hits=[(12, "...Total revenue...")]),
        _row(2, "total revenue", "unavailable", reason="not_found"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "=== filing 1" in out
    assert "Unavailable" in out and "not_found" in out
    assert "treat as UNKNOWN" in out


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


# --- 10. SPECHT round 7 ------------------------------------------------------

@pytest.mark.asyncio
async def test_account_wide_429_raises_rather_than_degrading(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """`quota_exhausted` / spend-cap / spend-ceiling are facts about the ACCOUNT.
    They must raise, and -- the half that is easy to lose on a POST -- they must
    NOT be retried: `_api_post` shares `_retry_delay` with `_api_get`, so a
    non-retryable 429 spends no second request to be told the same thing."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.post(f"{TEST_API_BASE}/filings/markdown/search/").mock(
        return_value=httpx.Response(
            429, json={"type": "quota_limit_exceeded", "detail": "monthly limit"}
        )
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    assert exc.value.error_kind == "quota_exhausted"
    assert route.call_count == 1, "a non-retryable 429 must not be retried"


# --- 11. SPECHT round 8 ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_batch_where_nothing_was_searched_is_an_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """With zero searched filings there is no answer to protect, and "0 match(es)
    across 2 filing(s)" tells a client branching on error status that the corpus
    was searched and is empty (#104).

    ⭐ #213 WIDENED THIS FROM `unavailable` TO NOT-SEARCHED-AT-ALL, which now
    includes `skipped`: an all-skipped batch (an API-side quota or deadline)
    searched nothing either, and rendering it as an empty result is the same
    false absence one status over. The per-filing reasons are carried into the
    error, so nothing the successful-looking string would have said is lost."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "revenue", "unavailable", reason="not_processed"),
        _row(2, "revenue", "skipped", reason="deadline"),
    ])
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    msg = str(exc.value)
    assert "not_processed" in msg and "deadline" in msg, "per-filing reasons lost"
    assert "not an empty result" in msg


@pytest.mark.asyncio
async def test_one_survivor_still_returns_the_partial_answer(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """CONTROL for the above, and the line the error must not cross: ONE searched
    filing is an answer, so the others failing must not cost the caller it. Note
    the survivor here is a `no_match`, not a hit -- the error is keyed on nothing
    being SEARCHED, never on nothing being FOUND."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "revenue", "no_match"),
        _row(2, "revenue", "unavailable", reason="not_found"),
        _row(3, "revenue", "skipped", reason="quota"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3], query="revenue"
    )
    assert "searched IN FULL" in out
    assert "Unavailable" in out and "Not searched in this request" in out


@pytest.mark.asyncio
async def test_every_filing_searched_with_no_match_is_not_an_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """SECOND CONTROL, and the one that matters most: a definite "searched it all,
    it isn't there" is a RESULT. Keying the error on "no hits" instead of on
    "nothing was searched" would turn every honest negative into an error -- a far
    worse bug than the one being prevented."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "total revenue", "no_match"),
        _row(2, "total revenue", "no_match"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="total revenue"
    )
    assert "0 match(es)" in out
    assert "searched IN FULL and the term is not in them: 1, 2" in out


# --- 12. SPECHT round 9 ------------------------------------------------------

# --- 13. SPECHT round 12 -----------------------------------------------------

@pytest.mark.asyncio
async def test_the_result_is_bounded_and_says_what_it_dropped(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The endpoint returns up to `max_hits_per_filing` snippets of ~440 characters
    per pair, so 50 filings x 10 hits is ~240,000 characters -- over the client's
    documented 150,000 ceiling by itself.

    ⚠ BOTH TERMS GREW WITH #213 (20->50 filings, 5->10 hits), so this bound went
    from one that rarely fired to one that fires at the documented maximum.
    Being too long is not the real damage: the host truncates from the END, and
    the per-filing outcome blocks are what a truncation would eat."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 1500)
    span = "x" * 440
    _mock_batch(respx_router, [
        _row(f, "total revenue", "hit", hits=[(0, span), (500, span)])
        for f in (1, 2, 3, 4)
    ])

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
    Whatever the budget drops, the not-searched and unavailable blocks must
    survive -- they are the difference between a real absence and an unread
    filing, and they used to be the LAST thing in the output."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 1100)
    span = "x" * 440
    _mock_batch(respx_router, [
        _row(1, "total revenue", "hit", hits=[(0, span), (500, span)]),
        _row(2, "total revenue", "hit", hits=[(0, span), (500, span)]),
        _row(3, "total revenue", "hit", hits=[(0, span), (500, span)]),
        _row(8, "total revenue", "skipped", reason="byte_budget"),
        _row(9, "total revenue", "unavailable", reason="not_found"),
    ])

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 8, 9], query="total revenue"
    )
    assert len(out) <= 1100
    assert "Not searched in this request" in out and "byte_budget" in out
    assert "Unavailable" in out and "not_found" in out
    assert "UNKNOWN" in out
    assert "omitted" in out, "the hit detail should be what gives way, not the disclosure"


@pytest.mark.asyncio
async def test_an_ordinary_batch_keeps_every_hit_detail(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: the bound must not fire on a normal call. A cap that trimmed a
    three-filing search would be a worse bug than the one it fixes."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(f, "total revenue", "hit", hits=[(12, "...Total revenue was 19,409...")])
        for f in (1, 2, 3)
    ])

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
async def test_a_huge_query_is_refused_before_the_request_not_echoed_into_the_ceiling(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """SPECHT round 13 found that the headline echoes the query with `!r` and is
    emitted unconditionally before the result budget is computed, so a
    200,000-character query could pass the 150,000-char ceiling on its own -- and
    host truncation then hides the per-filing outcomes, the exact failure round 12
    existed to prevent, re-entered through the one line round 12's own comment
    called "fixed prose".

    ⭐ #213 CLOSES IT A LEVEL EARLIER AND THE OLD ASSERTION NO LONGER HOLDS: the
    input guard refuses the query outright, so there is no echo to bound and no
    request to pay for. The round-13 defence is still in the code and is now
    unreachable -- which is a strictly better place to be, and only visible
    because this test was rewritten rather than left asserting a truncation that
    can no longer happen."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = _mock_batch(respx_router, [_row(1, "x", "no_match")])

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="z" * 200_000
    )
    assert len(out) <= mcp_module._BATCH_MAX_RESULT_CHARS, f"result was {len(out)} chars"
    assert "200000" in out, "the real length must still be reported"
    assert "200 characters" in out
    assert route.call_count == 0, "a 200,000-char query was sent to the API"


@pytest.mark.asyncio
async def test_the_batch_inherits_the_input_bound_so_its_echo_bound_is_dead_too(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ REPLACES `test_bounding_the_echo_does_not_change_what_matches`, and the
    replacement exists because the first version of this test HEDGED -- it
    asserted `queries in ([phrase], [])`, which is what you write when you have
    not worked out which one it is.

    Working it out found a real regression the move introduced. `_md_candidates`
    always returns the typed query FIRST, so the length filter on the candidate
    list cannot fall back to anything: on a 320-character query it drops the only
    candidate, and the tool would POST `queries: []` against a `minItems: 1`
    serializer -- turning what used to be a free local no-op into an upstream 400
    after a round trip. Fixed by giving the batch the same input guard the
    single-filing tool has had since #173.

    ⇒ And that makes `_echo_query`'s truncation branch unreachable here as well:
    `_MAX_QUERY_CHARS` and `_QUERY_ECHO_CHARS` are both 200, so no query that
    survives the guard can be long enough to truncate. Asserted by ARITHMETIC
    below rather than by inspection, because a dead branch passes lint, passes
    mutation testing on the paths that do run, and reads as defence-in-depth."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = _mock_batch(respx_router, [_row(1, "x", "no_match")])

    phrase = "material adverse change in the business " * 8   # 320 chars raw
    assert len(phrase) > mcp_module._MAX_QUERY_CHARS, "the premise"
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query=phrase
    )
    assert "200 characters" in out, "an over-long query should be refused, not sent"
    # ⚠ The reported length is of the STRIPPED query -- 319 here, not the 320 the
    # literal suggests, because the repetition leaves a trailing space. Computed
    # rather than typed: the first version of this assertion hard-coded 320 and
    # went red, which is the guard being RIGHT and the test being wrong. A
    # hard-coded number in a message assertion is a second, unmaintained copy of
    # an arithmetic the code already does.
    assert str(len(phrase.strip())) in out, "the message should name the actual length"
    assert route.call_count == 0, (
        "an over-long query reached the API, where queries are maxLength 200 — "
        "the round trip is paid for a request the serializer rejects"
    )
    assert "truncated for display" not in out, (
        "the echo bound fired, so the input guard did not — they overlap and the "
        "input guard must win"
    )
    assert mcp_module._MAX_QUERY_CHARS <= mcp_module._QUERY_ECHO_CHARS, (
        "if the input bound ever exceeds the echo bound, this tool can echo an "
        "unbounded query again and the retired round-13 test needs reinstating"
    )


@pytest.mark.asyncio
async def test_the_single_filing_tools_echo_bound_is_now_UNREACHABLE(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ REPLACES a test that asserted this tool TRUNCATES a long echo. It cannot
    any more, and the replacement asserts the stronger property instead.

    #173 added an INPUT bound: `len(raw) > _MAX_QUERY_CHARS` (200) is refused
    locally, because `q` now crosses the wire into web's parse_search() which
    400s above 200. `_QUERY_ECHO_CHARS` is ALSO 200 — so on this tool
    `len(raw) <= _QUERY_ECHO_CHARS` is now always true and the truncation branch
    is DEAD CODE. The old test fed it 320- and 5,000-character queries, which the
    guard refuses before any echo happens.

    ⛔ THIS PARAGRAPH PREDICTED ITS OWN EXPIRY AND #213 CASHED IT, five days later.
    It read: "the BATCH tool still scans client-side, has no server-side query
    bound, and is where the unbounded echo was originally found ... the helper
    stays load-bearing until the batch half of #166 lands and inherits the same
    200-char bound, at which point it can retire." The batch moved onto
    POST /filings/markdown/search/, whose `queries` items are `maxLength: 200`,
    so it now carries the SAME input guard — see
    `test_the_batch_inherits_the_input_bound_so_its_echo_bound_is_dead_too`.
    ⇒ `_echo_query`'s truncation branch is therefore unreachable from BOTH call
    sites, and the helper is kept rather than retired only as cheap defence for a
    future third caller. The arithmetic assertion at the end of each of the two
    tests is what tells the next author it is dead code rather than a live guard.
    ⚠ Worth noticing HOW this was caught: not by reading the test, which stayed
    green, but by changing the other tool and then asking what this docstring had
    claimed about it. A test's prose goes stale exactly like a comment's, and
    nothing in CI reads it.

    ⚠ The transferable bit: a LATER, STRONGER guard silently made an EARLIER one
    unreachable, and the only thing that said so was this test going red. Nothing
    else would have — a dead branch passes lint, passes mutation testing on the
    paths that do run, and reads as defence-in-depth."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    single = _tool(mcp_module, "filings_markdown_search")
    calls = {"n": 0}

    def _count(request):
        calls["n"] += 1
        return httpx.Response(200, json={
            "filing_id": 1, "query": "x", "total_chars": 10,
            "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/search/").mock(side_effect=_count)

    # Exactly the input the retired test used, now refused rather than truncated.
    phrase = "material adverse change in the business " * 8   # 320 chars
    assert len(phrase) > mcp_module._QUERY_ECHO_CHARS, "the premise of the old test"
    out = await single(filing_id=1, query=phrase)
    assert "200 characters" in out, "an over-long query should be refused, not echoed"
    assert "truncated for display" not in out, (
        "the echo bound fired, so the input guard did not — they overlap and the "
        "input guard must win, or the API is paid for a query it will reject"
    )
    assert calls["n"] == 0, "an over-long query reached the API"

    # And the dead branch is dead by ARITHMETIC, not by inspection: no reachable
    # input can be longer than the echo bound when the two constants are equal.
    assert mcp_module._MAX_QUERY_CHARS <= mcp_module._QUERY_ECHO_CHARS, (
        "if the input bound ever exceeds the echo bound, this tool can echo an "
        "unbounded query again and the retired test needs reinstating"
    )


@pytest.mark.asyncio
async def test_an_ordinary_query_is_echoed_verbatim(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control: a normal query must still appear exactly, with no marker. A bound
    that rewrote every echo would be a worse regression than the one it fixes."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [_row(1, "total revenue", "no_match")])

    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
    )
    assert "'total revenue'" in out
    assert "truncated for display" not in out


# --- 15. #213: the move onto POST /filings/markdown/search/ -------------------

@pytest.mark.asyncio
async def test_the_batch_issues_ONE_request_and_downloads_no_documents(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The whole point of the move. Before #213 a 5-filing batch made 5 streaming
    GETs of up to 10 MB each to return ~440 characters per hit.

    The `/markdown/` route is deliberately NOT mocked: respx fails an unmocked
    request, so if any download survived the refactor this test errors rather
    than passing quietly. That is the positive control -- an assertion on a call
    count of zero would pass just as well against a tool that never ran."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = _mock_batch(respx_router, [
        _row(f, "total revenue", "hit", hits=[(12, "...Total revenue...")])
        for f in (1, 2, 3, 4, 5)
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 4, 5], query="total revenue"
    )
    assert route.call_count == 1, "one batch call, not one per filing"
    assert "5 with hits" in out, "the tool must actually have produced a result"


def test_the_client_side_scanner_and_its_bounds_are_GONE(mcp_module):
    """An anti-regression, not a tautology: re-introducing a local scan is a
    plausible future "optimisation" (it would avoid an API round trip), and it
    would silently re-open the matcher divergence #213 closed -- the local scanner
    never learned the split-phrase matching web#10487 shipped.

    ⚠ Asserted against the RENDERED module, because the generator holds the whole
    tool as template TEXT: a grep of `scripts/generate_mcp_tools.py` sees the
    names inside the comment that explains their removal and reports them
    present. The control is the next line: `_md_candidates` IS still there, so
    this is not an import that silently failed."""
    assert hasattr(mcp_module, "_md_candidates"), "control: the module did load"
    assert not hasattr(mcp_module, "_md_scan_hits")
    for gone in (
        "_BATCH_MAX_FILING_BYTES",
        "_BATCH_CONCURRENCY",
        "_BATCH_MAX_TOTAL_BYTES",
        "_BATCH_DEADLINE_SECONDS",
    ):
        assert not hasattr(mcp_module, gone), f"{gone} came back"


@pytest.mark.asyncio
async def test_the_batch_reads_snippet_NOT_context(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ THE TWO ENDPOINTS NAME THE FIELD DIFFERENTLY: the single-filing search
    returns `hits[].context`, the batch returns `hits[].snippet`. Reading the
    wrong key does not error -- it yields an EMPTY span, which renders as
    `......`, a passage that exists and is blank. So the failure mode is a
    confident empty quote rather than a crash, and only an assertion on the
    TEXT catches it.

    The negative control is the second row: a hit carrying only `context` must
    come back empty, proving this test would fail if the accessor were changed
    back rather than passing on both."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    import json as _json
    body = {
        "results": [
            {"filing_id": 1, "query": "revenue", "status": "hit", "total_hits": 1,
             "hits": [{"offset": 5, "snippet": "SNIPPET-FIELD"}]},
            {"filing_id": 2, "query": "revenue", "status": "hit", "total_hits": 1,
             "hits": [{"offset": 5, "context": "CONTEXT-FIELD"}]},
        ],
        "pairs": 2, "searched": 2, "hit": 2, "no_match": 0,
        "unavailable": 0, "skipped": 0, "truncated": False, "billed_credits": 0,
    }
    respx_router.post(f"{TEST_API_BASE}/filings/markdown/search/").mock(
        return_value=httpx.Response(200, text=_json.dumps(body))
    )
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="revenue"
    )
    assert "SNIPPET-FIELD" in out, "the documented field was not read"
    assert "CONTEXT-FIELD" not in out, "control: the single tool's field is not read here"


@pytest.mark.asyncio
async def test_some_spellings_searched_and_some_not_is_NOT_an_absence(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The one outcome the endpoint's four statuses cannot express, because it is a
    fact about the SET of queries this tool sent rather than about any one pair.

    A numeric query goes out as two spellings. If the typed one returns `no_match`
    and the other is `skipped`, folding the filing into "no match" would claim the
    term is absent when a spelling of it was never tried -- the same false absence
    the byte cap used to produce, arriving on the query axis instead."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "19,409", "no_match"),
        _row(1, "19409", "skipped", reason="deadline"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="19,409"
    )
    assert "1 searched for only some spellings" in out
    assert "UNKNOWN rather than absent" in out
    assert "'19409'" in out and "deadline" in out
    # And it must NOT also be counted as a definite absence.
    assert "searched IN FULL" not in out


@pytest.mark.asyncio
async def test_a_burst_429_is_retried_once_then_raises(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Replaces `test_a_burst_429_still_degrades_per_filing`, whose subject is gone:
    with ONE request there is no per-filing degradation to do, so a burst limit is
    a whole-call fact. It must still be treated as the TRANSIENT thing it is --
    retried once by `_api_post` -- and then raise rather than render as an empty
    result. The body is not a JSON type prefix, so `_classify_upstream_429` routes
    it to `rate_limited`, which is the retryable class."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_RETRY_BACKOFF", 0.0)
    monkeypatch.setattr(mcp_module, "_RETRY_JITTER", 0.0)
    route = respx_router.post(f"{TEST_API_BASE}/filings/markdown/search/").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module, "filings_markdown_search_batch")(
            filing_ids=[1, 2], query="revenue"
        )
    assert exc.value.upstream_status == 429
    assert route.call_count == 2, "a burst 429 should be retried exactly once"


@pytest.mark.asyncio
async def test_a_filing_the_endpoint_omits_is_reported_not_dropped(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The endpoint contracts that every (filing_id, query) pair comes back exactly
    once, so this is unreachable on a conforming response -- which is why it is
    worth a test. A filing that silently vanished from the output would be counted
    in neither the hits nor the absences, and the only clue would be arithmetic
    that no longer sums."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [_row(1, "revenue", "no_match")])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2], query="revenue"
    )
    assert "across 2 filing(s)" in out
    assert "2" in out.split("Unavailable")[1]
    assert "no result row returned" in out


@pytest.mark.parametrize("requested,expected", [(50, 10), (0, 1), (-3, 1), (3, 3)])
@pytest.mark.asyncio
async def test_max_hits_per_filing_is_clamped_to_the_endpoints_range(
    mcp_module, monkeypatch, fake_access_token, respx_router, requested, expected
):
    """1-10 at the endpoint (it was 1-5 here while every extra hit was 475 more
    characters of a locally scanned document). Clamping rather than erroring is
    deliberate -- a model that asks for 50 should get 10 snippets, not a
    validation failure -- but the value must be clamped BEFORE the wire, because
    11 is a 400."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    # ⚠ ONE call per test, because re-registering the same respx route returns a
    # route whose `call_count` includes the EARLIER call -- so a second
    # `_mock_batch` in one test makes `_posted`'s exactly-one-POST assertion
    # fail on a tool that behaved correctly. Parametrized instead of calling
    # twice; the first version did the latter and went red for that reason alone.
    route = _mock_batch(respx_router, [_row(1, "revenue", "no_match")])
    await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue", max_hits_per_filing=requested
    )
    assert _posted(route)["max_hits_per_filing"] == expected


def test_the_description_no_longer_warns_it_matches_LESS(mcp_module):
    """The copy change IS the fix, not housekeeping. While the batch scanned
    locally it genuinely matched less than `filings_markdown_search`, and said so;
    both tools now reach the same server matcher, so leaving the warning would
    send a model to re-run 50 single searches to confirm an absence this tool
    already established.

    Whitespace is normalised because a wrapped docstring puts a newline and
    indentation inside a phrase -- an `assert ... not in` would otherwise pass on
    a formatting accident while the stale claim sat in the copy."""
    tool = mcp_module.mcp._tool_manager._tools["filings_markdown_search_batch"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    doc = " ".join((fn.__doc__ or "").split())
    assert "NARROWER THAN" not in doc
    assert "re-run it through filings_markdown_search" not in doc
    assert "SAME MATCHER AS filings_markdown_search" in doc
    # The absence assertions above are only meaningful if the docstring loaded.
    assert "Max 50 filings per call." in doc


def test_every_outcome_the_tool_RENDERS_is_also_DESCRIBED(mcp_module):
    """⛔ FOUND BY READING THE NEW DOCSTRING AS PROSE (PROCESS.md Phase 4.6), AFTER
    the code was written, the tests passed and the generator was clean.

    The first version said "Each filing comes back with ONE outcome" and then
    listed FOUR, while the renderer emits a FIFTH — "searched for only some
    spellings", the per-filing case where one spelling of a number was searched
    and the other was `skipped`. A model would have met that phrase in a headline
    with no definition for it anywhere, which is worse than not reporting it:
    an undefined outcome reads as a variant of whichever defined one is nearest,
    and the nearest is "no match".

    ⇒ So this test pins the two sides TOGETHER rather than the copy alone. It is
    the only gate in the suite that compares what the renderer can emit against
    what the description admits exists — mutation testing pins the code, the
    description tests pin the copy, and neither notices that they disagree."""
    tool = mcp_module.mcp._tool_manager._tools["filings_markdown_search_batch"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    doc = " ".join((fn.__doc__ or "").split())
    assert doc, "control: the docstring loaded"
    for phrase in (
        "NO MATCH",
        "UNAVAILABLE",
        "NOT SEARCHED",
        "SEARCHED FOR ONLY SOME SPELLINGS",
    ):
        assert phrase in doc, f"the tool can report {phrase!r} and never defines it"
    assert "last three as UNKNOWN" in doc, (
        "the count of outcomes that are NOT evidence of absence must track the "
        "list above it — it said 'last two' while the list had grown to five"
    )
