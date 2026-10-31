"""#166 — `filings_markdown_search` calls the search ENDPOINT, not a whole download.

The tool fetched `/filings/{id}/markdown/` in full (up to `_MAX_FILING_BYTES`,
10 MB) and scanned client-side, to return ~440 characters. The API's own
`GET /filings/{id}/markdown/search/` does the same match server-side.

What the switch buys, measured rather than assumed (see the issue):
  - the 10 MB no longer crosses the MCP↔API hop, per search
  - MCP-side memory and latency, which is what the batch byte budget bounded
  - ⭐ and the CORRECTNESS win nobody asked for: the byte cap could truncate a
    document, so a miss was UNKNOWN rather than absent. The server reads the
    whole document, so **that false-absence class disappears at the source** and
    the truncation disclosure has nothing left to disclose.
  - `total_hits` is EXACT, where scanning cap+1 could only say "more than cap"

What it must NOT change (the issue's acceptance list):
  - the thousands-comma fallback: "19409" must still match "19,409"
  - ~440 chars of context, document order, offsets usable by the retrieve tool
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

SEARCH = "/filings/1/markdown/search/"


def _tool(mcp_module, name):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _hit(offset, span):
    return {"offset": offset, "context": span}


@pytest.mark.asyncio
async def test_search_calls_the_endpoint_and_never_downloads_the_document(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The load-bearing assertion: `/markdown/` is NOT fetched at all.

    A negative control on the download route, not just a positive one on the
    search route — because a tool that called BOTH would pass an
    endpoint-was-called test while still moving 10 MB."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    downloaded = {"n": 0}

    def _count_download(request):
        downloaded["n"] += 1
        return httpx.Response(200, text="x" * 1000)

    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(side_effect=_count_download)
    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(
        return_value=httpx.Response(200, json={
            "filing_id": 1, "query": "total revenue", "total_chars": 480000,
            "total_hits": 2, "hits": [_hit(31, "Total revenue was 19,409.")],
        })
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="total revenue")
    assert downloaded["n"] == 0, "the tool still downloaded the whole markdown"
    assert "19,409" in out and "offset 31" in out


@pytest.mark.asyncio
async def test_total_hits_comes_from_the_server_and_is_exact(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Scanning `cap + 1` could only ever say "more than cap". The endpoint
    returns `total_hits` over the whole document, so the count is exact and the
    hit-cap notice can say how many were hidden rather than that some were."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(
        return_value=httpx.Response(200, json={
            "filing_id": 1, "query": "revenue", "total_chars": 480000,
            "total_hits": 97, "hits": [_hit(i, f"ctx {i}") for i in (10, 20, 30, 40, 50)],
        })
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="revenue", max_hits=5)
    assert "97" in out, f"the exact total is not reported: {out!r}"


@pytest.mark.asyncio
async def test_the_thousands_comma_fallback_is_preserved(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The issue's first preservation concern, and the only one the endpoint does
    not do itself: it documents a plain case-insensitive substring match with no
    numeric normalisation. `_md_candidates` turns "19409" into
    ["19409", "19,409"], so the tool asks the endpoint once per spelling and
    stops at the first that hits. Verified free: the day-dedup keys on
    (user, filing), not on the endpoint."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    asked = []

    def _by_q(request):
        q = dict(request.url.params).get("q")
        asked.append(q)
        if q == "19,409":
            return httpx.Response(200, json={
                "filing_id": 1, "query": q, "total_chars": 480000,
                "total_hits": 1, "hits": [_hit(31, "Total revenue was 19,409.")],
            })
        return httpx.Response(200, json={
            "filing_id": 1, "query": q, "total_chars": 480000,
            "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_by_q)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="19409")
    assert asked == ["19409", "19,409"], f"candidate order wrong: {asked}"
    assert "19,409" in out, f"the comma form did not reach the caller: {out!r}"


@pytest.mark.asyncio
async def test_a_non_numeric_query_asks_once(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the above — the second call must fire ONLY for the numeric
    case, or every ordinary search doubles its request count."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    asked = []

    def _miss(request):
        asked.append(dict(request.url.params).get("q"))
        return httpx.Response(200, json={
            "filing_id": 1, "query": "x", "total_chars": 100, "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_miss)
    await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="going concern")
    assert asked == ["going concern"], f"asked more than once: {asked}"


@pytest.mark.asyncio
async def test_a_miss_is_now_DEFINITE_and_says_so(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⭐ The correctness win. The byte cap meant a miss could be UNKNOWN — the
    tail was never read — and the tool had to say so. The server searches the
    WHOLE document, so a miss is now an absence and the truncation caveat must
    be GONE rather than reworded."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(
        return_value=httpx.Response(200, json={
            "filing_id": 1, "query": "going concern", "total_chars": 480000,
            "total_hits": 0, "hits": [],
        })
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="going concern")
    assert "No match" in out
    low = out.lower()
    assert "truncat" not in low, f"a truncation caveat survived the switch: {out!r}"
    assert "unknown" not in low, f"the miss is still hedged as unknown: {out!r}"
    assert "480000" in out, "the document size the server searched is not reported"


@pytest.mark.asyncio
async def test_an_upstream_error_still_raises_rather_than_reading_as_a_miss(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """#104's contract, unchanged by the switch: an upstream failure must stay
    distinguishable from a result. A 403 that returned "No match" would be the
    false absence this whole tool family exists to prevent."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(
        return_value=httpx.Response(403, text='{"detail":"plan does not include markdown"}')
    )
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="revenue")


@pytest.mark.asyncio
async def test_the_first_hitting_candidate_wins_and_is_not_overwritten(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Mutation B2: dropping the `break` left the earlier test GREEN, because in
    "19409" → ["19409", "19,409"] the HITTING spelling happens to be LAST, so
    running on and keeping the final payload gave the same answer by luck of
    ordering.

    Here the FIRST candidate hits and the second misses — the only arrangement
    that can tell "stops at the first hit" from "keeps whatever came last". A
    query of "19,409" yields candidates ["19409", "19,409"] via the bare form,
    so a document written WITHOUT separators hits on candidate one."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    asked = []

    def _first_hits(request):
        q = dict(request.url.params).get("q")
        asked.append(q)
        if q == "19409":
            return httpx.Response(200, json={
                "filing_id": 1, "query": q, "total_chars": 900,
                "total_hits": 1, "hits": [_hit(12, "unseparated 19409 here")],
            })
        return httpx.Response(200, json={
            "filing_id": 1, "query": q, "total_chars": 900, "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_first_hits)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="19,409")
    assert asked == ["19409"], f"it kept asking after a hit: {asked}"
    assert "unseparated 19409 here" in out, f"the first hit was overwritten: {out!r}"


@pytest.mark.asyncio
async def test_max_hits_is_passed_to_the_endpoint(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Mutation B5: omitting `max_hits` from the request left every test green,
    because the mock ignores params and the tool slices client-side anyway. On
    the real endpoint the server would apply its OWN default — so a caller
    asking for 10 could silently receive the server's default instead, and the
    client-side slice cannot invent hits it was never sent.

    The cap is the caller's, so it has to cross the wire."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    seen = {}

    def _capture(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={
            "filing_id": 1, "query": "revenue", "total_chars": 900,
            "total_hits": 1, "hits": [_hit(1, "revenue")],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_capture)
    await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="revenue", max_hits=9)
    assert seen.get("max_hits") == "9", f"the caller's cap did not reach the endpoint: {seen}"
