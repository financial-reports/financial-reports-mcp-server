"""Near matches on a miss, rendered by both markdown search tools (web#8004).

When nothing matches, the API (web ``markdown_window.near_matches``) returns up
to 3 APPROXIMATE passages holding most of the query's words: the single search
as ``near_matches`` beside ``total_hits: 0``, the batch on each ``no_match`` row.
What these tests pin:

- they are rendered, labelled APPROXIMATE, with the words each one has and
  lacks, and never counted as matches (the miss stays a miss in analytics);
- an API that predates the field (absent) or found nothing close (``[]``) gives
  exactly the output the tools gave before;
- in the batch they are the lowest-priority text: the outcome blocks and the
  hit detail are never dropped for them;
- and the single tool reads a hit's text from ``snippet``, the field the API
  sends. It read ``context`` (never sent), so every hit rendered blank.
"""
from __future__ import annotations

import json

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _tool(mcp_module, name):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _near(offset, snippet, has, lacks=()):
    return {"offset": offset, "snippet": snippet, "match": "approximate",
            "matched_words": list(has), "missing_words": list(lacks)}


NEAR = [
    _near(1200, "Supplemental cash flow information: Interest paid 412", ["cash", "paid", "interest"]),
    _near(5300, "Dividends were paid in cash", ["cash", "paid"], ["interest"]),
    _near(9100, "cash interest payments on our debt", ["cash", "interest"], ["paid"]),
]


def _mock_single(respx_router, fid=1, *, hits=(), near=None, omit_near=False, total_chars=50_000):
    body = {"filing_id": fid, "query": "q", "total_chars": total_chars,
            "total_hits": len(hits), "hits": list(hits)}
    if not omit_near and not hits:
        body["near_matches"] = NEAR if near is None else near
    return respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/search/").mock(
        return_value=httpx.Response(200, text=json.dumps(body)))


def _row(fid, query, status, *, hits=(), near=None):
    row = {"filing_id": fid, "query": query, "status": status}
    if status in ("hit", "no_match"):
        row["hits"] = [{"offset": o, "snippet": s} for o, s in hits]
        row["total_hits"] = len(hits)
    if status == "unavailable":
        row["reason"] = "not_processed"
    if status == "skipped":
        row["reason"] = "deadline"
    if near is not None:
        row["near_matches"] = near
    return row


def _mock_batch(respx_router, rows):
    body = {"results": rows, "pairs": len(rows), "searched": 0, "hit": 0, "no_match": 0,
            "unavailable": 0, "skipped": 0, "truncated": False, "billed_credits": 0}
    return respx_router.post(f"{TEST_API_BASE}/filings/markdown/search/").mock(
        return_value=httpx.Response(200, text=json.dumps(body)))


# --- single tool: the hit text ---------------------------------------------------

@pytest.mark.asyncio
async def test_single_hit_text_is_read_from_snippet(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The control row proves the accessor: a hit carrying only `context` (a key
    the API never sends) renders blank, so this fails if `context` comes back."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_single(respx_router, hits=[{"offset": 5, "snippet": "SNIPPET-FIELD"},
                                     {"offset": 90, "context": "CONTEXT-FIELD"}])
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="revenue")
    assert "SNIPPET-FIELD" in out
    assert "CONTEXT-FIELD" not in out
    assert "approximate" not in out.lower(), "a hit response carries no near-match text"


# --- single tool: near matches -----------------------------------------------------

@pytest.mark.asyncio
async def test_single_miss_renders_near_matches_labelled_approximate(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_single(respx_router)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="Cash paid for interest")
    assert out.startswith("No match for 'Cash paid for interest' in filing 1 (50000 chars searched, all of it).")
    assert "APPROXIMATE, NOT matches" in out
    assert "--- approximate, near offset 1200 (has: cash, paid, interest) ---" in out
    assert "--- approximate, near offset 5300 (has: cash, paid; missing: interest) ---" in out
    assert "Interest paid 412" in out and "cash interest payments" in out
    assert "match(es)" not in out, "a near match must never be presented as a match"
    assert "Try a shorter" not in out


@pytest.mark.asyncio
async def test_single_near_matches_respect_max_hits(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_single(respx_router)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="x y", max_hits=2)
    assert "near offset 1200" in out and "near offset 5300" in out
    assert "near offset 9100" not in out


