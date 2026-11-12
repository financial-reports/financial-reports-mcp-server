"""The text every client loads must route topic questions to `filings_search`
(financial-reports/web#8004).

Measured 2026-11-01..09 over 49,542 MCP calls: `filings_search` was about 1% of
calls, and 119 users faked a corpus search by running `filings_markdown_search`
over filing after filing (1,304 such hunts, 10.9% of all calls). The tool was on
every client's surface; the text steered agents away from it. The server
instructions named it 0 times, their only discovery workflow went through
`filings_list`, core rule 1 was an unconditional "Resolve company first", and
two tool descriptions said "Don't use to search for filings — use filings_list".

These pin the routing cues, in both directions: a topic question reaches
`filings_search`, and a question about one known filing or a line item stays
where it was (over-routing is the risk the change has to keep in check).
"""
from __future__ import annotations

import re

import pytest

from .test_sourcing_disclosure_178 import CLIENT_INSTRUCTION_CAP


def _instructions(mcp_module) -> str:
    return mcp_module.mcp.instructions


def _core_rules(mcp_module) -> str:
    text = _instructions(mcp_module)
    _, _, after = text.partition("CORE RULES:")
    assert after, "the instructions lost their CORE RULES block"
    rules, _, _ = after.partition("\n\n")
    return rules


def _rule(mcp_module, n: int) -> str:
    m = re.search(rf"^{n}\. (.*)$", _core_rules(mcp_module), re.M)
    assert m, f"core rule {n} is missing"
    return m.group(1)


def _description(mcp_module, name: str) -> str:
    return mcp_module.mcp._tool_manager._tools[name].description or ""


# --- instructions -------------------------------------------------------------

def test_the_first_core_rule_routes_topic_questions_to_filings_search(mcp_module) -> None:
    rule = _rule(mcp_module, 1)
    assert "which filings or companies mention / disclose / discuss X" in rule
    assert "filings_search" in rule
    # The workflow, not just the name: translations as separate queries, then
    # the in-filing tool on the hits.
    assert "translations as separate queries, up to 5" in rule
    assert rule.index("filings_search") < rule.index("filings_markdown_search")


def test_the_topic_rule_reaches_the_model_under_the_client_cap(mcp_module) -> None:
    """Claude Code cuts instructions at 4096 characters. A routing rule past the
    cut is the same as no rule for that client, which is exactly where the old
    CANONICAL WORKFLOWS block sat (offset 4005 of 4295)."""
    delivered = _instructions(mcp_module)[:CLIENT_INSTRUCTION_CAP]
    rule = _rule(mcp_module, 1)
    assert rule in delivered, "core rule 1 is cut off by the client cap"
    assert "zh/ja/ko" in delivered


def test_the_topic_rule_names_group_by_company_for_which_companies(mcp_module) -> None:
    """ "Which companies mention X" is answered by one grouped search
    (web#10016), not by reading company names off pages of filings. Inside
    rule 1, so it sits under the client cap with the rest of the rule."""
    rule = _rule(mcp_module, 1)
    assert 'group_by="company" for companies' in rule
    assert rule.index("filings_search") < rule.index("group_by")


def test_the_topic_rule_keeps_over_routing_in_check(mcp_module) -> None:
    """One known filing stays on the in-filing search; line items stay on the
    structured financials. Without these the new rule would pull per-filing and
    per-period questions into a corpus-wide search."""
    rule = _rule(mcp_module, 1)
    assert "One known filing: filings_markdown_search" in rule
    assert "line items: companies_financials_retrieve" in rule


def test_resolve_company_first_applies_only_when_a_company_is_named(mcp_module) -> None:
    text = _instructions(mcp_module)
    assert "Resolve company first" not in text, "the unconditional rule is back"
    rule = _rule(mcp_module, 2)
    assert rule.startswith("Company named → resolve it first")
    assert "companies_list" in rule and "isins_retrieve" in rule


def test_the_instructions_tell_the_model_to_add_cjk_phrasings_when_unscoped(mcp_module) -> None:
    """0 of 24 unscoped searches used non-Latin script, and an English and a
    native "going concern" query shared 0 of their top-10 results."""
    assert "zh/ja/ko too if no country filter" in _rule(mcp_module, 1)


def test_the_first_canonical_workflow_is_the_topic_search(mcp_module) -> None:
    text = _instructions(mcp_module)
    _, _, after = text.partition("CANONICAL WORKFLOWS")
    assert after, "the instructions lost their CANONICAL WORKFLOWS block"
    lines = [ln.strip() for ln in after.splitlines()[1:] if ln.strip()]
    assert lines[0].startswith("which filings / companies mention X → filings_search")
    assert "country/type/date" in lines[0]
    assert "filings_markdown_search(filing_id, term)" in lines[0]
    # The per-company workflows say they are per-company.
    assert any(ln.startswith("named company → resolve → filings_list") for ln in lines)
    assert not any(ln.startswith("resolve → filings_list") for ln in lines)


