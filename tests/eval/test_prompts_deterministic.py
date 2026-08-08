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

# Resource URI → set of substrings the resource body must contain.
# Add a row here whenever a new @mcp.resource() lands.
EXPECTED_RESOURCES: dict[str, set[str]] = {
    "fr://guide/filing-types": {"10-K", "10-K-ESEF", "IR", "ER", "DIRS", "SR", "filing_types_list"},
    "fr://guide/industry-classification": {"4 levels", "isic_class", "Peer", "companies_list"},
    "fr://guide/markdown-strategy": {"processing_status", "COMPLETED", "filings_markdown_retrieve"},
}


# Sample arguments for rendering each prompt. The Prompts have required
# arguments; FastMCP raises if any are missing at render time, so we
# provide synthetic-but-realistic values. The actual values don't matter
# for the assertion (we check for literal tool names in the rendered text),
# but they have to satisfy the schema.
#
# Every value here is a STRING on purpose. MCP transports prompt arguments as
# `map[string]string`, so passing natively-typed Python values (2024, not
# "2024") skips FastMCP's `_convert_string_arguments` entirely — which is
# exactly how #93 stayed invisible through four server versions while failing
# in production.
SAMPLE_ARGS: dict[str, dict[str, object]] = {
    "compare_financials_yoy": {
        "ticker_or_name": "AAPL",
        "current_fiscal_year": "2024",
        "prior_fiscal_year": "2023",
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

# Argument sets recovered from (or directly modelled on) real production
# traffic. The '', '$2', free-text and double-encoded-JSON values below are
# the literal inputs pulled from Cloud Run tracebacks while root-causing #93 —
# clients really do send these. Rendering must never raise on any of them.
WIRE_ARGS: dict[str, list[dict[str, object]]] = {
    "compare_financials_yoy": [
        {"ticker_or_name": "AAPL", "current_fiscal_year": "2024", "prior_fiscal_year": "2023"},
        {"ticker_or_name": "AAPL", "current_fiscal_year": "", "prior_fiscal_year": ""},
        {"ticker_or_name": "AAPL", "current_fiscal_year": "FY2024", "prior_fiscal_year": "FY2023"},
        # Free text landing in what used to be an int field.
        {
            "ticker_or_name": "AAPL",
            "current_fiscal_year": "Revenue, FFO, and EV/EBITDA",
            "prior_fiscal_year": "2023",
        },
    ],
    "find_filing_section": [
        {"ticker_or_name": "AAPL", "filing_type": "10-K", "section_keyword": "supply chain"},
    ],
    "summarize_recent_filings": [
        {"ticker_or_name": "AAPL", "lookback_days": "90"},
        {"ticker_or_name": "AAPL", "lookback_days": ""},
        {"ticker_or_name": "AAPL", "lookback_days": "90 days"},
        # Unsubstituted positional placeholder from a client-side template.
        {"ticker_or_name": "AAPL", "lookback_days": "$2"},
        # Client double-encoded the whole arguments object into one value.
        {"ticker_or_name": "AAPL", "lookback_days": '{"lookback_days": 30}'},
        # Explicit JSON null — reached the body and raised TypeError from timedelta.
        {"ticker_or_name": "AAPL", "lookback_days": None},
    ],
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


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_name", sorted(WIRE_ARGS))
async def test_prompts_render_from_wire_string_arguments(
    mcp_module, prompt_name: str
) -> None:
    """Rendering must survive every argument shape a real client sends (#93).

    MCP delivers prompt arguments as strings. A non-`str` annotation routes
    them through FastMCP's pydantic coercion, which hard-raises on anything
    non-numeric and then masks the cause as "Error rendering prompt <name>."
    — a dead end for the user and a dead end in telemetry.
    """
    prompts = await mcp_module.mcp.get_prompts()
    prompt = prompts[prompt_name]
    for args in WIRE_ARGS[prompt_name]:
        messages = await prompt.render(arguments=args)
        assert messages, f"{prompt_name} rendered nothing for {args!r}"


@pytest.mark.asyncio
async def test_no_prompt_declares_a_non_string_argument(mcp_module) -> None:
    """Structural guard for the whole #93 class, not just the two known cases.

    FastMCP stamps a "Provide as a JSON string matching..." description onto
    any prompt argument whose annotation is not `str`, because it then has to
    coerce the incoming string via pydantic. That marker is the tell. Keeping
    prompt arguments `str` and parsing in the body is the only shape that
    cannot fail at the framework boundary.
    """
    prompts = await mcp_module.mcp.get_prompts()
    offenders = [
        f"{name}.{arg.name}"
        for name, prompt in prompts.items()
        for arg in (prompt.arguments or [])
        if (arg.description or "").startswith("Provide as a JSON string matching")
    ]
    assert not offenders, (
        "MCP prompt arguments arrive as strings; annotate them `str` and parse "
        f"in the body instead. Non-`str` arguments: {offenders}"
    )


@pytest.mark.asyncio
async def test_all_expected_resources_registered(mcp_module) -> None:
    """Every URI in EXPECTED_RESOURCES must be exposed via resources/list."""
    resources = await mcp_module.mcp.get_resources()
    registered = set(resources.keys())
    missing = set(EXPECTED_RESOURCES) - registered
    assert not missing, f"Missing resources: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("uri,must_contain", list(EXPECTED_RESOURCES.items()))
async def test_resource_body_contains_expected_substrings(
    mcp_module, uri: str, must_contain: set[str]
) -> None:
    """Each resource body must contain the substrings the agent relies on."""
    resources = await mcp_module.mcp.get_resources()
    res = resources[uri]
    body = await res.read()
    if isinstance(body, (list, tuple)):
        # Some FastMCP versions return a list of content parts; concatenate.
        body = " ".join(
            getattr(part, "text", str(part)) for part in body
        )
    missing = [s for s in must_contain if s not in body]
    assert not missing, f"{uri}: missing substrings {missing}"
