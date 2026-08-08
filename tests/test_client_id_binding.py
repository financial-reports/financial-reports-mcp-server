"""The `client_id` binding check, exercised through the ATTRIBUTE path.

Why this file exists
--------------------
`_resolve_upstream_access_token`'s docstring (generator `:1472-1479`) records a
hard dependency on fastmcp internals:

    the swapped AccessToken's `claims` are stripped to
    {sub, username, cognito:groups} by AWSCognitoTokenVerifier, so the
    downstream client_id binding check passes only via the
    `AccessToken.client_id` ATTRIBUTE

The check itself reads:

    token_client_id = claims.get("client_id") or getattr(
        access_token, "client_id", None
    )

In production the left operand is `None`, so the `getattr` is the thing keeping
auth working. Every pre-existing stub, though, sets `client_id` in **both**
places (`tests/conftest.py:124-125`, `tests/test_token_reswap.py:25-26`), and
`or` short-circuits — so before this file the attribute path had **zero**
coverage. A fastmcp upgrade that stopped forwarding the attribute would have
shipped green and reached users as "Invalid client_id" on every tool call.

`test_claims_take_precedence_over_the_attribute` below is the demonstration of
that blind spot: it passes *because* `claims` short-circuits, which is precisely
why the older stubs never reached the `getattr`.

There are TWO independent copies of the check — the text-tool path in
`subscription_required` (returns an error string) and the structured-tool path
(raises `AuthenticationError`). Both are covered here; a regression in either is
a production outage.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

# What AWSCognitoTokenVerifier actually leaves in `claims` after the swap.
# Note the absence of `client_id` — that is the whole point.
_COGNITO_STRIPPED_CLAIMS = {
    "sub": "cognito-sub-12345678",
    "username": "analyst@example.invalid",
    "cognito:groups": ["fr-users"],
}


class _StrippedClaimsToken:
    """AccessToken shaped the way production Cognito hands it over: `client_id`
    on the attribute only, never in `claims`."""

    def __init__(self, client_id: str | None = TEST_CLIENT_ID) -> None:
        self.token = "real-access-token"
        self.client_id = client_id
        self.claims = dict(_COGNITO_STRIPPED_CLAIMS)


def _structured_tool(mcp_module, name: str = "companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _text_tool(mcp_module, name: str = "filing_types_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


# ---------------------------------------------------------------------------
# Positive: attribute-only binding must be accepted.
#
# These two fail if the `getattr` fallback is ever dropped: `claims` carries no
# `client_id`, so the left operand is None and only the fallback can satisfy the
# comparison against COGNITO_CLIENT_ID.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_structured_path_accepts_client_id_from_the_attribute(
    mcp_module, monkeypatch, respx_router
) -> None:
    monkeypatch.setattr(
        mcp_module, "get_access_token", lambda: _StrippedClaimsToken()
    )
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    out = await _structured_tool(mcp_module)()

    assert out == {"count": 0, "results": []}


@pytest.mark.asyncio
async def test_text_path_accepts_client_id_from_the_attribute(
    mcp_module, monkeypatch, respx_router
) -> None:
    monkeypatch.setattr(
        mcp_module, "get_access_token", lambda: _StrippedClaimsToken()
    )
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    out = await _text_tool(mcp_module)()

    assert "```json" in out
    assert "Invalid client_id" not in out


# ---------------------------------------------------------------------------
# Negative: neither source present must fail closed.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_structured_path_rejects_when_client_id_is_absent_everywhere(
    mcp_module, monkeypatch, respx_router
) -> None:
    monkeypatch.setattr(
        mcp_module,
        "get_access_token",
        lambda: _StrippedClaimsToken(client_id=None),
    )
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    with pytest.raises(mcp_module.AuthenticationError) as ei:
        await _structured_tool(mcp_module)()

    assert "client_id" in str(ei.value)
    # Fail closed: the upstream must never be called with an unbound token.
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_text_path_rejects_when_client_id_is_absent_everywhere(
    mcp_module, monkeypatch, respx_router
) -> None:
    monkeypatch.setattr(
        mcp_module,
        "get_access_token",
        lambda: _StrippedClaimsToken(client_id=None),
    )
    route = respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    out = await _text_tool(mcp_module)()

    assert "Invalid client_id" in out
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_a_wrong_client_id_on_the_attribute_is_rejected(
    mcp_module, monkeypatch, respx_router
) -> None:
    """Cross-app-client replay defence still holds on the attribute path."""
    monkeypatch.setattr(
        mcp_module,
        "get_access_token",
        lambda: _StrippedClaimsToken(client_id="some_other_app_client"),
    )
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    with pytest.raises(mcp_module.AuthenticationError):
        await _structured_tool(mcp_module)()
    assert route.call_count == 0


# ---------------------------------------------------------------------------
# Precedence — and the proof that the older stubs are blind to the attribute.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claims_take_precedence_over_the_attribute(
    mcp_module, monkeypatch, respx_router
) -> None:
    """`claims["client_id"]` wins; the attribute is only a fallback.

    This is also the demonstration of why every stub written before this file
    left the `getattr` untested: a correct value in `claims` short-circuits the
    `or`, so even a deliberately wrong attribute value cannot fail the check.
    """

    class _BothSet:
        def __init__(self) -> None:
            self.token = "real-access-token"
            self.client_id = "WRONG-attribute-value"
            self.claims = {
                "sub": "cognito-sub-12345678",
                "client_id": TEST_CLIENT_ID,
            }

    monkeypatch.setattr(mcp_module, "get_access_token", lambda: _BothSet())
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    out = await _structured_tool(mcp_module)()

    assert out == {"count": 0, "results": []}
