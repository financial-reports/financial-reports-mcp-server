"""Tool-surface redesign coverage: the pruned default surface, the guide tools,
the huge-filing search tool, and the sourcing/anti-fabrication guidance.

These assert the default (pruned) surface. MCP_FULL_SURFACE=1 restores the full
~42-tool surface; that path is exercised by generating with the env var set.
"""
from __future__ import annotations

import pytest


def test_pruned_default_surface(mcp_module) -> None:
    """Cold reference / ISIC hierarchy / webhooks / watchlist tools are dropped
    from the default surface; the core tools stay."""
    tools = mcp_module.mcp._tool_manager._tools
    for gone in (
        "countries_list", "languages_list", "filings_history_retrieve",
        "isic_sections_list", "isic_classes_list",
        "webhooks_list", "watchlist_retrieve",
    ):
        assert gone not in tools, f"{gone} should be pruned from the default surface"
    for kept in (
        "companies_list", "companies_financials_retrieve",
        "filings_list", "filings_markdown_retrieve", "filing_types_list",
    ):
        assert kept in tools, f"{kept} must stay on the default surface"


def test_guide_tools_and_nav_search_present(mcp_module) -> None:
    """The guide tools (standing in for the dropped ISIC/reference tools, for
    tool-only clients) and the huge-filing search tool are on the default surface."""
    tools = mcp_module.mcp._tool_manager._tools
    for name in (
        "get_fr_filing_type_taxonomy",
        "get_fr_industry_classification_isic",
        "get_fr_markdown_fetch_strategy",
        "filings_markdown_search",
    ):
        assert name in tools, f"{name} should be on the default (redesigned) surface"


def test_financials_sourcing_guidance(mcp_module) -> None:
    """The anti-fabrication / groundedness discipline is merged into the
    figure-bearing tool's description."""
    fin = mcp_module.mcp._tool_manager._tools.get("companies_financials_retrieve")
    assert fin is not None
    desc = fin.description or ""
    assert "NO structured financials" in desc or "GROUNDEDNESS" in desc, (
        "sourcing/anti-fabrication guidance missing from financials description"
    )


@pytest.mark.asyncio
async def test_guide_tools_return_content(mcp_module) -> None:
    """The guide tools must RETURN their resource content when CALLED — not just
    be registered. Regression guard for the first cut, which shipped
    `return _resource_x()` where `_resource_x` is a FastMCP FunctionResource (not
    callable) — every invocation raised "'FunctionResource' object is not
    callable" in prod. The fix calls `_resource_x.fn()`; this test exercises it."""
    tools = mcp_module.mcp._tool_manager._tools
    for name in (
        "get_fr_filing_type_taxonomy",
        "get_fr_industry_classification_isic",
        "get_fr_markdown_fetch_strategy",
    ):
        out = await tools[name].fn()
        assert isinstance(out, str) and len(out) > 100, f"{name} returned no content"
        assert "FunctionResource" not in out, f"{name} leaked a FunctionResource error"
