"""`filings_search` — cross-corpus full-text search over GET /filings/search/
(financial-reports/web#8004, endpoint in web#9601).

⚠ The response bodies below are SYNTHETIC, built from web#9601's serializer and
docstrings. Replace them with the allowlisted recordings when those arrive; a
fixture written from the contract can only agree with the contract.

What these pin, beyond "it calls the endpoint":
  - the three `match` states, none of which may read as "did not match"
  - `capped` is stated without implying count >= 1000 (count is the VISIBLE
    share; capped counts filings the caller cannot see)
  - an empty first page says what was searched and that nothing was billed
  - a 503 stays an ERROR, never an empty result
  - limits are enforced locally, so an over-limit call never costs a round trip
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

SEARCH_URL = f"{TEST_API_BASE}/filings/search/"


def _tool(mcp_module, name="filings_search"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _filing(fid, match, title="Annual report 2024"):
    return {
        "id": fid, "title": title, "release_datetime": "2025-03-14T08:00:00Z",
        "company": {"id": 900 + fid, "name": f"Company {fid}"},
        "filing_type": {"code": "AR", "name": "Annual Report"},
        "match": match,
    }


def _page(results, *, count=None, capped=False, next_url=None, scan_complete=None):
    search = {"capped": capped, "max_results": 1000, "scope": "filings_with_text"}
    if scan_complete is not None:
        search["scan_complete"] = scan_complete
    return {
        "count": len(results) if count is None else count,
        "next": next_url, "previous": None, "results": results,
        "search": search,
    }


LITERAL = {"query": "going concern", "total_hits": 4,
           "hits": [{"offset": 1200, "snippet": "material uncertainty ... going concern ..."}]}
STEM_ONLY = {"query": None, "hits": [], "total_hits": 0}


@pytest.mark.asyncio
async def test_sends_every_query_as_a_repeated_q_with_filters_and_paging(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)]))
    )
    out = await _tool(mcp_module)(
        queries=["going concern", "continuité d'exploitation"],
        company=42, include_predecessors=True, countries="FR,DE", types="AR",
        release_datetime_from="2024-01-01T00:00:00Z", page=2, page_size=50,
    )
    assert "filing 1" in out
    params = route.calls.last.request.url.params
    assert params.get_list("q") == ["going concern", "continuité d'exploitation"]
    assert params["company"] == "42" and params["include_predecessors"] == "true"
    assert params["countries"] == "FR,DE" and params["types"] == "AR"
    assert params["page"] == "2" and params["page_size"] == "50"
    assert "cursor" not in params, "cursor is a 400 on this endpoint"


@pytest.mark.asyncio
async def test_none_of_the_three_match_states_reads_as_no_match(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """null, the stem-only empty match, and literal hits are all MATCHES."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([
        _filing(1, LITERAL), _filing(2, STEM_ONLY), _filing(3, None),
    ])))
    out = await _tool(mcp_module)(queries=["going concern"])
    assert "3 filing(s) matched" in out
    assert "4 literal occurrence(s)" in out and "@offset 1200" in out
    assert "matched, but no exact-phrase snippet" in out
    assert "matched; snippets not shown" in out
    for wrong in ("no match", "did not match", "0 literal"):
        assert wrong not in out.lower(), f"a match state rendered as {wrong!r}"


@pytest.mark.asyncio
async def test_truncated_filing_is_disclosed(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([
        _filing(1, {**LITERAL, "truncated": True}),
    ])))
    out = await _tool(mcp_module)(queries=["going concern"])
    assert "longer than the 20 MB the index reads" in out


@pytest.mark.asyncio
async def test_a_filing_without_a_release_date_says_so(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([
        {**_filing(1, LITERAL), "release_datetime": None},
    ])))
    out = await _tool(mcp_module)(queries=["going concern"])
    assert "| no release date |" in out


