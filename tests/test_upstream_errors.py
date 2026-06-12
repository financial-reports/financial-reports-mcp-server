"""Typed upstream errors + fail-closed credential guard (issue #32).

Pins three behaviors:
  1. Structured tools raise `UpstreamHTTPError` carrying `upstream_status`,
     `request_id`, and an actionable message — never an opaque RuntimeError.
  2. `_inject_auth` refuses to forward a JWT without a `kid` (the FastMCP
     HS256 proxy token must never reach the upstream API).
  3. `_jwt_fingerprint` produces a safe diagnostic string that never leaks
     the token itself.
"""
from __future__ import annotations

import base64
import json
import logging

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _make_jwt(header: dict) -> str:
    """JWT-shaped string with a real JOSE header and dummy payload/signature."""
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    return f"{h}.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"


HS256_PROXY_JWT = _make_jwt({"alg": "HS256", "typ": "JWT"})
RS256_COGNITO_JWT = _make_jwt({"alg": "RS256", "kid": "test-kid-1", "typ": "JWT"})


def _structured_tool(mcp_module, name="companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


# --- 1. typed upstream errors -----------------------------------------------


@pytest.mark.asyncio
async def test_structured_403_raises_typed_error_with_context(
    mcp_module, monkeypatch, fake_access_token, respx_router, caplog
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            403,
            json={"detail": "Authentication error: Invalid token header. No kid provided."},
            headers={"x-request-id": "req-test-123"},
        )
    )

    fn = _structured_tool(mcp_module)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
            await fn()

    exc = ei.value
    assert exc.upstream_status == 403
    assert exc.request_id == "req-test-123"
    msg = str(exc)
    assert "upstream companies_list returned 403" in msg
    assert "reconnect" in msg.lower()  # actionable for the LLM/user
    assert "req-test-123" in msg
    # The upstream body is logged server-side, never echoed to the client.
    assert "No kid provided" not in msg
    assert any("upstream companies_list" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_structured_503_message_suggests_retry(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(503, text="upstream blip")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    assert ei.value.upstream_status == 503
    assert "retry" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_structured_429_message_mentions_rate_limit(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(429, text="slow down")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    assert ei.value.upstream_status == 429
    assert "rate limit" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_structured_timeout_raises_typed_error_without_url(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=httpx.ConnectTimeout("connection timed out")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    exc = ei.value
    assert exc.upstream_status is None
    msg = str(exc)
    assert "ConnectTimeout" in msg
    assert "retry" in msg.lower()
    # No internal hostnames in client-facing text.
    assert "api.test.invalid" not in msg


@pytest.mark.asyncio
async def test_structured_tool_still_releases_context_on_typed_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(500, text="boom")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await fn()

    assert mcp_module._current_token.get() == ""


# --- 2. fail-closed kid guard ------------------------------------------------


@pytest.mark.asyncio
async def test_inject_auth_refuses_jwt_without_kid(
    mcp_module, monkeypatch, fake_access_token, respx_router, caplog
) -> None:
    """The HS256 proxy token (no kid) must never be forwarded upstream."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, token=HS256_PROXY_JWT)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(mcp_module.AuthenticationError) as ei:
            await fn()

    assert "reconnect" in str(ei.value).lower()
    assert route.call_count == 0  # failed closed BEFORE the request left
    assert HS256_PROXY_JWT not in caplog.text  # token never logged


@pytest.mark.asyncio
async def test_inject_auth_forwards_jwt_with_kid(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token, token=RS256_COGNITO_JWT)
    captured = {}

    def _respond(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"count": 0, "results": []})

    respx_router.get(f"{TEST_API_BASE}/companies/").mock(side_effect=_respond)

    fn = _structured_tool(mcp_module)
    out = await fn()
    assert out == {"count": 0, "results": []}
    assert captured["auth"] == f"Bearer {RS256_COGNITO_JWT}"


@pytest.mark.asyncio
async def test_inject_auth_forwards_opaque_token(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Non-JWT bearers (test/dev opaque tokens) are not the issue-#32 failure
    mode and must keep working."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token")
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    out = await fn()
    assert out == {"count": 0, "results": []}


@pytest.mark.asyncio
async def test_text_tool_surfaces_guard_message(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """On the text path the guard's actionable message reaches the LLM
    instead of the generic 'see server logs' string."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, token=HS256_PROXY_JWT)

    tool = mcp_module.mcp._tool_manager._tools["filing_types_list"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    out = await fn()
    assert "reconnect" in out.lower()
    assert "see server logs" not in out.lower()


# --- 3. JWT fingerprint -------------------------------------------------------


def test_jwt_fingerprint_never_leaks_token(mcp_module) -> None:
    fp = mcp_module._jwt_fingerprint(HS256_PROXY_JWT)
    assert "alg=HS256" in fp
    assert "kid=missing" in fp
    for segment in HS256_PROXY_JWT.split("."):
        assert segment not in fp

    fp_rs = mcp_module._jwt_fingerprint(RS256_COGNITO_JWT)
    assert "alg=RS256" in fp_rs
    assert "kid=present" in fp_rs


def test_jwt_fingerprint_handles_non_jwt_inputs(mcp_module) -> None:
    assert mcp_module._jwt_fingerprint("") == "absent"
    fp = mcp_module._jwt_fingerprint("real-access-token")
    assert fp.startswith("opaque")
    assert "real-access-token" not in fp


# --- hardening (adversarial-review findings) ----------------------------------


@pytest.mark.asyncio
async def test_upstream_error_log_redacts_token_in_body(
    mcp_module, monkeypatch, fake_access_token, respx_router, caplog
) -> None:
    """If the upstream ever echoes a bearer in its error body, the server-side
    log line must carry the redacted form, never the token."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    echoed_jwt = (
        "eyJhbGciOiJSUzI1NiIsImtpZCI6ImFiYzEyMyJ9."
        "eyJzdWIiOiJzZWNyZXQtdXNlciJ9.c2lnbmF0dXJlLWJ5dGVz"
    )
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            403, json={"detail": "rejected", "echo": f"Bearer {echoed_jwt}"}
        )
    )

    fn = _structured_tool(mcp_module)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(mcp_module.UpstreamHTTPError):
            await fn()

    assert echoed_jwt not in caplog.text
    assert "<redacted" in caplog.text


def test_jose_header_rejects_oversized_header(mcp_module) -> None:
    """A multi-KB JOSE header must not be base64/JSON-decoded per call."""
    huge = "A" * 5000 + ".payload.sig"
    assert mcp_module._jose_header(huge) is None
    assert mcp_module._jwt_fingerprint(huge).startswith("opaque")
    assert mcp_module._jwt_lacks_kid(huge) is False


# --- 403 sub-case classification (issue: "User profile not found" path) ------


@pytest.mark.asyncio
async def test_403_missing_profile_body_gives_signup_hint(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Upstream 403 with 'User profile not found' must direct the user to
    sign up — NOT to 'disconnect and reconnect' (which is a dead-end loop)."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            403, json={"detail": "User profile not found for the provided token."}
        )
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    exc = ei.value
    assert exc.upstream_status == 403
    assert exc.error_kind == "missing_profile"
    msg = str(exc)
    assert "financialreports.eu/signup" in msg
    assert "support@financialreports.eu" in msg
    # The old hint must not appear — it would loop the user.
    assert "disconnect and reconnect" not in msg.lower()


@pytest.mark.asyncio
async def test_403_expired_token_body_gives_session_hint(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Upstream 403 'Token has expired' (the upstream's own message) gets
    the reconnect hint — that one IS the right next step."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            403, json={"detail": "Token has expired. Please re-authenticate."}
        )
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    exc = ei.value
    assert exc.error_kind == "expired_token"
    msg = str(exc).lower()
    assert "session has expired" in msg or "session expired" in msg
    assert "reconnect" in msg


@pytest.mark.asyncio
async def test_403_malformed_body_falls_back_to_default_hint(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Defensive: a malformed body must not raise during classification —
    falls back to the generic credentials-rejected hint."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(403, text="not json at all {{{")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    exc = ei.value
    assert exc.error_kind == "invalid_credentials"
    assert "reconnect" in str(exc).lower()


@pytest.mark.asyncio
async def test_5xx_error_kind_is_transient(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(503, text="blip")
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    assert ei.value.error_kind == "transient"


@pytest.mark.asyncio
async def test_401_error_kind_is_expired_token(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(401, json={"detail": "auth required"})
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await fn()

    assert ei.value.error_kind == "expired_token"
