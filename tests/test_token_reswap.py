"""Root fix for issue #32: re-run the OAuth proxy token swap.

Under Streamable HTTP, fastmcp's `get_access_token()` can fall back to the
SDK contextvar and hand the auth helpers the FastMCP HS256 *reference* token
instead of the swapped upstream Cognito token (fastmcp #1863). These tests
pin the recovery path: when the presented token is JWT-shaped without a
`kid`, the auth helpers re-run `auth_provider.load_access_token()` to obtain
the real upstream token — and fail closed with an actionable message when
the swap cannot recover one.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID
from .test_upstream_errors import HS256_PROXY_JWT, RS256_COGNITO_JWT


class _SwappedAccessToken:
    """Shape of the AccessToken the proxy returns after a successful swap."""

    def __init__(self, token: str = RS256_COGNITO_JWT) -> None:
        self.token = token
        self.client_id = TEST_CLIENT_ID
        self.claims = {"sub": "swapped-sub-1234", "client_id": TEST_CLIENT_ID}


class _StubProvider:
    def __init__(self, result) -> None:
        self._result = result
        self.calls: list[str] = []

    async def load_access_token(self, token: str):
        self.calls.append(token)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _structured_tool(mcp_module, name="companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


@pytest.mark.asyncio
async def test_reswap_recovers_cognito_token(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Proxy token in hand + successful swap -> upstream gets the Cognito token."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    provider = _StubProvider(_SwappedAccessToken())
    monkeypatch.setattr(mcp_module, "auth_provider", provider)

    captured = {}

    def _respond(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"count": 0, "results": []})

    respx_router.get(f"{TEST_API_BASE}/companies/").mock(side_effect=_respond)

    fn = _structured_tool(mcp_module)
    out = await fn()

    assert out == {"count": 0, "results": []}
    assert provider.calls == [HS256_PROXY_JWT]
    assert captured["auth"] == f"Bearer {RS256_COGNITO_JWT}"


@pytest.mark.asyncio
async def test_reswap_failure_raises_actionable_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Swap returns None (expired/lost upstream token) -> fail closed, no request."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    monkeypatch.setattr(mcp_module, "auth_provider", _StubProvider(None))
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.AuthenticationError) as ei:
        await fn()

    assert "reconnect" in str(ei.value).lower()
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_reswap_provider_exception_fails_closed(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    monkeypatch.setattr(
        mcp_module, "auth_provider", _StubProvider(RuntimeError("redis down"))
    )
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.AuthenticationError):
        await fn()
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_reswap_returning_kidless_token_fails_closed(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A swap that hands back another kid-less JWT must not be forwarded."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    monkeypatch.setattr(
        mcp_module,
        "auth_provider",
        _StubProvider(_SwappedAccessToken(token=HS256_PROXY_JWT)),
    )
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    with pytest.raises(mcp_module.AuthenticationError):
        await fn()
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_reswap_not_triggered_for_kid_token(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A proper Cognito RS256 token must never pay the re-swap round-trip."""
    _auth_as(mcp_module, monkeypatch, fake_access_token, RS256_COGNITO_JWT)
    provider = _StubProvider(RuntimeError("must not be called"))
    monkeypatch.setattr(mcp_module, "auth_provider", provider)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    fn = _structured_tool(mcp_module)
    out = await fn()
    assert out == {"count": 0, "results": []}
    assert provider.calls == []


@pytest.mark.asyncio
async def test_text_path_reswap_recovers_token(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    monkeypatch.setattr(mcp_module, "auth_provider", _StubProvider(_SwappedAccessToken()))

    captured = {}

    def _respond(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"count": 0, "results": []})

    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(side_effect=_respond)

    tool = mcp_module.mcp._tool_manager._tools["filing_types_list"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    out = await fn()

    assert "```json" in out
    assert captured["auth"] == f"Bearer {RS256_COGNITO_JWT}"


@pytest.mark.asyncio
async def test_text_path_reswap_failure_returns_reconnect_message(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token, HS256_PROXY_JWT)
    monkeypatch.setattr(mcp_module, "auth_provider", _StubProvider(None))

    tool = mcp_module.mcp._tool_manager._tools["filing_types_list"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    out = await fn()

    assert "reconnect" in out.lower()
    assert "authentication" in out.lower()
