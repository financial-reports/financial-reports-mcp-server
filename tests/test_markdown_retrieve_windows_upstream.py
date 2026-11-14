"""`filings_markdown_retrieve` windows upstream instead of downloading then slicing (#175).

THE REGRESSION THIS CLOSES IS OUR OWN. Before #166 both markdown tools were
capped at `_MAX_FILING_BYTES` (10 MB) and agreed. #166 moved
`filings_markdown_search` to the server, which reads the WHOLE document — so
search began finding passages at offsets `filings_markdown_retrieve` could not
reach, because retrieve still streamed from byte 0 and stopped at the cap.
Measured in prod: 1,586 filings exceed it, the largest at 2.49 GB.

⚠ 0.003% of rows is the wrong denominator and is not cited as reassurance: a
long filing is exactly the kind a caller SEARCHES instead of reading, so the
affected population skews toward these tools' traffic.

`GET /filings/{id}/markdown/` already takes `offset` and `limit`, and the
window carries its own paging headers, so nothing is lost by using them:

    X-Total-Chars   the whole document's length
    X-Offset        the effective offset
    X-Next-Offset   present ONLY while characters remain — its ABSENCE is the
                    end-of-document signal

and the unit is CHARACTERS, matching the offsets `filings_markdown_search`
returns. That last point retires the three-band reachability caveat the search
tool carries: the bands existed only because search counted characters while
retrieve capped bytes.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


@pytest.fixture(autouse=True)
def _authed(mcp_module, monkeypatch, fake_access_token):
    """Every test here reaches the network, so all of them need a token."""
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


def _fn(mcp_module):
    tool = mcp_module.mcp._tool_manager._tools["filings_markdown_retrieve"]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


@pytest.mark.asyncio
async def test_it_asks_upstream_for_a_window(mcp_module, respx_router) -> None:
    """The whole point: the request must carry offset and limit.

    Without this the tool downloads the document and slices locally, which is
    what made offsets past the byte cap unreachable.
    """
    route = respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="y" * 100,
            headers={"X-Total-Chars": "100", "X-Offset": "0"},
        )
    )
    await _fn(mcp_module)(filing_id=7, offset=0, limit=100)

    assert route.called
    params = route.calls[0].request.url.params
    assert params.get("offset") == "0", "no offset sent: still downloading whole"
    assert params.get("limit") == "100", "no limit sent: still downloading whole"


@pytest.mark.asyncio
async def test_an_offset_past_the_old_byte_cap_is_reachable(
    mcp_module, respx_router
) -> None:
    """#175's actual symptom, as a test.

    An offset beyond `_MAX_FILING_BYTES` used to come back as "past the end",
    because the local buffer stopped there. Windowing upstream means the server
    resolves it.
    """
    far = 12_000_000  # past the old 10 MB cap
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="FOUND-THE-PASSAGE",
            headers={"X-Total-Chars": "20000000", "X-Offset": str(far)},
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=far, limit=1000)

    assert "FOUND-THE-PASSAGE" in out
    assert "past the end" not in out


@pytest.mark.asyncio
async def test_the_total_comes_from_the_header_not_from_the_body(
    mcp_module, respx_router
) -> None:
    """A window cannot be measured for its document's length.

    The prose reports "chars X to Y of TOTAL"; with a window, len(body) is the
    window, not the document. Reading the header is what keeps that honest —
    and a naive port would silently report the window size as the total.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="z" * 500,
            headers={"X-Total-Chars": "987654", "X-Offset": "0", "X-Next-Offset": "500"},
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=500)
    assert "987654" in out, "the document total is missing or is the window size"
    assert "of 500" not in out


