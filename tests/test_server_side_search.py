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


def _mock_search(respx_router, fid, *, hits, total_hits=None, total_chars=1000):
    """Mock the search endpoint. Local twin of the batch file's helper.

    ⚠ Mocking `/markdown/` instead would leave the search route unmocked, which
    makes the tool ERROR — and an erroring tool satisfies any `X not in out`
    assertion for free. Every absence assertion in this file is therefore paired
    with a positive one proving the tool actually ran.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/{fid}/markdown/search/").mock(
        return_value=httpx.Response(200, json={
            "filing_id": fid,
            "query": "q",
            "total_chars": total_chars,
            "total_hits": total_hits if total_hits is not None else len(hits),
            "hits": [{"offset": o, "context": c} for o, c in hits],
        })
    )


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
    that can tell "stops at the first hit" from "keeps whatever came last".

    ⚠ Re-pointed when `_md_candidates` became TYPED-FIRST: the scenario depends
    on WHICH spelling is tried first, so a deliberate order change had to move
    the hit with it. "19,409" now yields ["19,409", "19409"], so the literal
    form is candidate one and the document holds separators."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    asked = []

    def _first_hits(request):
        q = dict(request.url.params).get("q")
        asked.append(q)
        if q == "19,409":
            return httpx.Response(200, json={
                "filing_id": 1, "query": q, "total_chars": 900,
                "total_hits": 1, "hits": [_hit(12, "separated 19,409 here")],
            })
        return httpx.Response(200, json={
            "filing_id": 1, "query": q, "total_chars": 900, "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_first_hits)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="19,409")
    assert asked == ["19,409"], f"it kept asking after a hit: {asked}"
    assert "separated 19,409 here" in out, f"the first hit was overwritten: {out!r}"


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


def test_candidate_order_is_TYPED_FIRST_not_bare_first(mcp_module) -> None:
    """⛔ Found from web#8990, which made the REST comma rule LITERAL-FIRST.

    `_md_candidates` returned the bare form first **whatever the user typed**:
    "19,409" → ["19409", "19,409"]. So this tool sent `q=19409` as its first
    request, and a literal-first server treats the `q` IT RECEIVES as the typed
    form — searching bare-first and never seeing the user's comma. ⇒ My
    client-side normalisation would have silently undone their fix, because the
    server cannot know what it was not sent.

    Typed-first is also the better order on the pre-#8990 server: a user who
    typed "19,409" means the literal form, and web#8990's own finding was that
    bare-first returned 1 bare hit where 2 literal ones existed.

    The bare form stays as the FALLBACK, which is the whole point of the helper:
    a figure typed without separators must still match "19,409"."""
    assert mcp_module._md_candidates("19,409") == ["19,409", "19409"], (
        "a comma-typed query must try the literal form first"
    )
    assert mcp_module._md_candidates("19409") == ["19409", "19,409"], (
        "a bare-typed query must try the bare form first"
    )
    # Non-numeric is untouched: one candidate, no second request.
    assert mcp_module._md_candidates("going concern") == ["going concern"]


# --- The query-length bound (SPECHT S2 on PR #173, 3/3 passes) ----------------
#
# Before #166 the scan was LOCAL, so `query` had no effective length limit. Now
# `q` crosses the wire into web's parse_search(), which raises ValidationError
# -> 400 above MAX_QUERY_CHARS = 200. So an over-long query went from a local
# no-op to an upstream error after a paid round trip.
#
# ⭐ WHY THE REVIEWER'S CITED EVIDENCE WAS WRONG AND THE FINDING STILL REAL:
# it attributed the limit to `scripts/openapi.snapshot.json`, where `q` is a
# bare {"type": "string"} with no maxLength. The bound lives in the SERVER, in
# the other repo, and is invisible to the schema — so checking the snapshot
# first (as I did) refutes the warrant while the defect stands. The number was
# read from filings/markdown_window.py:27, not from the review.
#
# Rejected fix: keep a local-scan path for long queries. That reinstates the
# 10 MB download, the byte cap and the truncation hedge — i.e. un-does the PR
# for exactly the queries least likely to match anything, since a 200+ char
# exact SUBSTRING match is near-hopeless by construction.


@pytest.mark.asyncio
async def test_an_over_long_query_is_refused_LOCALLY_and_never_hits_the_api(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """A negative control on the wire, which is the whole point.

    Asserting only that it raises would pass just as well if the tool sent the
    query, got a 400 and re-raised it — the round trip is the regression, so the
    call count is the assertion that can see it."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    calls = {"n": 0}

    def _count(request):
        calls["n"] += 1
        return httpx.Response(200, json={
            "filing_id": 1, "query": "x", "total_chars": 10,
            "total_hits": 1, "hits": [_hit(0, "x")],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_count)
    too_long = "a" * (mcp_module._MAX_QUERY_CHARS + 1)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query=too_long)
    assert calls["n"] == 0, "an over-long query was sent to the API anyway"
    assert "200 characters" in out and "201" in out