def test_the_slash_commands_are_still_listed(mcp_module) -> None:
    """Moved past the cap to make room for rule 1, not dropped."""
    text = _instructions(mcp_module)
    for name in ("/compare_financials_yoy", "/find_filing_section", "/summarize_recent_filings"):
        assert name in text


def test_the_intro_names_topic_questions_as_a_reason_to_use_the_server(mcp_module) -> None:
    assert "asks which filings mention a topic" in _instructions(mcp_module)


# --- tool descriptions --------------------------------------------------------

def test_no_tool_says_search_for_filings_means_filings_list(mcp_module) -> None:
    """The two explicit counter-cues the analysis found."""
    for name, tool in mcp_module.mcp._tool_manager._tools.items():
        desc = (tool.description or "").replace("\n", " ")
        assert not re.search(r"search for filings\W+use `?filings_list", desc), (
            f"{name} still routes 'search for filings' to filings_list"
        )


@pytest.mark.parametrize("name", ["filings_retrieve", "filings_markdown_retrieve"])
def test_the_retrieve_tools_route_text_search_to_filings_search(mcp_module, name) -> None:
    desc = " ".join(_description(mcp_module, name).split())
    assert "To find filings by what they say, use `filings_search`; by metadata, use `filings_list`." in desc


def test_filings_list_describes_itself_as_metadata_only(mcp_module) -> None:
    desc = " ".join(_description(mcp_module, "filings_list").split())
    assert "Use to search and filter regulatory filings" not in desc
    assert "List filings by metadata" in desc
    assert "it does not read filing text" in desc
    assert "use `filings_search`" in desc


def test_the_batch_tool_no_longer_invites_a_peer_fan_out(mcp_module) -> None:
    desc = " ".join(_description(mcp_module, "filings_markdown_search_batch").split())
    assert "across peers" not in desc
    assert "a set you already hold" in desc
    assert "To find WHICH filings or companies mention it, call filings_search first" in desc


def test_filings_search_names_the_cjk_line_and_the_new_since_recipe(mcp_module) -> None:
    desc = " ".join(_description(mcp_module, "filings_search").split())
    assert "With NO country filter, also pass Chinese, Japanese and Korean phrasings" in desc
    assert "WHAT IS NEW SINCE MY LAST CHECK" in desc
    assert "added_to_platform_from" in desc and 'ordering="-added_to_platform"' in desc


# --- the find_filing_section prompt -------------------------------------------

async def _render_find_filing_section(mcp_module) -> str:
    prompts = await mcp_module.mcp.get_prompts()
    messages = await prompts["find_filing_section"].render(arguments={
        "ticker_or_name": "AAPL", "filing_type": "10-K", "section_keyword": "supply chain",
    })
    return " ".join(m.content.text for m in messages)


@pytest.mark.asyncio
async def test_find_filing_section_searches_instead_of_paging(mcp_module) -> None:
    text = await _render_find_filing_section(mcp_module)
    assert '`filings_markdown_search` with filing_id=<that id>, query="supply chain"' in text
    assert "10 calls" not in text, "the 10-call markdown_retrieve paging is back"
    assert "Do NOT page the filing from offset 0" in text
    # Reading around the hit is still how the excerpt is fetched.
    assert "`filings_markdown_retrieve`" in text


@pytest.mark.asyncio
async def test_find_filing_section_offers_the_filings_search_shortcut(mcp_module) -> None:
    text = await _render_find_filing_section(mcp_module)
    assert '`filings_search` with queries=["supply chain", <its translations>], company=<id>' in text
    assert 'ordering="-release_datetime" lists this company\'s filings' in text
    # The prompt asks for the MOST RECENT filing, so an answer from an older one
    # must say so.
    assert "say so first, then name the older filing you answered from" in text


@pytest.mark.asyncio
async def test_find_filing_section_does_not_retrieve_an_unreachable_hit(mcp_module) -> None:
    # filings_markdown_search NOTES hits past filings_markdown_retrieve's cap;
    # retrieving at such an offset returns an empty window (SPECHT on #200).
    text = await _render_find_filing_section(mcp_module)
    assert "past what filings_markdown_retrieve can reach, do not retrieve it" in text
    assert "quote the search context" in text


@pytest.mark.asyncio
async def test_find_filing_section_shortcut_does_not_decide_the_newest(mcp_module) -> None:
    # The date ordering only reorders the relevance-capped set, so the newest
    # matching filing can be outside it; filings_list (step 3) decides newest.
    text = await _render_find_filing_section(mcp_module)
    assert "newest first among its top matches by relevance" in text
    assert "It does not decide which filing is newest; step 3 does." in text


@pytest.mark.asyncio
async def test_find_filing_section_offset_never_goes_negative(mcp_module) -> None:
    # filings_markdown_retrieve rejects a negative offset; a hit near 0 minus
    # "a little" would fail the read (SPECHT on #200).
    text = await _render_find_filing_section(mcp_module)
    assert "offset=max(0, <the best hit's offset> - 200)" in text
