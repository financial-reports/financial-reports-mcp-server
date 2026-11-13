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


# --- forgiving input through REAL dispatch (web#8004 routing PR) ---------------
#
# The bare-string test above calls the function directly, which skips FastMCP's
# argument validation. Through the wire, `queries: list[str]` refused a bare
# string, and an unknown `query` argument was refused too: one real call failed
# that way. These go through the in-memory Client, so they test what a client
# actually gets.

async def _call(mcp_module, args):
    from fastmcp import Client

    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool("filings_search", args)
    return result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "expected_q"),
    [
        ({"query": "going concern"}, ["going concern"]),
        ({"queries": "going concern"}, ["going concern"]),
        ({"queries": ["going concern"], "query": "Unternehmensfortführung"},
         ["going concern", "Unternehmensfortführung"]),
        ({"queries": ["going concern"], "query": "going concern"}, ["going concern"]),
        # A list sent JSON-encoded is that list, not one literal query.
        ({"queries": '["going concern", "継続企業の前提"]'}, ["going concern", "継続企業の前提"]),
        ({"queries": "[unclosed"}, ["[unclosed"]),
        # Valid JSON, but no query in it: a footnote-style search string.
        ({"queries": "[2023]"}, ["[2023]"]),
    ],
)
async def test_query_and_a_bare_string_are_accepted_through_real_dispatch(
    mcp_module, monkeypatch, fake_access_token, respx_router, args, expected_q
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    out = await _call(mcp_module, args)
    assert "filing 1" in out
    assert route.calls.last.request.url.params.get_list("q") == expected_q


@pytest.mark.asyncio
async def test_no_query_at_all_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _call(mcp_module, {"countries": "FR"})
    assert "at least one non-empty string" in out
    assert not route.called


@pytest.mark.asyncio
async def test_query_and_queries_together_still_respect_the_five_limit(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _call(mcp_module, {"queries": ["a", "b", "c", "d", "e"], "query": "f"})
    assert "at most 5 queries" in out
    assert not route.called


@pytest.mark.asyncio
async def test_added_to_platform_bounds_and_ordering_are_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _tool(mcp_module)(
        queries=["going concern"],
        added_to_platform_from="2026-11-09T00:00:00Z",
        added_to_platform_to="2026-11-10T00:00:00Z",
        ordering=" -added_to_platform , relevance ",
    )
    params = route.calls.last.request.url.params
    assert params["added_to_platform_from"] == "2026-11-09T00:00:00Z"
    assert params["added_to_platform_to"] == "2026-11-10T00:00:00Z"
    assert params["ordering"] == "-added_to_platform,relevance"


@pytest.mark.asyncio
async def test_unset_ordering_is_not_sent(mcp_module, monkeypatch, fake_access_token, respx_router):
    """Relevance is the endpoint's default; sending nothing keeps the rerank on."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _tool(mcp_module)(queries=["going concern"], ordering="  ")
    assert "ordering" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["-added_to_plaform", "title", "relevance,-date", "--id"])
async def test_an_unknown_ordering_field_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router, bad
):
    """The endpoint DROPS an unknown field and answers in relevance order, which
    reads as ordered when it is not."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _tool(mcp_module)(queries=["x"], ordering=bad)
    assert "unknown ordering field" in out and "added_to_platform" in out
    assert not route.called


def test_punctuation_only_ordering_is_unset(mcp_module) -> None:
    # "," names no field; sent as "" the endpoint ranks by relevance while the
    # header would claim "ordered by  among ..." (SPECHT on #200).
    assert mcp_module._cross_search_ordering(",") is None
    assert mcp_module._cross_search_ordering(" , ,") is None
    assert mcp_module._cross_search_ordering("-id,") == "-id"


@pytest.mark.parametrize("field", sorted(
    ["relevance", "release_datetime", "added_to_platform", "id", "filing_type_confidence"]
))
def test_every_endpoint_ordering_field_is_accepted_both_ways(mcp_module, field) -> None:
    """Enumerate the domain: each field the endpoint orders by, ascending and
    descending, passes the local check unchanged."""
    assert mcp_module._cross_search_ordering(field) == field
    assert mcp_module._cross_search_ordering(f"-{field}") == f"-{field}"


# --- returned ids reach usage analytics (REPORT rank 2) -------------------------

def _filing_in(fid, country, match=LITERAL):
    row = _filing(fid, match)
    row["company"]["country_code"] = country
    return row


@pytest.mark.asyncio
async def test_a_search_records_its_ranked_filing_ids_and_countries(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """filings_search returns a str, so the middleware cannot read ids off the
    payload: all 94 search events through 2026-11-09 logged returned_ids=[].
    Through the real middleware, the event must carry the filing ids in the
    order shown, and the markets they came from."""
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [_filing_in(31, "jp"), _filing_in(7, "KR"), _filing_in(12, "JP"), _filing_in(5, None)]
    )))
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        await client.call_tool("filings_search", {"queries": ["going concern", "継続企業の前提"]})

    events = [e for e in captured if e["name"] == "filings_search" and e["kind"] == "tool"]
    assert events, "no analytics event captured for the search call"
    ev = events[-1]
    assert ev["status"] == "ok"
    assert ev["returned_ids"] == [31, 7, 12, 5], "ids must be the filing ids, in rank order"
    assert ev["result_countries"] == ["JP", "KR"]
    assert ev["result_count"] == 4