@pytest.mark.asyncio
async def test_capped_says_more_exist_without_claiming_count_is_1000(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """capped=true with count=740 is a real shape: capped counts invisible
    filings. "at least 1000" would be false here."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [_filing(1, LITERAL)], count=740, capped=True, next_url="x?page=2",
    )))
    out = await _tool(mcp_module)(queries=["revenue"])
    assert out.startswith("740 filing(s) matched")
    assert "more matching filings may exist" in out
    assert "at least 1000" not in out
    assert "page=2" in out


@pytest.mark.asyncio
async def test_an_empty_CAPPED_page_is_not_reported_as_an_absence(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """web#9601 5f846a1fe: the scan stops at 10,000 candidates or 2 s. A broad
    query whose top candidates the caller cannot see returns count=0 with
    capped=true. "No filing matched" there would be a false absence."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        200, json=_page([], count=0, capped=True)))
    out = await _tool(mcp_module)(queries=["annual report"])
    assert "NOT an absence" in out and "may still exist" in out
    assert "No filing matched" not in out


@pytest.mark.parametrize("capped, scan_complete, expect, refuse", [
    (True, True, "More than 1000 filings match", "may exist"),
    (True, False, "more matching filings may exist", "More than 1000"),
    (False, False, "more matching filings may exist", "More than 1000"),
    (False, True, None, "may exist"),
])
@pytest.mark.asyncio
async def test_capped_copy_keys_on_scan_complete(
    mcp_module, monkeypatch, fake_access_token, respx_router,
    capped, scan_complete, expect, refuse
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [_filing(1, LITERAL)], count=500, capped=capped, scan_complete=scan_complete)))
    out = await _tool(mcp_module)(queries=["revenue"])
    assert out.startswith("500 filing(s) matched")
    if expect:
        assert expect in out
    assert refuse not in out


@pytest.mark.parametrize("count, scan_complete, expect, refuse", [
    (40, True, "Earlier pages hold the 40 result(s)", "may still exist"),
    (40, False, "may still exist", "No visible results"),
    (0, False, "may still exist", "Earlier pages hold"),
    (0, True, "No visible results were found", "may still exist"),
])
@pytest.mark.asyncio
async def test_an_empty_later_page_keeps_the_early_stop_warning(
    mcp_module, monkeypatch, fake_access_token, respx_router,
    count, scan_complete, expect, refuse
):
    """SPECHT on #191 (3/3): page 2 of an incomplete scan said only "earlier
    pages hold them", which reads as exhausted pagination."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [], count=count, capped=not scan_complete, scan_complete=scan_complete)))
    out = await _tool(mcp_module)(queries=["revenue"], page=3)
    assert expect in out
    assert refuse not in out


@pytest.mark.asyncio
async def test_empty_page_with_a_complete_scan_is_a_real_absence(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        200, json=_page([], count=0, capped=False, scan_complete=True)))
    out = await _tool(mcp_module)(queries=["xyzzy"])
    assert "No filing matched" in out and "NOT an absence" not in out


@pytest.mark.asyncio
async def test_empty_page_with_an_incomplete_scan_is_not_an_absence_even_uncapped(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """scan_complete is the explicit signal; it must win over capped."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        200, json=_page([], count=0, capped=False, scan_complete=False)))
    out = await _tool(mcp_module)(queries=["annual report"])
    assert "NOT an absence" in out


