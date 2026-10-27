"""`filings_markdown_search_batch` — one query across N filings in one call.

Why the tool exists: 90.7% of `filings_markdown_search` calls in prod are the same
query repeated across 2+ filings (53 episodes averaging 287 calls each, worst 1,401
calls over 565 filings). See financial-reports/web#8000 for the measurements and for
the server-side endpoint that would make this cheaper still.

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
    that outlives the batch deadline is an unknown, never an absence."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_DEADLINE_SECONDS", 0.25)

    async def _slow(*_a, **_kw):
        await asyncio.sleep(5)

    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(side_effect=_slow)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="total revenue"
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
    the caller could not tell a missing filing from a rate limit."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_md(respx_router, 1, "nope", status=429)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="revenue"
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