@pytest.mark.asyncio
async def test_results_cut_for_length_are_not_recorded_as_shown(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    big = dict(LITERAL, hits=[{"offset": 1, "snippet": "x" * 3000}])
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [_filing_in(1, "FR"), _filing_in(2, "DE", match=big), _filing_in(3, "IT")]
    )))
    monkeypatch.setattr(mcp_module, "_MAX_RESULT_CHARS", 1500)
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        out = (await client.call_tool("filings_search", {"queries": ["x"]})).content[0].text

    assert "1 result(s) on this page are not shown" in out
    ev = [e for e in captured if e["name"] == "filings_search"][-1]
    assert ev["returned_ids"] == [1, 3]
    assert ev["result_countries"] == ["FR", "IT"]


@pytest.mark.asyncio
async def test_countries_come_only_from_the_recorded_ids(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    # ids are capped at 50; a market seen only in result 51 must not be
    # attributed to the recorded ids (SPECHT on #200).
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    rows = [_filing_in(i, "US") for i in range(1, 51)] + [_filing_in(51, "JP")]
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(rows)))
    monkeypatch.setattr(mcp_module, "_MAX_RESULT_CHARS", 10_000_000)
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        await client.call_tool("filings_search", {"queries": ["x"]})

    ev = [e for e in captured if e["name"] == "filings_search"][-1]
    assert ev["returned_ids"] == list(range(1, 51))
    assert ev["result_countries"] == ["US"]


