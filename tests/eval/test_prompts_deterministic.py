"""Deterministic eval: every registered Prompt must surface the tools we
expect when called with documented arguments. No live LLM needed.

This is the fast, CI-friendly half of the eval harness. The LLM-based
golden-query suite (queries.yaml + mcp-eval) is the slower nightly half.
"""
from __future__ import annotations

import pytest


EXPECTED_PROMPTS: dict[str, set[str]] = {
    # Filled in as prompts are registered in Phase 5.
    # "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
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
    # Render with the prompt's own default arguments where possible.
    result = await prompt.render(arguments={})
    rendered = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in result.messages
    )
    missing = [t for t in expected_tools if t not in rendered]
    assert not missing, f"{prompt_name}: missing tool references {missing}"
