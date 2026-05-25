"""Deterministic eval: every registered Prompt must surface the tools we
expect when called with documented arguments. No live LLM needed.

This is the fast, CI-friendly half of the eval harness. The LLM-based
golden-query suite lives in the sibling repo `financial-reports/mcp-evals`.
"""
from __future__ import annotations

import pytest


# Prompt name → set of tool names that the rendered instructions must mention.
# Add a row here whenever a new @mcp.prompt() lands in scripts/generate_mcp_tools.py.
EXPECTED_PROMPTS: dict[str, set[str]] = {
    "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
    "find_filing_section": {"companies_list", "filings_list", "filings_markdown_retrieve"},
    "summarize_recent_filings": {"companies_list", "filings_list"},
}


# Sample arguments for rendering each prompt. The Prompts have required
# typed arguments; FastMCP raises if any are missing at render time, so we
# provide synthetic-but-realistic values. The actual values don't matter
# for the assertion (we check for literal tool names in the rendered text),
# but they have to satisfy the schema.
SAMPLE_ARGS: dict[str, dict[str, object]] = {
    "compare_financials_yoy": {
        "ticker_or_name": "AAPL",
        "current_fiscal_year": 2024,
        "prior_fiscal_year": 2023,
    },
    "find_filing_section": {
        "ticker_or_name": "AAPL",
        "filing_type": "10-K",
        "section_keyword": "supply chain",
    },
    "summarize_recent_filings": {
        "ticker_or_name": "AAPL",
        # lookback_days has a default; omitted intentionally to exercise the default.
    },
}


@pytest.mark.asyncio
async def test_all_expected_prompts_registered(mcp_module) -> None:
    """Every prompt in EXPECTED_PROMPTS must be exposed by the server."""
    prompts = await mcp_module.mcp.get_prompts()
    registered = set(prompts.keys())
    missing = set(EXPECTED_PROMPTS) - registered
    assert not missing, f"Missing prompts: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_name,expected_tools", list(EXPECTED_PROMPTS.items()))
async def test_prompt_messages_reference_expected_tools(
    mcp_module, prompt_name: str, expected_tools: set[str]
) -> None:
    """The messages returned by prompts/get must mention every expected tool name."""
    prompts = await mcp_module.mcp.get_prompts()
    prompt = prompts[prompt_name]
    # FastMCP 2.13.3's Prompt.render() returns the list of PromptMessage
    # objects directly (not a wrapper with a .messages attribute).
    messages = await prompt.render(arguments=SAMPLE_ARGS.get(prompt_name, {}))
    rendered = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in messages
    )
    missing = [t for t in expected_tools if t not in rendered]
    assert not missing, f"{prompt_name}: missing tool references {missing}"