@pytest.mark.asyncio
async def test_an_empty_search_records_no_ids_and_does_not_leak_into_the_next_call(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(side_effect=[
        httpx.Response(200, json=_page([_filing_in(9, "US")])),
        httpx.Response(200, json=_page([], scan_complete=True)),
    ])
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        await client.call_tool("filings_search", {"queries": ["a"]})
        await client.call_tool("filings_search", {"queries": ["b"]})

    first, second = [e for e in captured if e["name"] == "filings_search"][-2:]
    assert first["returned_ids"] == [9]
    assert second["returned_ids"] == [] and second["result_countries"] == []
    assert second["result_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ordering", "expected"),
    [
        (None, "ranked by relevance;"),
        ("-relevance", "ranked by relevance;"),
        ("relevance,-release_datetime", "ranked by relevance;"),
        ("-added_to_platform", "ordered by -added_to_platform among the first 1000 matches by relevance;"),
        ("-release_datetime,relevance", "ordered by -release_datetime,relevance among the first 1000"),
    ],
)
async def test_the_header_names_the_ordering_the_page_used(
    mcp_module, monkeypatch, fake_access_token, respx_router, ordering, expected
):
    """A date-ordered page headed "ranked by relevance" reads as a ranking."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    out = await _tool(mcp_module)(queries=["going concern"], ordering=ordering)
    assert expected in out.splitlines()[0]


@pytest.mark.asyncio
async def test_a_non_string_query_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Direct-call path; through the wire pydantic refuses it first."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _tool(mcp_module)(queries=["a"], query=7)
    assert "query must be a string" in out
    assert not route.called


# --- max_results, group_by=company and companies (web#10008, web#10016) --------
#
# Bodies built from web master 082cfe9c6 (filings/cross_search.py,
# filings/cross_search_group.py): a grouped page's `search` carries group_by,
# filings_grouped and message on top of the filing envelope, and its rows are
# ROW_FIELDS. All through real Client dispatch, so FastMCP's own argument
# validation runs first, as it does for a client.

GROUPED_MSG = (
    "Grouped over the first 1000 matching filings you can see, by relevance (at most "
    "max_results=1000): hit_count, first_release_datetime and last_release_datetime count "
    "only those filings. More filings may match (search.capped is true), so a company's "
    "counts can be higher and more companies may exist: raise max_results or narrow q or "
    "the filters."
)


def _company_row(cid, country="DE", hits=3, best=None, isin="DE0007164600"):
    return {
        "company_id": cid, "company_name": f"Company {cid}", "country_code": country,
        "isin": isin, "hit_count": hits,
        "first_release_datetime": "2021-03-01T08:00:00Z",
        "last_release_datetime": "2025-02-10T08:00:00Z",
        "best_filing_id": 5000 + cid if best is None else best,
    }


def _grouped(rows, *, grouped=40, capped=False, scan_complete=True, cap=1000,
             message="Grouped over ... That is every matching filing you can see.", next_url=None):
    search = {"capped": capped, "scan_complete": scan_complete, "max_results": cap,
              "scope": "filings_with_text", "types_resolved": [], "group_by": "company",
              "filings_grouped": grouped}
    if message is not None:
        search["message"] = message
    return {"count": len(rows), "next": next_url, "previous": None, "results": rows,
            "search": search}


def _capture(mcp_module, monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))
    return captured


def _last_event(captured):
    return [e for e in captured if e["name"] == "filings_search" and e["kind"] == "tool"][-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "wire"), [(5000, "5000"), (1, "1"), (10000, "10000"), ("250", "250")])
async def test_max_results_is_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router, sent, wire
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _call(mcp_module, {"queries": ["going concern"], "max_results": sent})
    assert route.calls.last.request.url.params["max_results"] == wire


@pytest.mark.asyncio
async def test_unset_max_results_group_by_and_companies_are_not_sent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Unset keeps the endpoint's defaults (cap 1000, filing rows, no basket)."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _call(mcp_module, {"queries": ["x"], "group_by": " ", "companies": ""})
    params = route.calls.last.request.url.params
    for name in ("max_results", "group_by", "companies"):
        assert name not in params


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 10001, -5, "0", "1e3", "10001"])
async def test_max_results_out_of_range_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router, bad
):
    """The endpoint answers these with a 400; refusing here names the range
    and costs no round trip."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    async with Client(mcp_module.mcp) as client:
        try:
            result = await client.call_tool("filings_search", {"queries": ["x"], "max_results": bad})
            out = result.content[0].text
        except ToolError as exc:  # FastMCP's own type check ("1e3" is not an int)
            out = str(exc)
    assert "max_results" in out
    assert not route.called