@pytest.mark.asyncio
async def test_a_query_at_exactly_the_limit_is_still_sent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The boundary, in the direction a too-eager guard would break.

    `> _MAX_QUERY_CHARS` and `>=` differ only here, and only this test fails if
    the guard is off by one — mirroring the server's own `len(query) > 200`."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    sent = []

    def _capture(request):
        sent.append(dict(request.url.params))
        return httpx.Response(200, json={
            "filing_id": 1, "query": "a", "total_chars": 10,
            "total_hits": 1, "hits": [_hit(0, "aaa")],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_capture)
    at_limit = "a" * mcp_module._MAX_QUERY_CHARS
    await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query=at_limit)
    assert len(sent) == 1, "a query at exactly the limit was refused"
    assert sent[0]["q"] == at_limit


def test_the_limit_mirrors_the_servers_and_is_stated_in_the_contract(mcp_module) -> None:
    """Two halves, because the constant alone is not a contract.

    An LLM only learns the bound from the tool DESCRIPTION; a guard the caller
    cannot see turns every long query into a wasted turn. And the value mirrors
    a server constant the OpenAPI schema does not carry, so nothing else in
    this repo would notice it drifting."""
    assert mcp_module._MAX_QUERY_CHARS == 200, (
        "mirrors web filings/markdown_window.py MAX_QUERY_CHARS"
    )
    doc = _tool(mcp_module, "filings_markdown_search").__doc__
    assert "200 characters" in doc, "the cap is enforced but not disclosed to the caller"
    assert "SUBSTRING" in doc


@pytest.mark.asyncio
async def test_an_over_long_COMMA_FALLBACK_is_skipped_not_sent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ A defect the INPUT guard introduced, found by SPECHT (2/3 phrasings).

    The guard bounds `raw`. What crosses the wire is each CANDIDATE. A 151-digit
    query is 151 characters and passes, but `_md_candidates` inserts 50 thousands
    commas, so the fallback is 201 and the server 400s it — turning a legitimate
    no-match into an upstream error on the second request.

    ⭐ Filtering can never empty the candidate list, and that is load-bearing
    rather than lucky: typed-first ordering puts `raw` first, and `raw` has
    already passed the same bound."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    sent = []

    def _capture(request):
        sent.append(dict(request.url.params)["q"])
        return httpx.Response(200, json={
            "filing_id": 1, "query": "x", "total_chars": 100,
            "total_hits": 0, "hits": [],
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_capture)

    digits = "1" * 151
    assert len(format(int(digits), ",")) == 201, "the premise: the comma form is over-limit"
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query=digits)

    assert sent == [digits], f"an over-limit candidate was sent: {[len(q) for q in sent]}"
    assert all(len(q) <= mcp_module._MAX_QUERY_CHARS for q in sent)
    # A genuine miss, reported as a miss — NOT as an upstream error.
    assert "No match" in out or "no match" in out.lower()


@pytest.mark.asyncio
async def test_an_in_limit_comma_fallback_is_STILL_sent(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control for the test above. A filter that dropped every comma candidate
    would pass that test and silently kill the fallback this PR must preserve —
    the same shape as the echo bound that rewrote every query."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    sent = []

    def _capture(request):
        q = dict(request.url.params)["q"]
        sent.append(q)
        hit = [_hit(0, "Revenue of 19,409 was reported.")] if "," in q else []
        return httpx.Response(200, json={
            "filing_id": 1, "query": q, "total_chars": 100,
            "total_hits": len(hit), "hits": hit,
        })

    respx_router.get(f"{TEST_API_BASE}{SEARCH}").mock(side_effect=_capture)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="19409")
    assert sent == ["19409", "19,409"], f"the fallback was dropped: {sent}"
    assert "19,409" in out


