"""Guidance for the argument errors prod MCP traffic actually produces.

Measured on customer `users_mcptoolevent` rows, 2026-11-13 -> 11-26, still
arriving on v1.4.211-213:

- 142 `filings_list` 400s: a regulator form name as a filing-type code (10-Q 98,
  8-K 27, 6-K 8, 20-F 7).
- 88 `companies_financials_retrieve` 400s: guessed `line_items` codes.
- ~80 calls refused for an argument name the tool does not take: `id` on
  `filings_markdown_retrieve`, `filing_id` on `filings_retrieve`,
  `companies`/`company_id`/`fiscal_year_from` on `filings_list`.
- 24 `filings_search` refusals: no `queries`, or `ordering` with `group_by`.

Every name the new text TELLS a model to send is checked against the real
signature, and every name it tells a model NOT to send is checked to be absent:
guidance naming a parameter that does not exist would manufacture the error it
is meant to stop.
"""
from __future__ import annotations

import json
import os

import pytest


def _tool(mcp_module, name):
    return mcp_module.mcp._tool_manager._tools[name]


def _props(mcp_module, name):
    return _tool(mcp_module, name).parameters["properties"]


def _generator():
    import importlib
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    return importlib.import_module("generate_mcp_tools")


@pytest.mark.parametrize("param", ["type", "types"])
def test_form_name_mapping_leads_the_type_params(mcp_module, param) -> None:
    desc = _props(mcp_module, "filings_list")[param].get("description", "")
    # FIRST, where the cap cannot reach it.
    assert desc.startswith("Form names are not codes"), desc
    for must in ("10-Q -> `IR`", "20-F -> `10-K`", "8-K", "`source_filing_type`"):
        assert must in desc, f"{param} lost {must!r}: {desc!r}"


def test_the_form_name_lead_agrees_with_the_server_instructions() -> None:
    """ANTI-ROT. The codes are not in the schema snapshot, so the lead is pinned
    to the instructions' own mapping: a change to one without the other fails
    here instead of shipping two contradictory instructions."""
    gen = _generator()
    src = open(gen.__file__, encoding="utf-8").read()
    assert "10-Q -> IR, 20-F -> 10-K" in src, "the instructions' mapping changed"
    assert "10-Q -> `IR`, 20-F -> `10-K`" in gen._FORM_NAME_LEAD


def test_upstream_still_sends_form_names_to_source_filing_type() -> None:
    """The lead repeats upstream's cross-reference because the cap now cuts
    upstream's copy. If upstream drops the distinction, re-read it."""
    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    params = {p["name"]: p for p in snap["paths"]["/filings/"]["get"]["parameters"]}
    for name in ("type", "types"):
        assert "source_filing_type" in (params[name].get("description") or ""), name
    assert "exact" in (params["source_filing_type"].get("description") or "").lower()


@pytest.mark.parametrize(
    "tool,takes,not_takes",
    [
        ("filings_retrieve", ["id"], ["filing_id"]),
        ("filings_markdown_retrieve", ["filing_id", "offset", "limit"],
         ["id", "start", "end", "length", "max_chars"]),
        ("filings_markdown_search", ["filing_id", "query"], ["id", "queries", "q"]),
        ("filings_list", ["company", "page_size", "fiscal_year",
                          "period_ending_date_from"],
         ["companies", "company_id", "limit", "fiscal_year_from", "fiscal_year_to",
          "ticker", "cik"]),
    ],
)
def test_argument_names_in_the_guidance_match_the_signature(
    mcp_module, tool, takes, not_takes
) -> None:
    props = _props(mcp_module, tool)
    desc = _tool(mcp_module, tool).description or ""
    for name in takes:
        assert name in props, f"{tool} guidance names `{name}` but the tool does not take it"
        assert f"`{name}`" in desc, f"{tool} description does not name `{name}`"
    for name in not_takes:
        assert name not in props, f"{tool} now takes `{name}`: the 'not' guidance is wrong"


def test_financials_fallback_does_not_suggest_a_form_name_as_a_type(mcp_module) -> None:
    """The fallback told a model to filter by `20-F` — a form name `filings_list`
    rejects (7 of the 142 400s)."""
    desc = _tool(mcp_module, "companies_financials_retrieve").description or ""
    assert "type='10-K'" in desc
    assert "e.g. 10-K, 20-F" not in desc


def test_financials_names_the_measured_line_item_misses(mcp_module) -> None:
    desc = " ".join((_tool(mcp_module, "companies_financials_retrieve").description or "").split())
    for wrong, right in [
        ("income_tax_expense", "income_tax_expense_benefit"),
        ("pretax_income", "earnings_before_tax_including_unusual_items"),
        ("net_income_common", "net_income_to_common_including_extra_items"),
        ("operating_profit", "operating_income_loss"),
        ("net_cash_from_operating_activities", "cash_from_operations"),
        ("stock_based_compensation", "stock_based_compensation_cf"),
        ("inventories", "inventory"),
    ]:
        assert f"{wrong} -> {right}" in desc, (wrong, right)
    assert "line_item_definitions_list" not in desc, "not on the default surface"


def test_filings_search_states_queries_is_required_and_group_by_refuses_ordering(
    mcp_module,
) -> None:
    desc = " ".join((_tool(mcp_module, "filings_search").description or "").split())
    assert "`queries` (REQUIRED)" in desc
    assert "filings_list(company=<id>)" in desc
    assert "do not pass `ordering` with it" in desc