def test_max_results_bool_is_refused(mcp_module) -> None:
    # True is an int to Python; the endpoint would read "true" as a 400.
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._cross_search_max_results(True)
    assert mcp_module._cross_search_max_results(" 42 ") == 42
    assert mcp_module._cross_search_max_results(None) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("cap", "raise_hint"), [(5000, True), (10000, False)])
async def test_the_header_reads_the_cap_the_endpoint_served(
    mcp_module, monkeypatch, fake_access_token, respx_router, cap, raise_hint
):
    """The header quotes `search.max_results`, and only offers a raise below
    the ceiling (raising past 10000 is a 400)."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _page([_filing(1, LITERAL)], count=cap, capped=True, scan_complete=True)
    body["search"]["max_results"] = cap
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["x"], "max_results": cap,
                                   "ordering": "-release_datetime"})
    assert f"More than {cap} filings match; only the first {cap}" in out
    assert f"among the first {cap} matches by relevance" in out.splitlines()[0]
    assert ("raise max_results (up to 10000 on Enterprise and pay-as-you-go plans)" in out) is raise_hint


@pytest.mark.asyncio
async def test_the_header_quotes_the_served_cap_not_the_sent_one(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """An endpoint that did not apply max_results served the default; quoting
    the sent value would overstate what was searched."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        200, json=_page([_filing(1, LITERAL)], count=1000, capped=True, scan_complete=True)))
    out = await _call(mcp_module, {"queries": ["x"], "max_results": 5000})
    assert "More than 1000 filings match; only the first 1000" in out
    assert "5000" not in out


@pytest.mark.asyncio
async def test_group_by_company_is_forwarded_and_rendered_as_company_rows(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped(
        [_company_row(7, "DE", hits=12, best=901), _company_row(3, "JP", hits=1, isin=None)],
        grouped=13, message="Grouped over the first 13 matching filings you can see.",
    )))
    out = await _call(mcp_module, {"queries": ["going concern"], "group_by": " Company "})
    assert route.calls.last.request.url.params["group_by"] == "company"
    lines = out.splitlines()
    assert lines[0].startswith("2 company(ies) with filings matching")
    assert "best match first" in lines[0]
    assert "counted over the first 13 matching filing(s)" in out
    assert "Search note: Grouped over the first 13 matching filings you can see." in out
    row7 = next(line for line in lines if line.startswith("- company 7 "))
    for part in ("Company 7", "| DE |", "ISIN DE0007164600", "12 matching filing(s)",
                 "first 2021-03-01, last 2025-02-10", "best match: filing 901"):
        assert part in row7, part
    row3 = next(line for line in lines if line.startswith("- company 3 "))
    assert "ISIN none" in row3 and "| JP |" in row3
    assert "count can be higher" not in out, "an uncapped, complete group is every match"
    assert "not over every match" not in out
    assert "counted over the first 13 matching filing(s) you can see: every match" in out
    assert "filing 901 |" not in out, "rows rendered as filings"


@pytest.mark.asyncio
async def test_a_capped_group_says_counts_may_be_higher(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped(
        [_company_row(7)], grouped=1000, capped=True, scan_complete=True, message=GROUPED_MSG)))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    assert "counted over the first 1000 matching filing(s)" in out
    assert "(max_results=1000), not over every match" in out
    assert "More than 1000 filings match, so a company's count can be higher" in out
    assert "raise max_results (up to 10000 on Enterprise and pay-as-you-go plans)" in out
    assert "Search note: Grouped over the first 1000" in out


@pytest.mark.asyncio
async def test_an_early_stopped_group_says_more_may_exist(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped(
        [_company_row(7)], grouped=40, capped=True, scan_complete=False, message=None)))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    assert "stopped before checking every candidate" in out
    assert "not over every match" in out
    assert "a company's count can be higher and more companies may exist" in out
    assert "Search note" not in out