@pytest.mark.asyncio
async def test_end_of_document_is_the_absence_of_x_next_offset(
    mcp_module, respx_router
) -> None:
    """The server's own end signal, rather than a length comparison.

    `X-Next-Offset` is present only while characters remain, so its absence is
    the end. Computing it locally from the window would be wrong at exactly the
    boundary where the window happens to end on the document's last character.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="w" * 200,
            headers={"X-Total-Chars": "200", "X-Offset": "0"},  # no X-Next-Offset
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=200)
    assert "TRUNCATED" not in out, "claimed more content at the end of the document"


@pytest.mark.asyncio
async def test_more_to_come_uses_the_servers_next_offset(
    mcp_module, respx_router
) -> None:
    """And the complement, so the fix above cannot overshoot into silence."""
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="w" * 200,
            headers={
                "X-Total-Chars": "5000",
                "X-Offset": "0",
                "X-Next-Offset": "200",
            },
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=200)
    assert "TRUNCATED" in out
    assert "offset=200" in out


@pytest.mark.asyncio
async def test_limit_is_clamped_to_what_upstream_accepts(
    mcp_module, respx_router
) -> None:
    """Upstream rejects a limit above 200,000 (`MAX_WINDOW_CHARS`).

    The tool's own ceiling is lower, so this is belt-and-braces — but sending a
    value the server 400s on would turn a caller's over-large request into an
    error instead of a clamped window.
    """
    route = respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200, text="q" * 10, headers={"X-Total-Chars": "10", "X-Offset": "0"}
        )
    )
    await _fn(mcp_module)(filing_id=7, offset=0, limit=10_000_000)
    assert int(route.calls[0].request.url.params["limit"]) <= 200_000


@pytest.mark.asyncio
async def test_a_total_that_says_more_wins_over_a_missing_next_offset(
    mcp_module, respx_router
) -> None:
    """The discriminating case mutation testing exposed.

    On a conforming server "X-Next-Offset absent" and "offset+len(window) ==
    total" are the same fact, so both of the earlier tests pass whichever signal
    the code reads — the mutation swapping one for the other survived them.

    They diverge when the total says more and the next-offset is absent. The
    costs are asymmetric: trusting the absence stops early and loses content
    silently, while trusting the union costs one extra call that returns
    empty-at-end. So the union wins, and this pins it.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="v" * 200,
            headers={"X-Total-Chars": "5000", "X-Offset": "0"},  # no X-Next-Offset
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=200)
    assert "TRUNCATED" in out, (
        "stopped at 200 of a 5000-char document because X-Next-Offset was "
        "absent; the remaining 4800 characters would be silently unreachable"
    )
    assert "offset=200" in out


@pytest.mark.asyncio
async def test_an_upstream_that_ignores_the_window_FAILS_rather_than_truncates(
    mcp_module, respx_router
) -> None:
    """Removing the 10 MB slice cap must not remove the MEMORY guard with it.

    SPECHT caught this 3/3: if an older upstream — or an intermediary — ignores
    `offset`/`limit` and returns the whole document, the buffering loop takes
    all of it, and the 2.49 GB filing this PR is about exhausts the replica.

    It FAILS rather than truncating, because a short buffer would be handed to
    the model as a complete window: a silent wrong answer, which is the failure
    mode this whole PR exists to remove.
    """
    oversized = "x" * (150_000 * 4 + 20_000)
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200, text=oversized, headers={"X-Total-Chars": str(len(oversized))}
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=150_000)

    assert "x" * 1000 not in out, (
        "returned a truncated buffer as if it were a window"
    )
    assert "error" in out.lower() or "not honouring" in out.lower()


@pytest.mark.asyncio
async def test_a_reply_without_the_total_header_is_REFUSED(
    mcp_module, respx_router
) -> None:
    """There is no safe fallback for a missing total (SPECHT 3/3).

    Deriving it from the body makes a short HTML error page — or a legacy
    whole-document reply — look like a complete filing with nothing after it:
    no continuation offered, and the rest silently unreachable. That is the
    failure this PR exists to remove, reintroduced by a convenience fallback.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(200, text="<html>gateway error</html>")
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=50_000)

    assert "gateway error" not in out, "an error page was presented as filing content"
    assert "not a window" in out.lower() or "error" in out.lower()


@pytest.mark.asyncio
async def test_a_window_that_starts_somewhere_ELSE_is_REFUSED(
    mcp_module, respx_router
) -> None:
    """Wrong content presented as the right content — the worst of the four.

    An upstream that ignores `offset` returns the document's BEGINNING. Without
    this check it is labelled "chars 120000 onward" and the continuation offset
    skips the passage actually requested, so the model reads the wrong text and
    is told it is the right text.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="THE-BEGINNING-OF-THE-DOCUMENT",
            headers={"X-Total-Chars": "900000", "X-Offset": "0"},  # ignored offset
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=120_000, limit=1000)

    assert "THE-BEGINNING-OF-THE-DOCUMENT" not in out, (
        "the document's beginning was presented as the passage at offset 120000"
    )
    # The caller-facing error is deliberately OPAQUE (_safe_error), so assert
    # that it is an error rather than looking for the offset in it. Asserting
    # the detail would pin a leak we do not want.
    assert "error" in out.lower()