@pytest.mark.asyncio
async def test_a_hit_past_the_retrieve_cap_is_DISCLOSED(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ An asymmetry THIS PR created, flagged by SPECHT and measured in prod.

    The server searches the whole document; filings_markdown_retrieve still
    streams from byte 0 and stops at _MAX_FILING_BYTES. So a hit past that cap is
    a passage this tool found and that tool cannot reach — and the result used to
    hand the model an offset with no hint that following it is futile.

    Reachable, not theoretical: 1,586 prod filings exceed the cap, largest
    2.49 GB (control: 152,127 exceed 1 MB, so the predicate works). A share of
    53M rows is the wrong denominator — a long filing is exactly what gets
    SEARCHED rather than read.

    The real fix windows retrieve on the API's own offset/limit (#175). This only
    stops the tool from giving a confidently useless instruction."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    far = mcp_module._MAX_FILING_BYTES + 5_000
    _mock_search(
        respx_router, 1,
        hits=[(12, "Near the top."), (far, "Deep in a 2 GB filing.")],
        total_hits=2, total_chars=mcp_module._MAX_FILING_BYTES * 2,
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="covenant")
    assert "cannot reach" in out, "an unreachable offset was handed over silently"
    assert "1 of these hits" in out, "the count of unreachable hits is wrong"
    assert "Deep in a 2 GB filing" in out, "the context must still be shown"


@pytest.mark.asyncio
async def test_hits_INSIDE_the_cap_carry_no_such_note(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Control. A note on every result would be worse than the gap it describes —
    the same failure as a bound that rewrites every echo."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(respx_router, 1, hits=[(12, "Near the top.")], total_hits=1)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="covenant")
    assert "cannot reach" not in out


@pytest.mark.asyncio
async def test_the_cap_note_and_the_hit_cap_note_COEXIST(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """Both suffixes append. The first version assigned `suffix =`, so whichever
    condition ran second erased the other — a bug the two tests above would each
    have passed on their own."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    far = mcp_module._MAX_FILING_BYTES + 1
    _mock_search(respx_router, 1, hits=[(far, "Deep.")], total_hits=99)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="covenant")
    assert "cannot reach" in out and "99 match(es) exist" in out


@pytest.mark.asyncio
async def test_an_offset_EXACTLY_at_the_cap_is_unreachable(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The boundary, added because a mutation SURVIVED without it.

    `>=` -> `>` passed the whole file: the other tests use cap+5000 and cap+1 and
    never probe the edge itself. Offsets are 0-indexed and retrieve reads
    [0, _MAX_FILING_BYTES), so the byte AT the cap is the first one it does not
    read — `>=` is correct and only this test says so."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    _mock_search(
        respx_router, 1,
        hits=[(mcp_module._MAX_FILING_BYTES, "The first unread byte.")],
        total_hits=1, total_chars=mcp_module._MAX_FILING_BYTES * 2,
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="covenant")
    assert "cannot reach" in out, "off-by-one: the byte at the cap is NOT readable"


@pytest.mark.asyncio
async def test_the_three_offset_BANDS_are_exact_not_heuristic(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """⛔ REPLACES `test_the_LAST_READABLE_offset_is_not_flagged`, which became a
    VACUOUS PASS and whose name was a lie.

    That test used offset `cap - 1`, called it "the last readable byte", and
    asserted `"cannot reach" not in out`. After the character/byte fix `cap - 1`
    lands in the MAYBE band and IS flagged — the assertion survived only because
    the new wording says "may be out of reach" instead. It passed on a string, not
    on behaviour. Its premise was also wrong in the same way the finding was: a
    CHARACTER offset of `cap - 1` is only reachable in pure ASCII.

    The bands are exact, from UTF-8 bounds alone:
        >= 1 byte per char  => byte_off >= char_off  => `>= cap` is CERTAINLY out
        <= 4 bytes per char => byte_off <= 4*char_off => `< cap//4` is CERTAINLY in
        in between                                    => depends on the document
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    cap = mcp_module._MAX_FILING_BYTES

    async def _run(offset):
        respx_router.reset()
        _mock_search(respx_router, 1, hits=[(offset, "Passage here.")],
                     total_hits=1, total_chars=cap * 2)
        return await _tool(mcp_module, "filings_markdown_search")(
            filing_id=1, query="covenant"
        )

    # Band 1 — certainly reachable: no note of either kind.
    out = await _run(cap // 4 - 1)
    assert "cannot reach" not in out and "may be out of reach" not in out
    assert "Passage here" in out, "positive guard: the tool actually ran"

    # Band 2 — may be unreachable. NOT the certain wording, which is the whole
    # point: a provably-fetchable-in-ASCII hit must not be called unreachable.
    out = await _run(cap // 4)
    assert "may be out of reach" in out, "the quarter-cap boundary enters the maybe band"
    assert "cannot reach" not in out, "a maybe was reported as a certainty"

    out = await _run(cap - 1)
    assert "may be out of reach" in out
    assert "cannot reach" not in out

    # Band 3 — certainly unreachable, because bytes are never fewer than chars.
    out = await _run(cap)
    assert "cannot reach" in out
    assert "may be out of reach" not in out, "a certainty was softened to a maybe"


@pytest.mark.asyncio
async def test_the_maybe_note_names_the_UNIT_CONFUSION_not_just_the_risk(
    mcp_module, monkeypatch, fake_access_token, respx_router
):
    """The caveat has to say WHY, or the model cannot act on it.

    "may be out of reach" alone invites giving up. Naming the cause — the offset
    counts characters, the cap counts bytes — tells the model the hit is probably
    fine in ASCII and worth attempting, which is what the band actually means."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    cap = mcp_module._MAX_FILING_BYTES
    _mock_search(respx_router, 1, hits=[(cap // 2, "Passage.")],
                 total_hits=1, total_chars=cap * 2)
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="covenant")
    assert "CHARACTERS" in out and "BYTES" in out, "the cause is not stated"
    assert "Try it" in out, "the model is not told the attempt is worthwhile"