@pytest.mark.asyncio
async def test_a_group_without_filings_grouped_falls_back_to_the_cap(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _grouped([_company_row(7)], cap=500)
    del body["search"]["filings_grouped"]
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company", "max_results": 500})
    assert "counted over at most the first 500 matching filings" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["filing", "country", "company,filing"])
async def test_an_unknown_group_by_is_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router, bad
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": bad})
    assert 'group_by takes one value: "company"' in out
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(("ordering", "refused"), [
    ("-release_datetime", True),
    ("relevance,-added_to_platform", True),
    ("id", True),
    ("relevance", False),
    ("-relevance", False),
])
async def test_group_by_takes_no_ordering_but_relevance(
    mcp_module, monkeypatch, fake_access_token, respx_router, ordering, refused
):
    """The endpoint answers any other ordering with 400 invalid_group_by."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_grouped([_company_row(7)])))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company", "ordering": ordering})
    assert ("ordering is not available with group_by" in out) is refused
    assert route.called is (not refused)


@pytest.mark.asyncio
async def test_group_by_ignored_by_the_endpoint_renders_filings_and_says_so(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """An endpoint that does not know group_by answers with filings. Read as
    company rows they would print as '?' and log filing ids as companies."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page(
        [_filing_in(31, "JP")])))
    captured = _capture(mcp_module, monkeypatch)
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    assert "1 filing(s) matched" in out and "- filing 31 |" in out
    assert 'group_by="company" was not applied by the endpoint' in out
    assert _last_event(captured)["returned_ids"] == [31]


@pytest.mark.asyncio
async def test_a_group_records_the_company_ids_shown_and_their_markets(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """In company mode the rows ARE companies: the event's ids are company ids,
    in the order shown, never the rows' best_filing_id."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped([
        _company_row(7, "de", best=901), _company_row(3, "JP", best=902),
        _company_row(11, None, best=903),
    ])))
    captured = _capture(mcp_module, monkeypatch)
    await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    ev = _last_event(captured)
    assert ev["status"] == "ok"
    assert ev["returned_ids"] == [7, 3, 11]
    assert ev["result_countries"] == ["DE", "JP"]
    assert ev["result_count"] == 3
    # The key survives sanitising, so a grouped call is visible; its VALUE is
    # <redacted> until both analytics allowlists add group_by (follow-up).
    assert "group_by" in ev["arguments"]


@pytest.mark.asyncio
async def test_a_group_does_not_record_rows_cut_for_length_or_past_the_cap(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    rows = [_company_row(i, "US") for i in range(1, 51)] + [_company_row(51, "JP")]
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped(rows)))
    captured = _capture(mcp_module, monkeypatch)
    await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    ev = _last_event(captured)
    assert ev["returned_ids"] == list(range(1, 51))
    assert ev["result_countries"] == ["US"]

    long_row = _company_row(2, "DE")
    long_row["company_name"] = "N" * 3000
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_grouped(
        [_company_row(1, "FR"), long_row, _company_row(3, "IT")])))
    monkeypatch.setattr(mcp_module, "_MAX_RESULT_CHARS", 1800)
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company"})
    assert "1 result(s) on this page are not shown" in out
    ev = _last_event(captured)
    assert ev["returned_ids"] == [1, 3]
    assert ev["result_countries"] == ["FR", "IT"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "wire"), [
    ([12, 345], "12,345"),
    (" 12, 345 ,12,", "12,345"),
    ("[12, 345]", "12,345"),
    (["12", "345"], "12,345"),
    ("7", "7"),
])
async def test_companies_is_forwarded_comma_separated(
    mcp_module, monkeypatch, fake_access_token, respx_router, sent, wire
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _call(mcp_module, {"queries": ["x"], "companies": sent})
    assert route.calls.last.request.url.params["companies"] == wire


@pytest.mark.asyncio
@pytest.mark.parametrize(("bad", "expected"), [
    ("12,abc", "not 'abc'"),
    ("12,-3", "not '-3'"),
    ("0", "not '0'"),
    ("12;34", "not '12;34'"),
    ("[1, 2", "not '[1'"),
    (",".join(str(i) for i in range(1, 52)), "at most 50 company ids (got 51)"),
])
async def test_bad_companies_are_refused_locally(
    mcp_module, monkeypatch, fake_access_token, respx_router, bad, expected
):
    """A token that is not an id is refused, never dropped: dropping it would
    widen the search past the basket the caller asked for."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=_page([])))
    out = await _call(mcp_module, {"queries": ["x"], "companies": bad})
    assert "companies takes" in out and expected in out
    assert not route.called


def test_fifty_companies_pass_and_duplicates_do_not_count(mcp_module) -> None:
    ids = list(range(1, 51))
    assert mcp_module._cross_search_companies(ids + ids) == ids
    assert mcp_module._cross_search_companies([]) is None
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._cross_search_companies([True])
    with pytest.raises(mcp_module.ToolInputError):
        mcp_module._cross_search_companies("[1.5]")
    # Direct calls only (the wire schema takes a list or a string).
    assert mcp_module._cross_search_companies(7) == [7]


@pytest.mark.asyncio
async def test_include_predecessors_works_with_companies_alone(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_page([_filing(1, LITERAL)])))
    await _call(mcp_module, {"queries": ["x"], "companies": [12, 34], "include_predecessors": True})
    params = route.calls.last.request.url.params
    assert params["companies"] == "12,34" and params["include_predecessors"] == "true"

    route.reset()
    out = await _call(mcp_module, {"queries": ["x"], "include_predecessors": True})
    assert "include_predecessors needs company or companies" in out
    assert not route.called


