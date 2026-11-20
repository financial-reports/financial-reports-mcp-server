"""`filings_markdown_outline` — a filing's headings with offsets (web#8004).

The tool renders `GET /filings/{id}/markdown/outline/` one line per heading, so
the model can pick a section and read it with `filings_markdown_retrieve` at
that offset instead of paging from 0. What is pinned here:

  - the request: the outline endpoint, `limit` clamped, `max_level` passed on;
  - the lines carry the API's offset, length, level and page unchanged, so an
    offset fed to `filings_markdown_retrieve` is the API's own character offset;
  - truncation and the result ceiling are SAID, never silent;
  - an older API without the route (web deploys first) answers with an HTML
    404, which must not read as "this filing does not exist";
  - every upstream failure (HTTP error, transport error, a 200 that is not an
    outline) reaches the client as `isError` (#104); bad input is a returned
    message, as on the other markdown tools.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

OUTLINE = f"{TEST_API_BASE}/filings/7/markdown/outline/"


@pytest.fixture(autouse=True)
def _authed(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _fn(mcp_module, name="filings_markdown_outline"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _entry(offset, title, *, level=2, page=None, length=100):
    return {"level": level, "title": title, "offset": offset, "page": page, "length": length}


def _payload(entries, *, total_headings=None, truncated=False, max_level=None, total_chars=5000):
    return {
        "filing_id": 7,
        "total_chars": total_chars,
        "scanned_chars": total_chars,
        "total_headings": len(entries) if total_headings is None else total_headings,
        "truncated": truncated,
        "max_level": max_level,
        "entries": entries,
    }


@pytest.mark.asyncio
async def test_it_calls_the_outline_endpoint_and_renders_one_line_per_heading(
    mcp_module, respx_router
) -> None:
    route = respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload([
        _entry(4908, "PART I", level=1, page=3, length=139084),
        _entry(145468, "ITEM 7. MANAGEMENT'S DISCUSSION", level=2, page=31, length=86233),
        _entry(341888, "NOTE 12 SEGMENTS", level=3, length=8835),
    ], total_chars=452225)))
    out = await _fn(mcp_module)(filing_id=7)
    assert route.called
    assert route.calls.last.request.url.params["limit"] == "500"
    assert "max_level" not in route.calls.last.request.url.params
    lines = out.splitlines()
    assert "4908 +139084 L1 p3 PART I" in lines
    assert "145468 +86233 L2 p31 ITEM 7. MANAGEMENT'S DISCUSSION" in lines
    assert "341888 +8835 L3 NOTE 12 SEGMENTS" in lines  # no page: no p-field
    assert "3 of 3 headings" in out and "452225 chars" in out
    assert "filings_markdown_retrieve(filing_id=7, offset=<offset>" in out
    assert "Not every heading" not in out


@pytest.mark.asyncio
async def test_limit_is_clamped_and_max_level_is_passed_on(mcp_module, respx_router) -> None:
    route = respx_router.get(OUTLINE).mock(
        return_value=httpx.Response(200, json=_payload([_entry(0, "A")])))
    await _fn(mcp_module)(filing_id=7, max_level=2, limit=999999)
    params = route.calls.last.request.url.params
    assert (params["max_level"], params["limit"]) == ("2", str(mcp_module._OUTLINE_MAX_LIMIT))
    await _fn(mcp_module)(filing_id=7, limit=0)
    assert route.calls.last.request.url.params["limit"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"filing_id": 0}, {"filing_id": 7, "max_level": 0}, {"filing_id": 7, "max_level": 7},
    {"filing_id": 7, "max_level": "x"}, {"filing_id": 7, "limit": "many"},
    {"filing_id": 7, "max_level": float("inf")}, {"filing_id": 7, "limit": float("inf")},
])
async def test_bad_input_is_refused_before_any_request(mcp_module, respx_router, kwargs) -> None:
    route = respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload([])))
    out = await _fn(mcp_module)(**kwargs)
    assert not route.called
    assert "must be" in out


@pytest.mark.asyncio
async def test_truncation_is_said_with_the_level_shown_in_full(mcp_module, respx_router) -> None:
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload(
        [_entry(0, "Part A", level=1), _entry(50, "Long section", level=2)],
        total_headings=900, truncated=True, max_level=1)))
    out = await _fn(mcp_module)(filing_id=7)
    assert "2 of 900 headings" in out
    assert "Not every heading is listed" in out
    assert "every heading down to level 1 is here" in out


@pytest.mark.asyncio
async def test_an_outline_of_only_the_start_says_where_it_stops(mcp_module, respx_router) -> None:
    body = _payload([_entry(0, "Part A", level=1)], truncated=True, total_chars=90_000_000)
    body["scanned_chars"] = 20_000_000
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=body))
    out = await _fn(mcp_module)(filing_id=7)
    assert "Only the first 20000000 chars were outlined" in out
    assert "filings_markdown_search" in out.splitlines()[0]


@pytest.mark.asyncio
async def test_a_trimmed_outline_of_only_the_start_says_both(mcp_module, respx_router) -> None:
    body = _payload([_entry(0, "Part A", level=1)], total_headings=900, truncated=True,
                    max_level=1, total_chars=90_000_000)
    body["scanned_chars"] = 20_000_000
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=body))
    head = (await _fn(mcp_module)(filing_id=7)).splitlines()[0]
    assert "Only the first 20000000 chars" in head and "Not every heading is listed" in head


@pytest.mark.asyncio
async def test_no_headings_in_the_outlined_start_is_not_no_headings(mcp_module, respx_router) -> None:
    body = _payload([], truncated=True, total_chars=90_000_000)
    body["scanned_chars"] = 20_000_000
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=body))
    out = await _fn(mcp_module)(filing_id=7)
    assert "Only the first 20000000 chars were outlined" in out
    assert out.startswith("No headings in the first 20000000 of 90000000 chars of filing 7")
    assert "marked no sections" not in out


@pytest.mark.asyncio
async def test_a_level_filter_on_a_partial_scan_is_scoped_to_it(mcp_module, respx_router) -> None:
    body = _payload([], total_headings=40, truncated=True, max_level=1, total_chars=90_000_000)
    body["scanned_chars"] = 20_000_000
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=body))
    out = await _fn(mcp_module)(filing_id=7, max_level=1)
    assert out.startswith("No headings at level 1 or above in the first 20000000 of 90000000")
    assert "Only the first 20000000 chars were outlined" in out


@pytest.mark.asyncio
async def test_malformed_entries_are_counted_never_printed(mcp_module, respx_router) -> None:
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload(
        [_entry(10, "Real"), {"title": "no offset"}, "junk", _entry(None, "null offset"),
         {**_entry(5, "bool"), "offset": True}, {**_entry(6, "nolen"), "length": None},
         {**_entry(7, "nolevel"), "level": "2"}, {**_entry(8, "nopage"), "page": None}],
        total_headings=8)))
    out = await _fn(mcp_module)(filing_id=7)
    assert "10 +100 L2 Real" in out
    assert "None" not in out and "no offset" not in out and "bool" not in out
    assert "nolen" not in out and "nolevel" not in out
    assert "8 +100 L2 nopage" in out  # a null page is fine
    assert "6 malformed entries were left out" in out


@pytest.mark.asyncio
async def test_headings_none_of_which_can_be_read_are_an_error(mcp_module, respx_router) -> None:
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload(
        [{**_entry(0, "A"), "offset": "0"}, {"title": "B"}])))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _fn(mcp_module)(filing_id=7)
    assert "cannot read" in str(exc.value)


@pytest.mark.asyncio
async def test_a_level_filter_that_leaves_nothing_is_not_no_headings(
    mcp_module, respx_router, monkeypatch
) -> None:
    counted = []
    monkeypatch.setattr(mcp_module, "record_result_count", counted.append)
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload(
        [], total_headings=12, max_level=1)))
    out = await _fn(mcp_module)(filing_id=7, max_level=1)
    assert out.startswith("No headings at level 1 or above in filing 7 (5000 chars); it has 12")
    assert "marked no sections" not in out
    assert counted == [0]


@pytest.mark.asyncio
async def test_an_outline_without_headings_says_to_search(mcp_module, respx_router) -> None:
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload([])))
    out = await _fn(mcp_module)(filing_id=7)
    assert out.startswith("No headings in filing 7")
    assert "filings_markdown_search(filing_id=7" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("title_chars", [151, 157, 163, 169, 175, 181])
async def test_the_result_stays_inside_the_ceiling_and_counts_what_it_left_out(
    mcp_module, respx_router, monkeypatch, title_chars
) -> None:
    """Several title lengths, so the stop point lands at different distances
    from the ceiling: one fixed length lets a zero notice room pass by luck.
    Analytics records the headings the client received, not those sent."""
    counted = []
    monkeypatch.setattr(mcp_module, "record_result_count", counted.append)
    entries = [_entry(i * 1000, f"{i:04d} " + "x" * title_chars) for i in range(1000)]
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload(entries)))
    out = await _fn(mcp_module)(filing_id=7, limit=1000)
    assert len(out) <= mcp_module._MAX_RESULT_CHARS
    shown = sum(1 for line in out.splitlines() if line[:1].isdigit())
    assert 0 < shown < 1000
    assert f"... and {1000 - shown} more headings, not shown" in out
    assert counted == [shown]


@pytest.mark.asyncio
async def test_an_older_api_without_the_route_is_not_a_missing_filing(
    mcp_module, respx_router
) -> None:
    """Web ships the endpoint first, but an MCP image can meet an API that has
    not got it: Django answers the unknown path with its HTML 404 page."""
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(
        404, text="<!DOCTYPE html><title>Page Not Found | FinancialFilings</title>",
        headers={"content-type": "text/html; charset=utf-8"}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _fn(mcp_module)(filing_id=7)
    assert exc.value.error_kind == "outline_unavailable"
    assert exc.value.upstream_status == 404
    message = str(exc.value)
    assert "not available from the FinancialFilings API yet" in message
    assert "filings_markdown_search(filing_id=7" in message
    assert "does not exist" not in message and "check the id" not in message


@pytest.mark.asyncio
async def test_a_json_404_is_the_endpoints_own_answer(mcp_module, respx_router) -> None:
    """No Markdown yet (a `reason` body) keeps the markdown 404's own hint."""
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(404, json={
        "detail": "Processed content not found for this filing.",
        "processing_status": "QUEUED", "reason": "not_processed", "retryable": True}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _fn(mcp_module)(filing_id=7)
    assert exc.value.error_kind == "markdown_pending"
    assert "still being converted" in str(exc.value)

    respx_router.get(OUTLINE).mock(return_value=httpx.Response(404, json={"detail": "Not found."}))
    with pytest.raises(mcp_module.UpstreamHTTPError) as exc:
        await _fn(mcp_module)(filing_id=7)
    assert exc.value.error_kind != "outline_unavailable"
    assert "does not exist upstream" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(404, text="<html>Page Not Found</html>"),
    httpx.Response(403, json={"detail": "Your current plan does not permit access."}),
    httpx.Response(200, text="<html>a proxy page</html>"),
    httpx.Response(200, json={}),
    httpx.Response(200, json={"entries": []}),
    httpx.Response(200, json={"entries": [], "total_chars": 5000, "scanned_chars": 5000}),
    httpx.Response(200, json={"entries": [], "total_chars": 5000, "total_headings": 0}),
    httpx.Response(200, json={"entries": [], "total_chars": 5000, "scanned_chars": "5000",
                              "total_headings": 0}),
    httpx.ConnectError("refused"),
])
async def test_failures_reach_the_client_as_isError(mcp_module, respx_router, response) -> None:
    """#104 through the real client: a string return would read as success.
    Bad INPUT stays a returned message, as on the other markdown tools."""
    from fastmcp import Client

    if isinstance(response, Exception):
        respx_router.get(OUTLINE).mock(side_effect=response)
    else:
        respx_router.get(OUTLINE).mock(return_value=response)
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool(
            "filings_markdown_outline", {"filing_id": 7}, raise_on_error=False)
    assert result.is_error is True


