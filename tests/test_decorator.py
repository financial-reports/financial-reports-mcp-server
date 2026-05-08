"""subscription_required decorator: branches that don't reach _check_subscription."""
from __future__ import annotations

import pytest

from .conftest import TEST_CLIENT_ID


@pytest.mark.asyncio
async def test_no_token_returns_upgrade_response(mcp_module, monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: None)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "should not reach here"

    out = await tool()
    assert "subscription required" in out.lower()


@pytest.mark.asyncio
async def test_get_access_token_raises(mcp_module, monkeypatch) -> None:
    def raises():
        raise RuntimeError("auth backend down")

    monkeypatch.setattr(mcp_module, "get_access_token", raises)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "should not reach here"

    out = await tool()
    assert "subscription required" in out.lower()


@pytest.mark.asyncio
async def test_missing_sub_returns_upgrade(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token()
    at.claims = {}  # no sub
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "leak"

    out = await tool()
    assert "leak" not in out


@pytest.mark.asyncio
async def test_foreign_client_id_rejected(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    """Cross-app-client token replay must fail closed."""
    at = fake_access_token(client_id="someone-elses-client")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "leak"

    out = await tool()
    assert "leak" not in out
    assert "subscription required" in out.lower()


@pytest.mark.asyncio
async def test_missing_client_id_rejected(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token(client_id=None)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "leak"

    out = await tool()
    assert "leak" not in out


@pytest.mark.asyncio
async def test_authorized_passes_through(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        assert token == at.token
        assert sub == at.claims["sub"]
        return {"authorized": True, "plan": "analyst", "user_id": 1}

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    @mcp_module.subscription_required
    async def tool() -> str:
        # Inside the wrapped function, the contextvars must be set.
        assert mcp_module._current_token.get() == at.token
        assert mcp_module._current_user.get()["plan"] == "analyst"
        return "ok"

    out = await tool()
    assert out == "ok"


@pytest.mark.asyncio
async def test_unauthorized_returns_per_user_upgrade_url(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {
            "authorized": False,
            "reason": "subscription_required",
            "upgrade_url": "https://promo.example/x",
        }

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "leak"

    out = await tool()
    assert "promo.example/x" in out