def test_the_description_teaches_max_results_and_the_basket_mode(mcp_module) -> None:
    desc = mcp_module.mcp._tool_manager._tools["filings_search"].description or ""
    flat = " ".join(desc.split())
    assert "`max_results` (default 1000)" in flat
    assert "Enterprise and pay-as-you-go plans may raise it to 10000; other plans may only lower it" in flat
    assert "a regulator form name such as 10-Q, 8-K, 20-F or S-1 is accepted too" in flat
    assert 'Raise it for broad screens and "how many companies / filings" questions' in flat
    assert "costs nothing extra per page" in flat and "slower" in flat
    assert 'WHICH COMPANIES MENTION X: group_by="company"' in flat
    assert "then filings_search with company=<id> (or companies=<ids>)" in flat
    assert "companies (up to 50 internal ids" in flat
    assert "first 1000 matches by relevance" not in flat, "the cap is max_results now"


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "page", "expected", "absent"), [
    (_grouped([], grouped=0, message="No matching filing you can see was found."), 1,
     "No filing matched", "may still exist"),
    (_grouped([], grouped=0, capped=True, scan_complete=False, message=None), 1,
     "this is NOT an absence", "No filing matched"),
    (_grouped([], grouped=40, capped=True, scan_complete=False, message=None), 3,
     "matching filings may still exist", "No filing matched"),
])
async def test_an_empty_group_page_reads_as_the_filing_search_does(
    mcp_module, monkeypatch, fake_access_token, respx_router, body, page, expected, absent
):
    """The empty paths do not depend on the row shape: an empty grouped page is
    an absence only when the scan was complete, as for filings."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["x"], "group_by": "company", "page": page})
    assert expected in out and absent not in out


@pytest.mark.asyncio
async def test_a_mapped_form_type_is_reported(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """types=8-K is searched as ER and RNS (web#10008); the note reaches the agent so it
    does not present every earnings release as an 8-K."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _page([_filing(1, LITERAL)])
    note = ("8-K is not a FinancialFilings type code; searched as ER, RNS. ER, RNS also hold "
            "filings that are not 8-K, so this may match more than you asked for.")
    body["search"]["types_resolved"] = [
        {"param": "types", "requested": "8-K", "types": ["ER", "RNS"], "widens": True,
         "may_miss": True, "note": note},
        {"param": "types", "requested": "10-Q", "types": ["IR"], "widens": True, "may_miss": False,
         "note": " "},  # a blank note adds no line
        "not a dict",
    ]
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["going concern"], "types": "8-K,10-Q"})
    assert route.calls.last.request.url.params["types"] == "8-K,10-Q"
    assert ("Type note: " + note) in out
    assert out.count("Type note:") == 1


