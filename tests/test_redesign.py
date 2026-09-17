"""Tool-surface redesign coverage: the pruned default surface, the guide tools,
the huge-filing search tool, and the sourcing/anti-fabrication guidance.

These assert the default (pruned) surface. MCP_FULL_SURFACE=1 restores the full
46-tool surface; that path is exercised by generating with the env var set.
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


# --- SEC form name -> FR code guidance (telemetry 2026-09-16/17) -------------
# 14 distinct users asked filings_list for `10-Q` and 7 for `8-K` in one day.
# Neither is a FilingType code, and filter_types is an exact `code IN (...)`,
# so the call returns an EMPTY LIST rather than an error — indistinguishable
# from "this company filed nothing".

def test_server_instructions_map_sec_form_names_to_codes(mcp_module) -> None:
    """The always-sent instructions must give the FORM -> CODE direction.

    They already listed `IR  Interim / Quarterly Report (10-Q, ...)`, i.e.
    code -> form: an agent holding "10-Q" has to reverse-map it. The forward
    direction is what a caller actually needs.
    """
    text = mcp_module.mcp.instructions
    assert "10-Q -> IR" in text
    assert "Form 4 -> DIRS" in text
    assert "DEF 14A proxy -> PSI" in text
    # The silence is the reason the wrong code is invisible — say so.
    assert "EMPTY LIST" in text


def test_filing_type_guide_carries_the_translation_table(mcp_module) -> None:
    guide = mcp_module._resource_filing_types.fn()
    assert "SEC form names are NOT codes" in guide
    for form in ("10-Q", "20-F", "Form 4", "DEF 14A", "8-K"):
        assert form in guide, f"{form} missing from the translation table"
    # 8-K has no single target: 28 codes over 180d. Guessing one is the error.
    assert "no single code" in guide or "28 codes" in guide


def test_guide_warns_that_def_14a_is_a_name_collision(mcp_module) -> None:
    """The dangerous one: `DEF 14A` IS a valid code, so it returns real filings
    — but SEC DEF 14A proxies are `PSI` (3,234 in 180d) while the code spelled
    `DEF 14A` holds remuneration content parsed mostly from 8-Ks (88 in 180d).
    A wrong-but-plausible result, not an empty one.
    """
    guide = mcp_module._resource_filing_types.fn()
    assert "PSI" in guide
    assert "collision" in guide.lower()