@pytest.mark.asyncio
async def test_an_outline_offset_is_the_offset_retrieve_sends_upstream(
    mcp_module, respx_router
) -> None:
    """The navigation contract end to end: the number on the outline line goes,
    unchanged, as `offset` to `/markdown/`, whose windows are in the same
    characters (#175)."""
    respx_router.get(OUTLINE).mock(return_value=httpx.Response(200, json=_payload([
        _entry(145468, "ITEM 7. MD&A", length=86233)], total_chars=452225)))
    window = respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(200, text="## ITEM 7. MD&A\n\nbody", headers={
            "X-Total-Chars": "452225", "X-Offset": "145468", "X-Next-Offset": "145490"}))
    out = await _fn(mcp_module)(filing_id=7)
    line = next(line for line in out.splitlines() if line.endswith("ITEM 7. MD&A"))
    offset, length = int(line.split()[0]), int(line.split()[1].lstrip("+"))
    read = await _fn(mcp_module, "filings_markdown_retrieve")(filing_id=7, offset=offset, limit=length)
    assert window.calls.last.request.url.params["offset"] == "145468"
    assert "## ITEM 7. MD&A" in read


def test_the_schema_twin_is_never_generated(mcp_module) -> None:
    """When the snapshot carries the endpoint, the schema loop would emit a
    generic `filings_markdown_outline_retrieve` next to this tool."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_mcp_tools.py"
    spec = importlib.util.spec_from_file_location("_gen_for_outline_test", path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert "filings_markdown_outline_retrieve" in gen._REPLACED_BY_SYNTHETIC
    assert "filings_markdown_outline_retrieve" not in mcp_module.mcp._tool_manager._tools
    assert "filings_markdown_outline" in mcp_module.mcp._tool_manager._tools


@pytest.mark.asyncio
async def test_the_section_prompt_and_the_huge_filing_hint_point_at_the_outline(
    mcp_module, respx_router
) -> None:
    prompt = mcp_module.mcp._prompt_manager._prompts["find_filing_section"]
    fn = getattr(prompt, "fn", None) or getattr(prompt, "function", None)
    messages = await fn(ticker_or_name="SAP", filing_type="annual report", section_keyword="segments")
    text = messages[0].content.text
    assert text.index("filings_markdown_outline") < text.index("filings_markdown_search")

    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(200, text="x" * 1000, headers={
            "X-Total-Chars": "500000", "X-Offset": "0", "X-Next-Offset": "1000"}))
    first = await _fn(mcp_module, "filings_markdown_retrieve")(filing_id=7, limit=1000)
    assert "filings_markdown_outline(filing_id=7)" in first.split("--- MARKDOWN CONTENT")[0]
