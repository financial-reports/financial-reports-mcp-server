"""`filings_search` replayed against REAL prod responses of GET /filings/search/.

The fixtures in tests/fixtures/filings_search/ are the step C smoke recordings
(cross-corpus-search, 2026-11-06 07:08-07:09Z, one allowlisted account). Only
the status, three non-secret headers and the body are kept. The synthetic
fixtures in test_filings_search.py were written from the contract and can only
agree with it; these can disagree, and the first replay did (call 13).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

SEARCH_URL = f"{TEST_API_BASE}/filings/search/"
FIXTURES = Path(__file__).parent / "fixtures" / "filings_search"


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _response(name: str) -> httpx.Response:
    rec = _recorded(name)
    return httpx.Response(rec["status"], json=rec["body"], headers=rec["headers"])


def _tool(mcp_module):
    tool = mcp_module.mcp._tool_manager._tools["filings_search"]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


@pytest.fixture
def authed(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)
    return mcp_module


@pytest.mark.asyncio
async def test_a_capped_early_stopped_first_page(authed, respx_router):
    """Recording 01: a common phrase. count=1000, capped, scan_complete=false,
    10 results with snippets and 15 with match=null."""
    respx_router.get(SEARCH_URL).mock(return_value=_response("01_common_q"))
    out = await _tool(authed)(queries=["going concern"], page_size=25)
    assert "1000 filing(s) matched" in out and "25 shown" in out
    assert "stopped before checking every candidate" in out
    assert "call again with page=2" in out
    assert out.count("matched; snippets not shown") == 15
    assert "literal occurrence(s)" in out
    assert "no visible filing found" not in out.lower()


@pytest.mark.asyncio
async def test_stem_only_matches_are_matches(authed, respx_router):
    """Recording 04b: two results matched only through accent folding, with the
    real {query: null, hits: [], total_hits: 0} block."""
    respx_router.get(SEARCH_URL).mock(return_value=_response("04b_fold_aeromexico"))
    out = await _tool(authed)(queries=["aeromexico"], page_size=25)
    assert out.count("matched, but no exact-phrase snippet") == 2
    assert "did not match" not in out.lower()
    # Word boundary: "10 literal" and "20 literal" are real counts here.
    assert not re.search(r"(?<!\d)0 literal", out)


@pytest.mark.asyncio
async def test_zero_results_with_a_complete_scan_is_a_real_absence(authed, respx_router):
    """Recording 09: count 0, scan_complete true, nothing billed (x-credits-charged 0)."""
    rec = _recorded("09_zero_results")
    assert rec["headers"]["x-credits-charged"] == "0"
    respx_router.get(SEARCH_URL).mock(return_value=_response("09_zero_results"))
    out = await _tool(authed)(queries=["zzqxnotawordzz"], page_size=25)
    assert out.startswith("No filing matched") and "Nothing was billed" in out


@pytest.mark.asyncio
async def test_a_page_past_the_last_does_not_claim_earlier_pages_hold_results(
    authed, respx_router
):
    """Recording 13: page 3 of a search that matched about 0. The tool used to
    add "Earlier pages hold the results", which this recording contradicts."""
    route = respx_router.get(SEARCH_URL).mock(return_value=_response("13_page_past_last_page"))
    # The recording filtered with type=10-K-ESEF; the tool's only type filter
    # is the plural `types`, which the endpoint accepts as an equivalent.
    out = await _tool(authed)(
        queries=["going concern"], company=390, types="10-K-ESEF", page=3, page_size=25,
    )
    params = route.calls.last.request.url.params
    assert params["company"] == "390" and params["types"] == "10-K-ESEF"
    assert "No results on page 3" in out
    assert "matches about 0" in out
    assert "earlier pages hold" not in out.lower()
    assert "not billed" in out
    assert "does not exist" not in out


@pytest.mark.asyncio
async def test_page_past_cap_is_an_error_carrying_the_reason(authed, respx_router):
    """Recording 08: 400 search_page_past_cap with type + resolution."""
    respx_router.get(SEARCH_URL).mock(return_value=_response("08_page_past_cap"))
    with pytest.raises(authed.UpstreamHTTPError) as exc:
        await _tool(authed)(queries=["annual report"], page=41, page_size=25)
    msg = str(exc.value)
    assert "capped at the first 1000" in msg
    assert "Narrow q or the filters" in msg


@pytest.mark.asyncio
async def test_an_endpoint_404_is_not_read_as_a_past_end_page(authed, respx_router):
    """Recording 12: the endpoint's 404 for a caller it does not serve
    ({"detail": "Not found."}, no type). Must stay an error."""
    respx_router.get(SEARCH_URL).mock(return_value=_response("12_unauthenticated"))
    with pytest.raises(authed.UpstreamHTTPError):
        await _tool(authed)(queries=["going concern"], page=3)


@pytest.mark.parametrize("name, queries", [
    ("10b_six_q", ["going concern", "continuité d'exploitation",
                   "Unternehmensfortführung", "continuidad", "continuità aziendale", "x"]),
    ("10c_q_201_chars", ["a" * 201]),
])
@pytest.mark.asyncio
async def test_local_limits_refuse_what_the_api_refuses(authed, respx_router, name, queries):
    """Recordings 10b/10c: the API's invalid_q limits. The tool refuses the same
    inputs locally, so no round trip is made."""
    assert _recorded(name)["body"]["type"] == "invalid_q"
    route = respx_router.get(SEARCH_URL).mock(return_value=_response(name))
    out = await _tool(authed)(queries=queries)
    assert not route.called
    assert "at most" in out


@pytest.mark.parametrize("name", ["10a_no_q", "10b_six_q", "10c_q_201_chars"])
def test_invalid_q_bodies_forward_detail_and_resolution(mcp_module, name):
    """If an invalid_q ever does reach the API (a limit drifting), the model gets
    the API's reason and its remedy, not "check the arguments"."""
    body = json.dumps(_recorded(name)["body"])
    copy = mcp_module._upstream_4xx_copy(body)
    assert "Pass q 1 to 5 times" in copy
