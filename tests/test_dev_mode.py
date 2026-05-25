"""DEV_MODE_API_KEY auth bypass — local-development only."""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator

import pytest


@pytest.fixture()
def dev_mode_module(respx_router, monkeypatch) -> Iterator[object]:
    """Re-import the MCP module with DEV_MODE_API_KEY set."""
    monkeypatch.setenv("DEV_MODE_API_KEY", "fr_test_devkey_abc123")
    # Force MCP_BASE_URL to a non-prod hostname so the prod guard does not trip.
    monkeypatch.setenv("MCP_BASE_URL", "http://localhost:8000")
    sys.modules.pop("src.financial_reports_mcp", None)
    import src.financial_reports_mcp as m  # type: ignore
    importlib.reload(m)
    yield m


def test_dev_mode_config_exposed(dev_mode_module) -> None:
    """The generated module reads DEV_MODE_API_KEY at import time."""
    assert dev_mode_module.DEV_MODE_API_KEY == "fr_test_devkey_abc123"


@pytest.mark.asyncio
async def test_dev_mode_skips_jwt_and_sets_token(dev_mode_module) -> None:
    """With DEV_MODE_API_KEY, get_access_token is never called and the
    API key is placed into _current_token for the wrapped tool."""
    sentinel: dict[str, str] = {}

    @dev_mode_module.subscription_required
    async def tool() -> str:
        sentinel["token"] = dev_mode_module._current_token.get()
        return "ok"

    # Even if get_access_token would raise, the bypass should not call it.
    def boom():  # pragma: no cover — should not run
        raise AssertionError("get_access_token must not be called in dev mode")

    dev_mode_module.get_access_token = boom  # type: ignore[attr-defined]

    out = await tool()
    assert out == "ok"
    assert sentinel["token"] == "fr_test_devkey_abc123"


@pytest.mark.asyncio
async def test_dev_mode_clears_token_after_call(dev_mode_module) -> None:
    """The contextvar is reset after the wrapped function returns."""

    @dev_mode_module.subscription_required
    async def tool() -> str:
        return "ok"

    await tool()
    assert dev_mode_module._current_token.get() == ""


def test_prod_hostname_guard(monkeypatch) -> None:
    """Setting DEV_MODE_API_KEY against the prod hostname refuses to import."""
    monkeypatch.setenv("DEV_MODE_API_KEY", "leak_attempt")
    monkeypatch.setenv("MCP_BASE_URL", "https://mcp.financialfilings.com")
    sys.modules.pop("src.financial_reports_mcp", None)
    with pytest.raises(RuntimeError, match="never be enabled in prod"):
        import src.financial_reports_mcp  # noqa: F401


@pytest.mark.asyncio
async def test_dev_mode_injects_xapikey_header(dev_mode_module, respx_router) -> None:
    """In dev mode the upstream call carries X-API-Key, not Bearer."""
    import httpx
    captured: dict[str, str] = {}

    def capture(request):
        captured["auth"] = request.headers.get("Authorization", "")
        captured["xapikey"] = request.headers.get("X-API-Key", "")
        return httpx.Response(200, json={"ok": True})

    respx_router.get("https://api.test.invalid/probe").mock(side_effect=capture)

    token_reset = dev_mode_module._current_token.set(dev_mode_module.DEV_MODE_API_KEY)
    try:
        resp = await dev_mode_module._api_client.get("/probe")
    finally:
        dev_mode_module._current_token.reset(token_reset)
    assert resp.status_code == 200
    assert captured["xapikey"] == "fr_test_devkey_abc123"
    assert captured["auth"] == ""  # bearer NOT set in dev mode