@pytest.mark.parametrize("variant", ["absent", "empty", "not_a_list", "junk_items"])
@pytest.mark.asyncio
async def test_single_miss_without_near_matches_is_byte_identical_to_before(
    mcp_module, monkeypatch, fake_access_token, respx_router, variant
):
    """An API that predates the field (absent), nothing close ([]) or a malformed
    field: the miss text the tool always returned, character for character."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    near = {"absent": None, "empty": [], "not_a_list": {"offset": 1}, "junk_items": ["x", 3]}[variant]
    _mock_single(respx_router, near=near, omit_near=variant == "absent")
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="zzz")
    assert out == (
        "No match for 'zzz' in filing 1 (50000 chars searched, all of it). "
        "Try a shorter or different query (e.g. a single key term), or page the "
        "document with filings_markdown_retrieve."
    )


@pytest.mark.asyncio
async def test_a_miss_with_near_matches_is_still_a_miss_in_analytics(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The zero-hit rate is read from these events: near matches must not move it."""
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_single(respx_router, fid=7)
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool("filings_markdown_search", {"filing_id": 7, "query": "cash paid"})
    assert "APPROXIMATE" in result.content[0].text  # positive control: near matches rendered
    ev = [e for e in captured if e["name"] == "filings_markdown_search"][-1]
    assert (ev["result_count"], ev["has_data"]) == (0, False)


# --- batch tool --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_renders_near_matches_for_no_match_filings_only(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "cash paid for interest", "hit", hits=[(10, "cash paid for interest was 5")]),
        _row(2, "cash paid for interest", "no_match", near=NEAR[:2]),
        _row(3, "cash paid for interest", "no_match", near=[]),
        _row(4, "cash paid for interest", "unavailable", near=NEAR),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1, 2, 3, 4], query="cash paid for interest")
    # Outcomes unchanged: 2 and 3 are definite no-match filings, 4 is unknown.
    assert "1 with hits, 2 with none" in out
    assert "searched IN FULL and the term is not in them: 2, 3" in out
    assert "Unavailable" in out and "4 (not_processed)" in out
    near_part = out.split("No-match filings, closest passages", 1)[1]
    assert "=== filing 2 — no match ===" in near_part
    assert "near offset 1200 (has: cash, paid, interest)" in near_part
    assert "filing 3" not in near_part and "filing 4" not in near_part
    # Last, after the hit detail.
    assert out.index("=== filing 1 —") < out.index("No-match filings, closest passages")


@pytest.mark.asyncio
async def test_batch_without_near_matches_is_unchanged(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    rows = [_row(1, "q", "hit", hits=[(10, "q here")]), _row(2, "q", "no_match")]
    _mock_batch(respx_router, rows)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=[1, 2], query="q")
    assert "searched IN FULL and the term is not in them: 2" in out  # positive control
    assert "closest passages" not in out.lower() and "approximate" not in out.lower()


@pytest.mark.asyncio
async def test_batch_numeric_query_takes_near_matches_from_the_typed_spelling(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "19,409 revenue", "no_match", near=[_near(7, "TYPED", ["revenue"])]),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=[1], query="19,409 revenue")
    assert "TYPED" in out
    _mock_batch(respx_router, [
        _row(1, "19409", "no_match", near=[_near(7, "TYPED", ["19409"])]),
        _row(1, "19,409", "no_match", near=[_near(8, "COMMA", ["19,409"])]),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=[1], query="19409")
    assert "TYPED" in out and "COMMA" not in out


@pytest.mark.asyncio
async def test_batch_partly_searched_filing_shows_no_near_matches(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Unresolved is not "no match": its near matches would read as an answer."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_batch(respx_router, [
        _row(1, "19409", "no_match", near=[_near(7, "PARTIAL", ["19409"])]),
        _row(1, "19,409", "skipped"),
    ])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=[1], query="19409")
    assert "searched for only some spellings" in out  # positive control
    assert "PARTIAL" not in out


@pytest.mark.asyncio
async def test_batch_near_matches_are_dropped_before_any_hit_detail(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 6000)
    big = "x" * 700
    rows = [_row(1, "q", "hit", hits=[(10, "HIT-ONE " + big)])]
    rows += [_row(f, "q", "no_match", near=[_near(5, f"NEAR-{f} " + big, ["q"])]) for f in range(2, 12)]
    _mock_batch(respx_router, rows)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=list(range(1, 12)), query="q")
    assert "HIT-ONE" in out, "hit detail must survive the near matches"
    assert "NEAR-2 " in out, "the budget left room for some"
    assert "NEAR-11 " not in out
    assert "NOTE: closest passages for" in out and "omitted to stay under the result ceiling" in out
    assert len(out) <= 6000