@pytest.mark.asyncio
async def test_empty_first_page_states_scope_and_that_nothing_was_billed(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _tool(mcp_module)(queries=["xyzzy"])
    assert "No filing matched" in out
    assert "first 20 MB" in out and "extracted text" in out
    assert "Nothing was billed" in out


@pytest.mark.asyncio
async def test_unavailable_index_is_an_error_not_an_empty_result(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """503 search_unavailable also fires on a PARTIAL shard answer. Reading it
    as "No filing matched" is the false absence this tool must never produce."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        503, json={"detail": "The full-text index is unavailable."}))
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module)(queries=["going concern"])


@pytest.mark.asyncio
async def test_past_cap_400_is_raised_with_its_reason(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    # web#9601 as merged sends a BARE {"detail": ...}: the error code does not
    # reach the wire until its follow-up adds `type`. So the reason must get
    # through from `detail` alone.
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        400, json={"detail": "Results are capped at the first 1000; narrow q or the filters."}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module)(queries=["revenue"], page=60, page_size=20)
    assert "capped at the first 1000" in str(exc.value)


# Live bodies from web master (users/exceptions.py _coded_hint,
# filings/api_pagination.py _past_the_end, filings/cross_search.py SearchBusy);
# prod recording 13 confirmed the 404 for a page past the last one.
PAST_END = {
    "detail": "Invalid page. Page 3 is past the end of the results: this request matches about 25.",
    "type": "page_out_of_range",
    "resolution": "The results ended before this page. Follow `next` until it is null "
                  "instead of computing the last page from `count`, which can be an estimate.",
}
BUSY = {
    "detail": "Too many full-text searches are running right now. Retry in a few seconds.",
    "type": "search_busy",
    "resolution": "Too many searches are running right now. Retry after the Retry-After "
                  "seconds, and run at most a couple of searches at a time per account.",
}


@pytest.mark.asyncio
async def test_a_page_past_the_last_is_a_result_not_a_missing_resource(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The live endpoint answers a page past the last with 404 page_out_of_range.
    Through the shared path that read "the requested resource does not exist —
    check the id", which tells the model its SEARCH was wrong."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(404, json=PAST_END))
    out = await _tool(mcp_module)(queries=["going concern"], page=3, page_size=20)
    assert "No results on page 3" in out
    assert "matches about 25" in out
    assert "not billed" in out
    assert "does not exist" not in out
    # The 404 does not say whether the scan was complete, so an early-stopped
    # search must not read as exhausted (SPECHT S2 at b515ab6).
    assert "does not show that every candidate was searched" in out


@pytest.mark.asyncio
async def test_any_other_404_stays_an_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A 404 that is not page_out_of_range (the endpoint gone, a flag closed)
    must not be read as "past the last page"."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(404, json={"detail": "Not found."}))
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _tool(mcp_module)(queries=["going concern"], page=3)


@pytest.mark.asyncio
async def test_search_busy_is_retried_once_then_says_busy_not_rate_limited(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """429 search_busy (in-flight cap, Retry-After 2, unbilled) is not an account
    limit: it is retried once, and if still busy the model is told to retry,
    not that the account is rate limited."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        429, json=BUSY, headers={"Retry-After": "2"}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module)(queries=["going concern"])
    assert route.call_count == 2, "Retry-After 2 is within the retry cap"
    msg = str(exc.value)
    assert "busy" in msg and "not an account limit" in msg
    assert "Retry after 2s" in msg
    assert "Rate limited" not in msg
    assert exc.value.error_kind == "search_busy"


@pytest.mark.asyncio
async def test_search_busy_then_free_returns_results(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(side_effect=[
        httpx.Response(429, json=BUSY, headers={"Retry-After": "2"}),
        httpx.Response(200, json=_page([_filing(1, LITERAL)])),
    ])
    out = await _tool(mcp_module)(queries=["going concern"])
    assert "filing 1" in out


@pytest.mark.parametrize("queries, fragment", [
    ([], "at least one"),
    (["  "], "at least one"),
    (["a", "b", "c", "d", "e", "f"], "at most 5 queries"),
])
@pytest.mark.asyncio
async def test_query_limits_are_enforced_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router, queries, fragment
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    calls = {"n": 0}
    respx_router.get(SEARCH_URL).mock(side_effect=lambda r: (calls.__setitem__("n", calls["n"] + 1),
                                                             httpx.Response(200, json=_page([])))[1])
    out = await _tool(mcp_module)(queries=queries)
    assert calls["n"] == 0, "an invalid call was sent to the API"
    assert fragment in out


@pytest.mark.asyncio
async def test_an_over_long_query_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _tool(mcp_module)(queries=["a" * (mcp_module._MAX_QUERY_CHARS + 1)])
    assert route.call_count == 0
    assert "200 characters" in out and "201" in out


@pytest.mark.asyncio
async def test_exactly_five_queries_and_200_chars_are_sent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    qs = ["a" * mcp_module._MAX_QUERY_CHARS, "b", "c", "d", "e"]
    await _tool(mcp_module)(queries=qs)
    assert route.calls.last.request.url.params.get_list("q") == qs


@pytest.mark.asyncio
async def test_a_bare_string_is_one_query_and_duplicates_do_not_use_slots(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _tool(mcp_module)(queries="going concern")
    assert route.calls.last.request.url.params.get_list("q") == ["going concern"]
    await _tool(mcp_module)(queries=["x", "x ", "y", "y", "z", "z"])
    assert route.calls.last.request.url.params.get_list("q") == ["x", "y", "z"]


def test_tool_is_on_the_default_surface_and_read_only(mcp_module) -> None:
    tool = mcp_module.mcp._tool_manager._tools.get("filings_search")
    assert tool is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    desc = tool.description or ""
    for claim in ("translations", "first 20 MB", "nothing", "Every page is billed"):
        assert claim in desc, f"description lost: {claim!r}"
