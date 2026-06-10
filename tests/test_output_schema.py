"""Structured-output tools (output_schema declared).

Covers the auth flow that differs from `subscription_required` — these
tools must raise `AuthenticationError` on failure rather than return
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
    tool = mcp_module.mcp._tool_manager._tools.get(tool_name)
    assert tool is not None, f"{tool_name} not registered"
    schema = tool.output_schema
    assert schema, f"{tool_name} has no output_schema"
    assert isinstance(schema, dict)
    assert (
        "type" in schema
        or "properties" in schema
        or "$defs" in schema
        or "$ref" in schema
    )


def test_unstructured_tools_only_get_fastmcp_default_wrapper(mcp_module) -> None:
    tm = mcp_module.mcp._tool_manager
    for name in ("filing_types_list", "filing_categories_list", "isins_retrieve"):
        tool = tm._tools.get(name)
        assert tool is not None
        schema = tool.output_schema or {}
        assert schema.get("x-fastmcp-wrap-result") is True, (
            f"{name} schema unexpectedly looks structured: {schema!r}"
        )


@pytest.mark.parametrize("tool_name", STRUCTURED_TOOL_NAMES)
def test_structured_tools_are_NOT_fastmcp_default_wrapper(mcp_module, tool_name) -> None:
    tool = mcp_module.mcp._tool_manager._tools[tool_name]
    schema = tool.output_schema or {}
    assert (
        schema.get("x-fastmcp-wrap-result") is not True
    ), f"{tool_name} fell back to FastMCP auto-wrap; output_schema render likely failed"


def test_authentication_error_exists(mcp_module) -> None:
    assert issubclass(mcp_module.AuthenticationError, RuntimeError)


def test_authorize_or_raise_exists_and_has_release(mcp_module) -> None:
    assert callable(mcp_module._authorize_or_raise)
    assert callable(mcp_module._release_auth_context)


def _underlying_callable(tool):
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


@pytest.mark.asyncio
async def test_structured_tool_returns_dict_on_success(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

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
    assert fn is not None

    out = await fn()
    assert isinstance(out, dict)
    assert out == payload


@pytest.mark.asyncio
async def test_structured_tool_raises_on_foreign_client_id(
    mcp_module, monkeypatch, fake_access_token
) -> None:
    at = fake_access_token(client_id="foreign-client-id")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    with pytest.raises(mcp_module.AuthenticationError):
        await fn()


@pytest.mark.asyncio
async def test_structured_tool_releases_context_on_error(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(503, text="upstream blip")
    )

    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    fn = _underlying_callable(tool)
    with pytest.raises(RuntimeError):
        await fn()

    assert mcp_module._current_token.get() == ""


def test_structured_tool_input_schema_still_valid(mcp_module) -> None:
    tool = mcp_module.mcp._tool_manager._tools["companies_list"]
    assert tool.parameters
    assert tool.output_schema
