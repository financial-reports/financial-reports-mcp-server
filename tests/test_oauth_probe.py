"""Unit coverage for the prod OAuth probe's #32-contract classifier.

The live probe (`tests/e2e/test_prod_oauth_probe.py`) is env-gated and never runs
in CI. This pins the deterministic classifier it relies on — especially that a raw
upstream-403 leak is ALWAYS flagged `forbidden` and that `forbidden` beats a
reconnect hint — so the regression guard itself can't silently rot. No network.
"""
from __future__ import annotations

import pytest

from tests.e2e.oauth_probe import (
    FORBIDDEN_MARKERS,
    RECONNECT_MARKER,
    _follow_to_code,
    _scrape_csrf,
    classify,
)


def test_raw_upstream_403_is_forbidden() -> None:
    # The exact #32 signature the probe must always catch.
    text = "Error calling tool 'companies_list': upstream companies_list returned 403"
    assert classify(text, True) == "forbidden"


def test_no_kid_detail_is_forbidden() -> None:
    text = '{"detail":"Authentication error: Invalid token header. No kid provided."}'
    assert classify(text, True) == "forbidden"


def test_reconnect_message_is_accepted() -> None:
    # The post-#32 fail-closed message is an EXPECTED outcome, not a regression.
    msg = (
        "Your session could not be linked to upstream credentials. Please "
        "disconnect and reconnect the FinancialFilings connector, then retry."
    )
    assert classify(msg, True) == "reconnect"


def test_real_data_is_data() -> None:
    assert classify('{"results":[{"id":14,"name":"Alcoa"}]}', False) == "data"


def test_forbidden_beats_reconnect() -> None:
    # A 403 leak must never be masked as an acceptable reconnect outcome.
    assert classify("returned 403 — please disconnect and reconnect", True) == "forbidden"


def test_markers_are_what_the_probe_asserts_on() -> None:
    assert "returned 403" in FORBIDDEN_MARKERS
    assert RECONNECT_MARKER == "disconnect and reconnect"


# --- headless login helpers (#78) --------------------------------------------
# The headless mint itself needs prod plus real credentials, so it cannot run in
# CI. Its two pure helpers can, and they are where the parsing bugs would live.


class _StubResponse:
    """Minimal stand-in for httpx.Response's redirect surface."""

    def __init__(
        self,
        location: str,
        url: str = "https://mcp.example.invalid/authorize",
        text: str = "",
    ) -> None:
        self.headers = {"location": location} if location else {}
        self.url = url
        self.status_code = 302 if location else 200
        self.text = text


class _StubClient:
    """Serves canned responses by URL, recording what was fetched."""

    def __init__(self, routes: dict[str, _StubResponse]) -> None:
        self.routes = routes
        self.fetched: list[str] = []

    def get(self, url: str) -> _StubResponse:
        self.fetched.append(url)
        return self.routes[url]


def _handoff_page(url: str) -> str:
    """The AS's post-login hand-off page (web #5379), HTML-escaped as Django renders it."""
    escaped = url.replace("&", "&amp;")
    return (
        f'<html><head><meta http-equiv="refresh" content="0;url={escaped}"></head>'
        f'<body><a href="{escaped}">Continue</a></body></html>'
    )


def test_scrape_csrf_finds_the_token_in_either_attribute_order() -> None:
    name_first = '<input type="hidden" name="csrfmiddlewaretoken" value="tok-xyz789">'
    value_first = '<input value="tok-abc123" name="csrfmiddlewaretoken" />'
    assert _scrape_csrf(name_first) == "tok-xyz789"
    assert _scrape_csrf(value_first) == "tok-abc123"


def test_scrape_csrf_returns_empty_when_absent() -> None:
    """Empty rather than raising — the caller raises with a better message."""
    assert _scrape_csrf("<form><input name='identifier'></form>") == ""
    assert _scrape_csrf("") == ""


def test_follow_to_code_extracts_the_authorization_code() -> None:
    redirect = "http://localhost:8765/callback"
    resp = _StubResponse(f"{redirect}?code=the-code&state=st")
    assert _follow_to_code(None, resp, redirect) == "the-code"


def test_follow_to_code_raises_on_an_oauth_error() -> None:
    """An `error` in the callback query must not be reported as "no code" — the
    upstream reason is the useful part."""
    redirect = "http://localhost:8765/callback"
    resp = _StubResponse(f"{redirect}?error=access_denied&error_description=nope")
    with pytest.raises(RuntimeError, match="access_denied"):
        _follow_to_code(None, resp, redirect)


def test_follow_to_code_returns_empty_without_a_location() -> None:
    """A 200 re-rendering the login form (wrong password) carries no Location and
    must not be mistaken for a redirect chain."""
    resp = _StubResponse("")
    assert _follow_to_code(None, resp, "http://localhost:8765/callback") == ""


def test_follow_to_code_follows_the_meta_refresh_hand_off_page() -> None:
    """Since web #5379 a successful password POST answers 200 with a meta-refresh
    page to the connector callback (CSP form-action blocks a 302 chain in Chrome).
    The probe must follow it like a browser, unescaping `&amp;`, or #161 recurs."""
    redirect = "http://localhost:8765/callback"
    connector_cb = "https://mcp.example.invalid/auth/callback?code=as-code&state=st"
    client = _StubClient(
        {connector_cb: _StubResponse(f"{redirect}?code=the-code&state=st")}
    )
    posted = _StubResponse(
        "", url="https://as.example.invalid/oauth/authorize", text=_handoff_page(connector_cb)
    )
    assert _follow_to_code(client, posted, redirect) == "the-code"
    assert client.fetched == [connector_cb]


def test_follow_to_code_reads_an_oauth_error_off_the_hand_off_page() -> None:
    redirect = "http://localhost:8765/callback"
    posted = _StubResponse(
        "", text=_handoff_page(f"{redirect}?error=access_denied&state=st")
    )
    with pytest.raises(RuntimeError, match="access_denied"):
        _follow_to_code(None, posted, redirect)
