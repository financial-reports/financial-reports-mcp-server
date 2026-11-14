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
