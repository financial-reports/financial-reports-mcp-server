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
    assert "1 with hits, 1 with none, 1 not searched" in out


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