@pytest.mark.asyncio
async def test_batch_no_near_matches_once_hit_detail_was_omitted(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", 3000)
    big = "x" * 900
    rows = [_row(f, "q", "hit", hits=[(10, f"HIT-{f} " + big)]) for f in (1, 2, 3, 4)]
    rows.append(_row(5, "q", "no_match", near=[_near(5, "NEAR-5", ["q"])]))
    _mock_batch(respx_router, rows)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(filing_ids=[1, 2, 3, 4, 5], query="q")
    assert "hit detail for" in out  # positive control: the hit budget was spent
    assert "NEAR-5" not in out
    assert "closest passages for 1 no-match filing(s) omitted" in out and out.rstrip().endswith("5")


@pytest.mark.asyncio
async def test_batch_near_matches_respect_max_hits_per_filing(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    four = [_near(o, f"N{o}", ["q"]) for o in (1, 2, 3, 4)]
    _mock_batch(respx_router, [_row(1, "q", "no_match", near=four)])
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=[1], query="q", max_hits_per_filing=2)
    assert "near offset 1 " in out and "near offset 2 " in out
    assert "near offset 3 " not in out


@pytest.mark.parametrize("ceiling", [1500, 2200, 3000, 4000, 6000, 9000])
@pytest.mark.parametrize("hits_cut", [False, True])
@pytest.mark.asyncio
async def test_batch_result_never_exceeds_the_ceiling(
    mcp_module, monkeypatch, fake_access_token, respx_router, ceiling, hits_cut
):
    """With 50 filings the notices carry up to 50 ids each, which no fixed
    reserve covers: the bound must hold at every ceiling, with the hit detail
    cut (two notices) or not."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "_BATCH_MAX_RESULT_CHARS", ceiling)
    big = "x" * 600
    hit_ids = list(range(1_000_000, 1_000_025)) if hits_cut else [1_000_000]
    rows = [_row(f, "q", "hit", hits=[(10, "HIT " + big)]) for f in hit_ids]
    near_ids = list(range(2_000_000, 2_000_050 - len(hit_ids)))
    rows += [_row(f, "q", "no_match", near=[_near(5, "NEAR " + big, ["q"])]) for f in near_ids]
    _mock_batch(respx_router, rows)
    out = await _tool(mcp_module, "filings_markdown_search_batch")(
        filing_ids=hit_ids + near_ids, query="q")
    assert "with hits" in out  # positive control: the outcome headline is there
    assert len(out) <= ceiling, (len(out), ceiling)
    if hits_cut:
        assert "hit detail for" in out  # positive control: the hit detail WAS cut
        assert "NEAR " not in out, "near-match text shown although hit detail was cut"


@pytest.mark.asyncio
async def test_single_numeric_query_takes_near_matches_from_the_typed_spelling(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)

    def answer(request):
        q = request.url.params["q"]
        near = [_near(1, "TYPED-SPELLING", ["19409"])] if q == "19409" else [_near(2, "COMMA-SPELLING", ["19,409"])]
        return httpx.Response(200, text=json.dumps({
            "filing_id": 1, "query": q, "total_chars": 10, "total_hits": 0, "hits": [], "near_matches": near}))
    route = respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/search/").mock(side_effect=answer)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="19409")
    assert route.call_count == 2  # positive control: both spellings were tried
    assert "TYPED-SPELLING" in out and "COMMA-SPELLING" not in out


@pytest.mark.asyncio
async def test_malformed_near_match_fields_neither_raise_nor_flood(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    odd = [{"offset": 1, "snippet": "S" * 50_000, "matched_words": 5, "missing_words": "abc"},
           {"offset": 2, "snippet": None, "matched_words": [f"w{i}" for i in range(500)]}]
    _mock_single(respx_router, near=odd)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="x y")
    assert "near offset 1 (has: -)" in out  # a non-list word field shows nothing
    assert "S" * 1_000 in out and "S" * 1_001 not in out
    assert "w19" in out and "w20" not in out
    assert len(out) < 5_000