@pytest.mark.asyncio
async def test_no_type_note_when_nothing_was_mapped(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _page([_filing(1, LITERAL)])
    body["search"]["types_resolved"] = []
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["going concern"], "types": "AR"})
    assert "Type note" not in out


def test_the_generated_search_operation_is_never_a_second_tool(mcp_module) -> None:
    """The endpoint is in the schema while it is open; its generated tool would sit next
    to the hand-built filings_search on every surface (pruned or full)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_mcp_tools.py"
    spec = importlib.util.spec_from_file_location("gen_for_test", path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert "filings_search_list" in gen._REPLACED_BY_SYNTHETIC
    source = path.read_text()
    assert "            if func_name in _REPLACED_BY_SYNTHETIC:\n                continue" in source
    assert "filings_search_list" not in mcp_module.mcp._tool_manager._tools


@pytest.mark.asyncio
@pytest.mark.parametrize(("page", "scan_complete", "lead"), [
    (1, True, "No filing matched"),
    (1, False, "No visible filing found"),
    (2, True, "No results on page 2"),
])
async def test_an_empty_page_keeps_the_type_note(
    mcp_module, monkeypatch, fake_access_token, respx_router, page, scan_complete, lead
):
    """An empty 8-K search must still say the mapping may miss some 8-K filings, or it
    reads as an absence (SPECHT on #204, 3/3)."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _page([], count=0, scan_complete=scan_complete, capped=not scan_complete)
    note = "Some 8-K filings are classified under a more specific type, which is not included."
    body["search"]["types_resolved"] = [{"param": "types", "requested": "8-K", "types": ["ER", "RNS"],
                                         "widens": True, "may_miss": True, "note": note}]
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["going concern"], "types": "8-K", "page": page})
    assert out.startswith(lead)
    assert out.endswith("Type note: " + note)


@pytest.mark.asyncio
async def test_a_too_slow_search_is_not_retried_and_says_to_narrow(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """web#10234: a search too heavy to answer in time is a 503 search_too_slow. Retrying the
    same search fails the same way at the node's expense, and the model must narrow instead."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(503, json={
        "detail": "This search took too long to run. Narrow q or the filters.", "type": "search_too_slow"}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module)(queries=["going concern"], countries="JP")
    assert route.call_count == 1  # not retried
    assert "too heavy to answer in time" in str(exc.value)
    assert "Narrow the queries" in str(exc.value)
    assert exc.value.error_kind == "search_too_slow"


@pytest.mark.asyncio
async def test_another_503_is_still_retried_once(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(
        503, json={"detail": "The full-text index is unavailable.", "type": "search_unavailable"}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _tool(mcp_module)(queries=["going concern"])
    assert route.call_count == 2
    assert exc.value.error_kind == "transient"


@pytest.mark.asyncio
async def test_the_endpoints_search_notes_reach_the_model(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = _page([_filing(1, LITERAL)])
    body["search"]["max_results_note"] = (
        "Asked for 2000 results; your plan allows up to 1000, so 1000 were searched.")
    body["search"]["relaxed_note"] = (
        'No filing contained every word of "a b c d e f", so these results contain at least '
        "70% of its words.")
    respx_router.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body))
    out = await _call(mcp_module, {"queries": ["a b c d e f"]})
    assert "Search note: Asked for 2000 results; your plan allows up to 1000" in out
    assert "Search note: No filing contained every word" in out