@pytest.mark.asyncio
async def test_a_past_the_end_offset_is_still_allowed(
    mcp_module, respx_router
) -> None:
    """The control for the check above, so it cannot overshoot.

    Upstream reports `X-Offset: min(offset, total)`, so a past-the-end request
    legitimately answers with the total. Rejecting that as a mismatch would
    break the documented behaviour the #107 test pins.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200, text="", headers={"X-Total-Chars": "500", "X-Offset": "500"}
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=600, limit=1000)
    assert "past the end" in out
    assert "not honouring" not in out


@pytest.mark.asyncio
async def test_an_over_returned_window_is_CLAMPED_not_refused(
    mcp_module, respx_router
) -> None:
    """Over-returning is the benign violation, so it is clamped, not rejected.

    The content is the right content from the right offset — there is just more
    of it than the caller budgeted for. Returning 50x the requested text is a
    real cost to the caller's context; refusing it would be worse, since the
    data is usable. So: clamp, and let the continuation carry the rest.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="A" * 5000,
            headers={"X-Total-Chars": "5000", "X-Offset": "0"},
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=0, limit=100)

    # Count the BODY, not the whole result: the prose contains "MARKDOWN" and
    # "TRUNCATED", which carry an "A" each — the first version of this assertion
    # read 102 and blamed the clamp.
    body = out.split("---\n\n", 1)[1] if "---\n\n" in out else out
    assert body.count("A") == 100, f"returned {body.count('A')} chars for limit=100"
    assert "offset=100" in out, "the continuation must resume at what was returned"


@pytest.mark.asyncio
async def test_a_missing_offset_header_cannot_BYPASS_the_mismatch_check(
    mcp_module, respx_router
) -> None:
    """The guard added one commit ago had a hole: omit the header, skip the check.

    Defaulting a missing `X-Offset` to the REQUESTED offset meant an upstream
    could pass the mismatch guard by simply not sending the header — on exactly
    the response the guard exists to catch.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200,
            text="THE-BEGINNING-OF-THE-DOCUMENT",
            headers={"X-Total-Chars": "900000"},  # no X-Offset
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=120_000, limit=1000)
    assert "THE-BEGINNING-OF-THE-DOCUMENT" not in out
    assert "error" in out.lower()


@pytest.mark.asyncio
async def test_an_empty_window_before_the_end_is_REFUSED_not_looped(
    mcp_module, respx_router
) -> None:
    """An instruction to call the same offset forever.

    With no characters returned, `end_index` stays at `offset`, so the result
    read "Call again with offset=<the offset just requested>". A model
    following its own tool's instruction repeats the identical call
    indefinitely. Verified on the arithmetic before fixing:

        offset=1000 total=50000 window=0 -> end_index=1000, advertises more

    Empty AT or PAST the end is the legitimate case and stays valid — see
    test_a_past_the_end_offset_is_still_allowed.
    """
    respx_router.get(f"{TEST_API_BASE}/filings/7/markdown/").mock(
        return_value=httpx.Response(
            200, text="", headers={"X-Total-Chars": "50000", "X-Offset": "1000"}
        )
    )
    out = await _fn(mcp_module)(filing_id=7, offset=1000, limit=5000)

    assert "offset=1000" not in out, (
        "told the caller to repeat the identical request — an infinite loop"
    )
    assert "error" in out.lower()
