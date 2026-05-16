"""auth_required decorator: validates Cognito JWT without backend verify call."""
from __future__ import annotations

import pytest

from .conftest import TEST_CLIENT_ID


@pytest.mark.asyncio
async def test_no_token_returns_auth_error(mcp_module, monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: None)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "should not reach here"

    out = await tool()
    assert "authentication required" in out.lower()


@pytest.mark.asyncio
async def test_get_access_token_raises(mcp_module, monkeypatch) -> None:
    def raises():
        raise RuntimeError("auth backend down")

    monkeypatch.setattr(mcp_module, "get_access_token", raises)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "should not reach here"

    out = await tool()
    assert "authentication required" in out.lower()


@pytest.mark.asyncio
async def test_missing_sub_returns_auth_error(
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
    assert "authentication required" in out.lower()


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

    @mcp_module.subscription_required
    async def tool() -> str:
        assert mcp_module._current_token.get() == at.token
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
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    at.claims = {"sub": "test-sub-12345678", "client_id": TEST_CLIENT_ID, "aud": aud_claim}
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "ok"

    out = await tool()
    assert out == "ok"


@pytest.mark.asyncio
async def test_aud_claim_rejects_foreign_audience(
    mcp_module, monkeypatch, fake_access_token
) -> None:
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
    assert "authentication required" in out.lower()


@pytest.mark.asyncio
async def test_aud_claim_optional_when_missing(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    at.claims = {"sub": "test-sub-12345678", "client_id": TEST_CLIENT_ID}  # no aud
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    @mcp_module.subscription_required
    async def tool() -> str:
        return "ok"

    assert await tool() == "ok"
