"""Tool-surface redesign coverage: the pruned default surface, the guide tools,
the huge-filing search tool, and the sourcing/anti-fabrication guidance.

These assert the default (pruned) surface. MCP_FULL_SURFACE=1 restores the full
53-tool surface; that path is exercised by generating with the env var set.
"""
from __future__ import annotations

import pytest


def test_pruned_default_surface(mcp_module) -> None:
    """Cold reference / ISIC hierarchy / webhooks / watchlist tools are dropped
    from the default surface; the core tools stay.

    The corporate-actions trio is here because `_PRUNED_EXCLUDE` is a DENYLIST:
    an upstream endpoint joins the LLM-facing surface the moment the snapshot is
    refreshed unless something stops it. Before #154 nothing asserted the newer
    entries, so deleting one would have silently promoted a 40-credit
    experimental tool and no test would have said so."""
    tools = mcp_module.mcp._tool_manager._tools
    for gone in (
        "countries_list", "languages_list", "filings_history_retrieve",
        "isic_sections_list", "isic_classes_list",
        "webhooks_list", "watchlist_retrieve",
        # #154, 2026-10-30: 40 credits each and all three self-described
        # "Experimental: the response may change without an API version bump".
        "companies_segments_retrieve", "companies_splits_retrieve",
        "companies_dividends_retrieve",
        # #149/#156 entries, likewise previously unasserted.
        "agent_key_claim", "agent_signup", "filings_document_retrieve",
    ):
        assert gone not in tools, f"{gone} should be pruned from the default surface"
    for kept in (
        "companies_list", "companies_financials_retrieve",
        "filings_list", "filings_markdown_retrieve", "filing_types_list",
        "usage_retrieve",
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
    # Since web#3031 (2026-09-18) a wrong code is a 400 naming it, not a
    # silent empty list; the instructions must say what actually happens (#132).
    assert "an unknown code is rejected with a 400" in text
    assert "EMPTY LIST" not in text


def test_filing_type_guide_carries_the_translation_table(mcp_module) -> None:
    guide = mcp_module._resource_filing_types.fn()
    assert "SEC form names are NOT codes" in guide
    for form in ("10-Q", "20-F", "Form 4", "DEF 14A", "8-K"):
        assert form in guide, f"{form} missing from the translation table"
    # 8-K has no single target: 28 codes over 180d. Guessing one is the error.
    assert "no single code" in guide or "28 codes" in guide


def test_guide_pairs_the_code_with_a_title_search_for_form_exact_asks(mcp_module) -> None:
    """A taxonomy code is BROADER than the SEC form: `type=IR` alone returns the
    8% of IR that is 6-K/424B3, so reporting it as "the 10-Qs" is wrong. `search`
    covers the filing title, and 94% of SEC 10-Q titles name the form.
    """
    guide = mcp_module._resource_filing_types.fn()
    assert 'search="10-Q"' in guide or 'search=\\"10-Q\\"' in guide.replace('\\\\', '\\')
    assert "BROADER than the form" in guide
    # Form 4 is the exception that makes this a measurement, not a slogan.
    assert "9%" in guide and "DIRS" in guide


def test_guide_does_not_claim_dirs_is_purely_form_4(mcp_module) -> None:
    """REGRESSION (shipped wrong in #126, live at v1.4.76): the guide and the
    instructions both said "DIRS is 100% Form 4 — use the code alone there".
    That conflated RECALL (100% of Form 4 is DIRS — true) with PRECISION
    (88.6% of DIRS is Form 4 — 8.9% is Form 3, an initial-ownership snapshot
    and NOT a transaction). It was the one place the guidance told the model to
    stop qualifying, and it was the one claim that did not hold.
    """
    guide = mcp_module._resource_filing_types.fn()
    text = mcp_module.mcp.instructions
    for surface, name in ((guide, "guide"), (text, "instructions")):
        assert "100% Form 4" not in surface, f"{name} still claims DIRS is purely Form 4"
        assert "88.6%" in surface, f"{name} does not state the measured DIRS precision"
        assert "Form 3" in surface, f"{name} does not name the contaminating form"


def test_form_4_recipe_includes_amendments(mcp_module) -> None:
    """`4/A` is an AMENDED Form 4 and is 1.4% of DIRS. A `4`-only filter drops
    it silently from a request for Form 4 insider transactions."""
    guide = mcp_module._resource_filing_types.fn()
    assert 'source_filing_type in ("4", "4/A")' in guide, (
        "the Form 4 recipe must accept amendments; a 4-only filter drops them"
    )
    assert "amend" in guide.lower()


def test_both_surfaces_qualify_the_nullable_field(mcp_module) -> None:
    """`source_filing_type` is nullable (the schema: "Null when the source
    publishes no label"). Saying every row carries it tells a model it can
    confirm a form when it cannot."""
    for surface in (mcp_module._resource_filing_types.fn(), mcp_module.mcp.instructions):
        assert "null" in surface.lower()
        assert "UNCONFIRMED" in surface
    assert "Every filing row carries" not in mcp_module.mcp.instructions


def test_both_surfaces_point_at_source_filing_type(mcp_module) -> None:
    """The exact discriminator is on the row and is 99.99% populated on SEC.
    Advertised in the output schema since the 1.4.0 snapshot — but a model has
    no reason to read it unless the guidance says so.
    """
    for surface in (mcp_module._resource_filing_types.fn(), mcp_module.mcp.instructions):
        assert "source_filing_type" in surface


def test_instructions_warn_the_code_is_broader_than_the_form(mcp_module) -> None:
    text = mcp_module.mcp.instructions
    assert "BROADER than the SEC form" in text
    assert "92% 10-Q" in text


def test_guide_warns_that_def_14a_is_a_name_collision(mcp_module) -> None:
    """The dangerous one: `DEF 14A` IS a valid code, so it returns real filings
    — but SEC DEF 14A proxies are `PSI` (3,234 in 180d) while the code spelled
    `DEF 14A` holds remuneration content parsed mostly from 8-Ks (88 in 180d).
    A wrong-but-plausible result, not an empty one.
    """
    guide = mcp_module._resource_filing_types.fn()
    assert "PSI" in guide
    assert "collision" in guide.lower()


def test_markdown_search_routes_line_items_to_the_structured_path(mcp_module) -> None:
    """#167: the tool's own description told the model to use document search for
    "a specific figure, line item, or section (e.g. query='total revenue')" — and it
    obeyed. 267 of 559 users who call it have never once called
    companies_financials_retrieve, and 80% of those never have since telemetry began.
    Not reliability, not coverage, not price: the remaining explanation was our copy."""
    tool = mcp_module.mcp._tool_manager._tools["filings_markdown_search"]
    d = tool.description or ""
    assert "companies_financials_retrieve" in d, "the structured path is not named"
    assert "total revenue" not in d, "the line-item example is still here"


def test_markdown_search_keeps_the_text_fallback_REQUIRED(mcp_module) -> None:
    """cross-corpus-search's condition 1, and the thing that makes this an
    experiment rather than a wall: when structured financials has no coverage or
    comes back empty, the model must STILL be told to search the document. We are
    measuring which path it routes to, so the second path has to stay open — and an
    absent structured value is not an absent fact."""
    d = mcp_module.mcp._tool_manager._tools["filings_markdown_search"].description or ""
    low = d.lower()
    assert "empty" in low and ("come back" in low or "fall back" in low), (
        f"the fallback is not stated as required: {d!r}"
    )


def test_markdown_search_example_is_single_filing_shaped(mcp_module) -> None:
    """cross-corpus-search's condition 2: the example must be a lookup INSIDE one
    known filing, not a 'which filings mention X' discovery query — discovery stays
    reserved for the cross-corpus tool, whose demand they are separately measuring."""
    d = mcp_module.mcp._tool_manager._tools["filings_markdown_search"].description or ""
    assert "going concern" in d, f"no single-filing example: {d!r}"
    for discovery in ("which filings", "across filings", "any filing that"):
        assert discovery not in d.lower(), f"discovery-shaped example leaked in: {discovery}"


def test_batch_search_closes_the_same_line_item_door(mcp_module) -> None:
    """#167's fix only closed one door. filings_markdown_search_batch takes ONE
    query across up to 20 filings, so a line-item sweep across peers could route
    around the new copy at 20x the cost — and the release that carries #167 also
    carries #165, so both doors have to change together.

    cross-corpus-search approved widening it and amended the PREREG to count batch
    calls in the after window, so a migration from the single tool to this one
    cannot read as a win."""
    d = mcp_module.mcp._tool_manager._tools["filings_markdown_search_batch"].description or ""
    assert "companies_financials_retrieve" in d, "the structured path is not named"
    low = d.lower()
    assert "empty" in low and ("come back" in low or "fall back" in low), (
        f"the required text fallback is missing: {d!r}"
    )
    # Its example was already disclosure-shaped; widening must not break that.
    assert "disclosure" in low, f"the disclosure-shaped example was lost: {d!r}"


def test_structured_first_does_not_hijack_as_reported_questions(mcp_module) -> None:
    """SPECHT #171, 2/3 passes, and a correctness bug in my own #167 copy.

    companies_financials_retrieve selects ONE statement per fiscal year, period and
    statement type when several filings report it, so it does NOT necessarily return
    the statement from the filing you are searching. "What did THIS filing report"
    followed by structured-first can therefore answer with a later restatement
    attributed to the earlier filing — a wrong citation, not a missing one, which is
    the worse failure.

    These two tools are the filing-specific path: both take filing ids. So the
    carve-out belongs in both."""
    for name in ("filings_markdown_search", "filings_markdown_search_batch"):
        d = (mcp_module.mcp._tool_manager._tools[name].description or "").lower()
        assert "restat" in d or "particular filing" in d, (
            f"{name} does not carve out as-reported questions: {d!r}"
        )


def test_the_fallback_covers_a_refusal_not_only_an_empty_result(mcp_module) -> None:
    """The second #171 finding. My fallback enumerated its triggers — no coverage,
    empty line item — so a structured call that is REFUSED fell outside the list,
    and a model could report a figure unavailable while the document was readable.

    ⚠ SPECHT's stated premise (Markdown is Level 2, financials Level 3) is NOT
    verifiable from the pinned schema: `Level N` appears ZERO times for either
    endpoint, because the #154 refresh replaced access-level text with `Cost:`.
    Fixed on the general principle instead — ANY unanswered structured call should
    fall back, and enumerating the reasons is what caused the gap."""
    for name in ("filings_markdown_search", "filings_markdown_search_batch"):
        d = (mcp_module.mcp._tool_manager._tools[name].description or "").lower()
        assert "refus" in d or "denied" in d or "not available to your plan" in d, (
            f"{name}'s fallback still excludes a refused call: {d!r}"
        )
