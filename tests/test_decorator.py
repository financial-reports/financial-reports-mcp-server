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
@pytest.mark.parametrize(
    "aud_claim",
    [
        TEST_CLIENT_ID,                                    # Cognito default
        "https://mcp.test.invalid/mcp",                    # canonical resource URI
        "https://mcp.test.invalid",                        # base URL form
        ["https://mcp.test.invalid/mcp", "ignored"],       # list form
    ],
)
async def test_aud_claim_accepts_canonical_audiences(
    mcp_module, monkeypatch, fake_access_token, aud_claim
) -> None:
    """`aud` claim must validate against the Cognito client_id OR the
    canonical resource URI. Anything else is rejected by the decorator."""
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    at.claims = {"sub": "test-sub-12345678", "client_id": TEST_CLIENT_ID, "aud": aud_claim}
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {"authorized": True}

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "ok"

    out = await tool()
    assert out == "ok"


@pytest.mark.asyncio
async def test_aud_claim_rejects_foreign_audience(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    """A token with `aud` pointing at a different MCP server (e.g. a token
    minted for some other Cognito-fronted MCP) must not be accepted here."""
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    at.claims = {
        "sub": "test-sub-12345678",
        "client_id": TEST_CLIENT_ID,
        "aud": "https://some-other-mcp.example/mcp",
    }
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "leak"

    out = await tool()
    assert "leak" not in out
    assert "subscription required" in out.lower()


@pytest.mark.asyncio
async def test_aud_claim_optional_when_missing(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    """If the IdP doesn't emit `aud` (some Cognito setups), client_id is the
    only audience check. We must still let the request through rather than
    blanket-failing on a missing optional claim."""
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    at.claims = {"sub": "test-sub-12345678", "client_id": TEST_CLIENT_ID}  # no aud
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {"authorized": True}

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "ok"

    assert await tool() == "ok"


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
