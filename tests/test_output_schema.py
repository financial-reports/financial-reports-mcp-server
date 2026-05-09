"""Structured-output tools (output_schema declared).

Covers the auth flow that differs from `subscription_required` — these
tools must raise `SubscriptionGateError` on failure rather than return
markdown, because markdown can't conform to the declared JSON Schema
and FastMCP would surface a server error instead of a tool error.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


# Tools we promoted to structured output. Keep this list in sync with
# `STRUCTURED_OUTPUT_TOOLS` in scripts/generate_mcp_tools.py.
STRUCTURED_TOOL_NAMES = [
    "companies_list",
    "companies_retrieve",
    "companies_financials_retrieve",
    "filings_list",
    "filings_retrieve",
    "isins_list",
]


@pytest.mark.parametrize("tool_name", STRUCTURED_TOOL_NAMES)
def test_structured_tool_advertises_output_schema(mcp_module, tool_name) -> None:
    """Every structured tool must carry a non-empty `output_schema` so
    FastMCP advertises it on /mcp `tools/list`."""
    tool = mcp_module.mcp._tool_manager._tools.get(tool_name)
    assert tool is not None, f"{tool_name} not registered"
    schema = tool.output_schema
    assert schema, f"{tool_name} has no output_schema"
    assert isinstance(schema, dict)
    # Top-level keys we expect for an inlined OpenAPI response schema.
    assert (
        "type" in schema
        or "properties" in schema
        or "$defs" in schema
        or "$ref" in schema
    )


def test_unstructured_tools_only_get_fastmcp_default_wrapper(mcp_module) -> None:
    """Tools we did NOT promote return `str`. FastMCP auto-wraps that as
    `{"type": "object", "properties": {"result": {"type": "string"}}, "x-fastmcp-wrap-result": True}`,
    which is the right thing for a markdown-returning tool — the wrapper
    is what tells FastMCP to box the string in a `result` field rather
    than failing schema validation.

    The contract we care about: structured tools get *richer* schemas
    (no `x-fastmcp-wrap-result`), unstructured tools get only the
    auto-wrap. This regression-guards against accidentally promoting a
    tool to STRUCTURED_OUTPUT_TOOLS without giving it the matching
    return-type and template change.
    """
    tm = mcp_module.mcp._tool_manager
    for name in ("countries_list", "filing_types_list", "languages_list"):
        tool = tm._tools.get(name)
        assert tool is not None
        schema = tool.output_schema or {}
        # Auto-wrap marker is the giveaway that it's the FastMCP default.
        assert schema.get("x-fastmcp-wrap-result") is True, (
            f"{name} schema unexpectedly looks structured: {schema!r}"
        )


@pytest.mark.parametrize("tool_name", STRUCTURED_TOOL_NAMES)
def test_structured_tools_are_NOT_fastmcp_default_wrapper(mcp_module, tool_name) -> None:
    """The opposite of the test above — confirm our promoted tools have
    a real OpenAPI-derived schema, not the auto-wrap marker."""
    tool = mcp_module.mcp._tool_manager._tools[tool_name]
    schema = tool.output_schema or {}
    assert (
        schema.get("x-fastmcp-wrap-result") is not True
    ), f"{tool_name} fell back to FastMCP auto-wrap; output_schema render likely failed"


def test_subscription_gate_error_exists(mcp_module) -> None:
    assert issubclass(mcp_module.SubscriptionGateError, RuntimeError)


def test_authorize_or_raise_exists_and_has_release(mcp_module) -> None:
    assert callable(mcp_module._authorize_or_raise)
    assert callable(mcp_module._release_auth_context)


def _underlying_callable(tool):
    """Pull the real coroutine fn out of the FunctionTool wrapper.
    FastMCP stores it on `.fn` in 2.13.x."""
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


@pytest.mark.asyncio
async def test_structured_tool_returns_dict_on_success(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {"authorized": True, "plan": "analyst", "user_id": 1}

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    payload = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [{"id": 1, "name": "Test Co"}, {"id": 2, "name": "Other Co"}],
    }
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    assert fn is not None, "couldn't find underlying function on FunctionTool"

    out = await fn()
    assert isinstance(out, dict)
    assert out == payload


@pytest.mark.asyncio
async def test_structured_tool_raises_on_unauthorized(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    """Free-tier user calling a structured tool: the wrapper raises
    SubscriptionGateError carrying the upgrade markdown. FastMCP turns
    that into a tool error — the LLM sees the message in `content`
    with `isError: true`."""
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {
            "authorized": False,
            "reason": "subscription_required",
            "upgrade_url": "https://promo.example/upgrade",
        }

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    with pytest.raises(mcp_module.SubscriptionGateError) as exc_info:
        await fn()
    msg = str(exc_info.value)
    assert "subscription required" in msg.lower()
    assert "promo.example/upgrade" in msg


@pytest.mark.asyncio
async def test_structured_tool_raises_on_foreign_client_id(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    """Cross-app-client token replay must fail closed even on structured
    tools (they go through `_authorize_or_raise`, which performs the
    same client_id validation as `subscription_required`)."""
    at = fake_access_token(client_id="foreign-client-id")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    with pytest.raises(mcp_module.SubscriptionGateError):
        await fn()


@pytest.mark.asyncio
async def test_structured_tool_releases_context_on_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Even if the upstream HTTP call raises, the contextvars must be
    released — otherwise the next request from the same task sees the
    leaked token."""
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    async def fake_check(token, sub):
        return {"authorized": True}

    monkeypatch.setattr(mcp_module, "_check_subscription", fake_check)

    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(503, text="upstream blip")
    )

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    with pytest.raises(RuntimeError):
        await fn()

    assert mcp_module._current_token.get() == ""
    assert mcp_module._current_user.get() == {}


def test_structured_tool_input_schema_still_valid(mcp_module) -> None:
    """Structured tools must keep their inputSchema. Regression guard for
    refactors that accidentally drop one or the other."""
    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    assert tool.parameters
    assert tool.output_schema
