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
            # `snippet`: the field web's search endpoint returns (markdown_window.search).
            "hits": [{"offset": o, "snippet": c} for o, c in hits],
        })
    )


def _hit(offset, span):
    return {"offset": offset, "snippet": span}


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
    # Was `assert "SUBSTRING" in doc`, which web#10487 made too narrow to keep:
    # the matcher is no longer substring-ONLY, so the all-caps word went and the
    # disclosure is now the pair — what it matches exactly, and what else it
    # matches. Asserting the lowercase word alone would pass on copy that still
    # claimed a plain substring search, which is the defect #213 filed.
    assert "substring match" in doc, "the match TYPE is no longer disclosed at all"


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
async def test_no_hit_is_reported_as_OUT_OF_REACH_any_more(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """#175 retired the reachability disclosure AT THE SOURCE.

    WHAT WAS HERE BEFORE, and why it is gone. Five tests pinned a three-band
    note on this tool's result: a hit past `_MAX_FILING_BYTES` was "certainly
    unreachable", a hit below a quarter of it "certainly reachable", and the
    span between "depends on this document's density" -- because this tool
    reports CHARACTER offsets while `filings_markdown_retrieve` capped BYTES,
    and in 2-byte text character 5.5M is byte 11M. SPECHT caught the first
    version comparing the two units directly (3/3).

    Those bands were exact and they were correct. They are now MOOT: #175 moved
    retrieve to window upstream on the same CHARACTER offsets, so every hit this
    tool reports is fetchable. Keeping the note would tell a model a passage is
    out of reach when it is not -- sending it to a 440-character snippet instead
    of the text it could have read. That is a worse failure than the one the
    note prevented, which is why the removal is part of the fix rather than
    cleanup.

    So this asserts the INVERSE invariant: a far-offset hit carries no
    reachability hedge. If a byte cap is ever reintroduced into retrieve, this
    passes while the lie returns -- so it is paired with
    tests/test_markdown_retrieve_windows_upstream.py, which pins the windowing
    itself. Neither alone is sufficient and that is stated rather than implied.
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    far = 12_000_000
    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/search/").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": [{"offset": far, "snippet": "the passage"}],
                "total_hits": 1,
                "total_chars": 20_000_000,
            },
        )
    )
    out = await _tool(mcp_module, "filings_markdown_search")(filing_id=1, query="x")

    assert str(far) in out, "the offset itself must still be reported"
    for hedge in (
        "cannot reach",
        "out of reach",
        "may be out of reach",
        "whole passage available",
    ):
        assert hedge not in out, (
            f"the result still hedges with {hedge!r}: every offset is fetchable "
            "since #175, so this sends the model away from text it can read"
        )


def _snapshot_search_description() -> str:
    """The committed snapshot's own text for GET /filings/{id}/markdown/search/.

    Read with a parser, never with a line-oriented tool: the snapshot is a
    SINGLE LINE of JSON, so `grep -c` on it is a constant and `head` sees the
    whole file. A count that cannot vary reads as a measurement.
    """
    import json
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"
    )
    with open(path, encoding="utf-8") as handle:
        snap = json.load(handle)
    return " ".join(
        snap["paths"]["/filings/{id}/markdown/search/"]["get"]["description"].split()
    )


def test_the_tool_describes_the_split_phrase_contract_upstream_actually_states(
    mcp_module,
) -> None:
    """⛔ web#10487 WIDENED THE MATCHER AND FOUR COPY SITES KEPT SAYING "SUBSTRING".

    They were false in the expensive direction: a model reading "this is a
    substring search" avoids exactly the phrase queries that now work, so the
    capability shipped and nothing used it (mcp-server#213 item 1).

    The claim is pinned against the SNAPSHOT'S OWN SENTENCE rather than against
    a string a human retyped here, so the test fails when upstream rewords the
    contract instead of silently passing on stale prose — the same discipline as
    `test_the_hand_written_lead_still_matches_upstream`. The sibling direction is
    worth stating: our copy is hand-written, so nothing but this test connects it
    to the thing it describes.
    """
    upstream = _snapshot_search_description()
    # If upstream drops the clause this test exists for, say so plainly rather
    # than failing on our copy — the fixture, not the tool, is what moved.
    assert "ran its words together" in upstream, (
        "the snapshot no longer states the split-phrase rule. Either the refresh "
        "regressed or the API changed; re-read /filings/{id}/markdown/search/ "
        "before touching the tool copy."
    )
    # ⚠ NORMALISE THE WHITESPACE BEFORE MATCHING. A docstring is wrapped and
    # indented, so a phrase crossing a line break contains "\n    " and a
    # substring test on the flat phrase fails on FORMATTING rather than content.
    # It cost a red run here, and the same omission on an `assert ... not in`
    # would have passed while the stale claim sat in the copy.
    doc = " ".join((_tool(mcp_module, "filings_markdown_search").__doc__).split())
    for claim in (
        "ran its words together",   # what else matches
        "Exact hits come first",    # the ORDER, which decides what a model reads first
        "total_hits",               # that the count covers both kinds
    ):
        assert claim in doc, (
            f"filings_markdown_search does not disclose {claim!r}; upstream states it"
        )
    assert "is a SUBSTRING" not in doc, (
        "the pre-web#10487 claim survives in the tool copy"
    )


def test_the_batch_no_longer_has_a_matcher_of_its_own(mcp_module) -> None:
    """⛔ THIS REPLACES `test_md_scan_hits_has_exactly_one_caller`, AND THE OLD TEST
    PREDICTED ITS OWN RETIREMENT: it said the count was "asserted in BOTH
    directions ... and losing the last caller means the helper is dead." #213 took
    the last caller, so the helper went with it.

    What the old test was really protecting was never the count. It was the claim
    `_md_scan_hits`' docstring made for two weeks -- that the two search tools
    "cannot drift" -- which went false when #173 moved the single tool server-side
    and THE OTHER CALLER LEFT, without the function or its comment changing. That
    invariant is now true again, and for a better reason: there is no second
    matcher to drift FROM. So the guard moves from counting callers of a local
    scanner to asserting that no local scanner exists.

    ⛔⛔ STILL MEASURED ON THE RENDERED MODULE, for the reason that cost two wrong
    versions of the old test: `scripts/generate_mcp_tools.py` holds the tools as
    TEXT inside a template string, so a regex there matches MENTIONS as well as
    occurrences -- the comment explaining the removal names `_md_scan_hits` -- and
    `ast` there finds nothing at all. The emitted module is where the code is real
    Python, and it is also the thing that ships.
    """
    import ast
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..", "src", "financial_reports_mcp.py"
    )
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # POSITIVE CONTROL FIRST, because every assertion below is an absence: if the
    # render were empty or unparsed, they would all pass for free.
    assert "filings_markdown_search_batch" in names, "the render did not contain the tool"
    assert "_md_candidates" in names, "the render did not contain the numeric fallback"

    assert "_md_scan_hits" not in names, (
        "a client-side scanner is back. Re-introducing one re-opens the matcher "
        "divergence #213 closed: a local scan does not do the split-phrase "
        "matching web#10487 shipped, so a phrase the single tool finds would be "
        "missed here on the same filing -- and the batch's description now tells "
        "a model the two agree."
    )
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_md_scan_hits" not in calls


def test_the_numeric_fallback_is_shared_so_neither_tool_may_claim_literal_only() -> None:
    """The fact that made "EXACT substring match only" wrong, pinned structurally.

    `_md_candidates` adds the thousands-separator spelling of a number, and BOTH
    search tools call it. So the numeric fallback is COMMON BEHAVIOUR, never one
    tool's exactness and never a divergence between them.

    ⇒ Two consequences, and the test exists because I got both wrong in one
    sentence: neither description may advertise a literal-only match, and the
    fallback must not be offered as a contrast between them.

    ⭐ THE CALLER LIST CHANGED WITH #213 AND THE INVARIANT DID NOT. It used to be
    `_md_scan_hits` (the batch's client-side scan) and `filings_markdown_search`;
    it is now the two TOOLS, because the batch sends its candidates to the
    endpoint as two of the three `queries` instead of scanning for them here. The
    sharing is in fact stronger than before -- the same mechanism on both paths
    rather than one scanned locally and one sent over the wire -- which is why
    this test survives the move while the one above it did not.

    ⇒ Counted with `ast` on the RENDERED module: the generator holds this code as
    text inside a template string, so the structural signal is absent from the
    file that contains it.
    """
    import ast
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..", "src", "financial_reports_mcp.py"
    )
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    enclosing = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_md_candidates"
            ):
                # Innermost wins: a nested def would otherwise be attributed to
                # its parent and make the two paths look like one.
                prev = enclosing.get(inner.lineno)
                if prev is None or node.lineno > prev[1]:
                    enclosing[inner.lineno] = (node.name, node.lineno)
    callers = sorted({name for name, _ in enclosing.values()})
    assert callers == ["filings_markdown_search", "filings_markdown_search_batch"], (
        "the numeric fallback's callers changed: "
        f"{callers}. If only ONE path still has it, the two tools now really do "
        "differ on numbers and both descriptions must say so; if a third appears, "
        "check it is not a path that advertises a literal match."
    )
