"""The filing-type guide must not contradict the tool that links to it.

HISTORY, because this file's premise inverted under it and the inversion is the
point. It was written on 2026-11-12 from live telemetry: 2.7 days of
`filings_search`, 96 calls, 13 errors, of which four were 400s from an agent
putting a SEC form name in `types` (`S-1`, `13F-HR`, `424B5`, `EC`). The fix
was a warning that `types` takes FinancialFilings codes and not form names.

**#204 then made form names ACCEPTED on `filings_search`** — a regulator form
name is mapped to the type(s) its filings are filed under, and the response
says how. So the warning this file was built to enforce became FALSE for the
tool it was aimed at, and asserting it would have steered models away from a
route that now works.

What survives is the half that got bigger. `get_fr_filing_type_taxonomy` still
says, in its own words, that `type=10-Q` "is not a code" and "an unknown code
is rejected with a 400" — true of `filings_list`, whose filter is an exact
`code IN (...)`, and FALSE of `filings_search` since #204. The guide is linked
from both. So these pin the SPLIT rather than either rule:

  * `filings_list`  — a non-code form name is REJECTED
  * `filings_search` — a form name is ACCEPTED and mapped, and the result says
                       how; but it has no `search=` and no `source_filing_type`,
                       so you can narrow and cannot confirm

A reader who carries either rule across gets a wrong answer in one direction or
the other, which is why the guide now states both.
"""
from __future__ import annotations

import inspect

TAXONOMY_TOOL = "get_fr_filing_type_taxonomy"


def _description(mcp_module, name: str) -> str:
    return mcp_module.mcp._tool_manager._tools[name].description or ""


def _guide(mcp_module) -> str:
    return mcp_module._resource_filing_types.fn()


def _guide_header(mcp_module) -> str:
    """The guide ABOVE its code table — where the caveats have to live.

    Scoped deliberately: an assertion over the whole guide passes on wording
    that sits below the table, which a model reading the caveats will not have
    reached.
    """
    text = _guide(mcp_module)
    header, _, _ = text.partition("| Code | Name | Category |")
    assert header, "the taxonomy guide lost its code table"
    return header


def test_the_guide_states_the_filings_list_rejection_rule(mcp_module) -> None:
    """The original claim, kept — it is still true of `filings_list`."""
    header = _guide_header(mcp_module)
    assert "REJECTED" in header or "rejected" in header
    assert "filings_list" in header


def test_the_guide_states_that_filings_search_ACCEPTS_form_names(mcp_module) -> None:
    """The half #204 inverted.

    Without this, the guide tells a model a form name will be refused by a tool
    that in fact maps it — a false absence manufactured by documentation.
    """
    header = _guide_header(mcp_module)
    assert "ACCEPTED" in header, (
        "the guide no longer says `filings_search` accepts form names; since "
        "#204 it does, and the guide is linked from that tool"
    )
    assert "filings_search" in header


def test_the_guide_and_the_tool_do_not_contradict_each_other(mcp_module) -> None:
    """The actual regression this file exists to prevent.

    `filings_search`'s own description says a form name is accepted. The guide
    it points at must not be readable as saying the opposite. Both strings are
    derived here rather than restated, so a later edit to either one is caught.
    """
    clause = _description(mcp_module, "filings_search")
    assert "form name" in clause, (
        "filings_search no longer documents form-name handling; if #204 was "
        "reverted, this whole file's premise needs re-deriving"
    )
    assert "accepted" in clause.lower()

    header = _guide_header(mcp_module)
    # The guide must carry the same fact, not merely avoid denying it.
    assert "ACCEPTED" in header and "filings_search" in header


def test_the_guide_keeps_the_confirm_limitation_on_filings_search(mcp_module) -> None:
    """The direction that did NOT invert, and still bites.

    `filings_search` takes no `search=` and its rows carry the filing-type code,
    not `source_filing_type`. So the guide's form-verification recipes remain
    `filings_list`-only even though its rejection rule no longer applies.
    """
    header = _guide_header(mcp_module)
    assert "source_filing_type" in header
    assert "filings_list` ONLY" in header or "filings_list` only" in header


def test_the_scoping_claims_still_match_the_tool_signatures(mcp_module) -> None:
    """Pin the guide's claims about another tool's interface to that interface.

    Prose about a sibling tool rots silently, and this guide is where a model is
    told to trust it. Includes the contrast control, since the claim is a
    contrast.
    """
    search_params = set(inspect.signature(mcp_module.filings_search.fn).parameters)
    list_params = set(inspect.signature(mcp_module.filings_list.fn).parameters)

    assert "search" not in search_params, (
        "filings_search grew a `search` parameter — the guide says it has none"
    )
    assert "types" in search_params
    assert "search" in list_params, (
        "filings_list lost `search` — the guide's recipes are written for it"
    )


def test_the_taxonomy_tool_is_on_the_default_surface(mcp_module) -> None:
    """A pointer to a pruned tool is worse than no pointer."""
    assert TAXONOMY_TOOL in mcp_module.mcp._tool_manager._tools
