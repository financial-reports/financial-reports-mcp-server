"""`types` on `filings_search` takes FinancialFilings codes, not SEC form names.

Live telemetry from the `cross-corpus-search` seat, 2.7 days to 2026-11-09:
96 `filings_search` calls, 83 ok, 13 errors. Four of the thirteen were 400s
from an agent passing a SEC form name in `types` — `S-1`, `13F-HR`, `424B5`,
`EC`. None of the four is one of the 30 FinancialFilings codes, so the filter's
exact `code IN (...)` rejected the call.

The guidance that would have prevented it exists and the agent never saw it:
the `get_fr_filing_type_taxonomy` guide carries a whole "Form names are NOT
codes — translate first" section, but it introduced itself as being about the
`type` param on `filings_list`, and `filings_search`'s own description said
only "types (comma-separated filing type codes)" — a phrase a model reading it
as "the codes a filing type is called" satisfies with `10-K`, `S-1`, `13F-HR`
alike. `10-K` happens to be a real code; the other two are not, and nothing on
the call path said which was which.

These pin BOTH ends of that path, because either one alone leaves the agent
where it was: `filings_search` must send the model to the taxonomy, and the
taxonomy must admit `filings_search` is a caller.
"""
from __future__ import annotations

import pytest

TAXONOMY_TOOL = "get_fr_filing_type_taxonomy"

# Measured on origin/main 2026-11-12 against the 30-code table in
# `_resource_filing_types`: none of these is a FinancialFilings code.
NOT_FR_CODES = ("S-1", "13F-HR", "424B5", "EC")


def _description(mcp_module, name: str) -> str:
    return mcp_module.mcp._tool_manager._tools[name].description or ""


def _types_clause(mcp_module) -> str:
    """The `filings_search` sentence that documents the `types` filter.

    Scoped deliberately: an assertion over the WHOLE description passes on a
    taxonomy pointer sitting anywhere in 3k characters, including one that
    belongs to a different parameter. The fix has to land where a model reading
    about `types` will read it.
    """
    text = _description(mcp_module, "filings_search")
    start = text.find("types (")
    assert start != -1, (
        "`filings_search` no longer documents a `types` filter in the shape "
        "this test knows how to locate — re-anchor it before deleting it"
    )
    end = text.find("`max_results`", start)
    assert end > start, "the filters block lost its `max_results` terminator"
    return text[start:end]


def test_the_types_clause_sends_the_model_to_the_taxonomy(mcp_module) -> None:
    clause = _types_clause(mcp_module)
    assert TAXONOMY_TOOL in clause, (
        "the `types` clause names no way to learn the codes; the four measured "
        "400s were agents guessing"
    )


def test_the_types_clause_says_form_names_are_not_codes(mcp_module) -> None:
    """Naming the taxonomy is not enough on its own.

    A model that believes it already knows the codes has no reason to spend a
    call on a guide. The clause has to contradict the belief, not just offer a
    reference.
    """
    clause = _types_clause(mcp_module).lower()
    assert "form name" in clause
    assert "not" in clause


@pytest.mark.parametrize("form", NOT_FR_CODES)
def test_a_measured_rejected_form_name_is_not_advertised_as_a_code(
    mcp_module, form: str
) -> None:
    """Negative control on the fix itself.

    The cheap way to write the warning is to list the forms that failed. That
    would be wrong twice over: the list is four of an unbounded set, and a
    model skimming for a code would find these spelled out next to `types`.
    """
    clause = _types_clause(mcp_module)
    assert form not in clause


def test_the_taxonomy_guide_admits_filings_search_is_a_caller(mcp_module) -> None:
    """The other end of the path.

    The guide opened with "Pass these via the `type` query param (or `types`
    for several) on `filings_list`" — true, and it told an agent arriving from
    `filings_search` that it had landed in the wrong document.
    """
    guide = mcp_module._resource_filing_types.fn()
    header, _, _ = guide.partition("## Form names are NOT codes")
    assert header, "the taxonomy guide lost its form-name section"
    assert "filings_search" in header, (
        "the guide introduces itself as being about `filings_list` only"
    )


def test_the_taxonomy_tool_is_on_the_default_surface(mcp_module) -> None:
    """A pointer to a pruned tool is worse than no pointer.

    `filings_search` is on the default (19-tool) surface, so the tool it sends
    the model to has to be there too.
    """
    tools = mcp_module.mcp._tool_manager._tools
    assert TAXONOMY_TOOL in tools


def test_the_guide_scopes_its_search_recipes_to_filings_list(mcp_module) -> None:
    """Widening the guide's audience without scoping its recipes is a defect.

    SPECHT caught it 3/3 on `0de8131` — unanimous, and correct on both halves.
    Telling `filings_search` callers to read this guide hands them a document
    whose 10-Q recipe is `IR` plus `search="10-Q"` and whose verification step
    is "read `source_filing_type` on the row". `filings_search` has neither.
    An agent following the recipe makes an invalid call; one following the
    verification step has no field to read.

    The pointer was still right — the CODE TABLE is what a `filings_search`
    caller needs, and it is the only part of the guide that was ever going to
    help them. So the fix scopes the recipes rather than withdrawing the
    pointer.
    """
    guide = mcp_module._resource_filing_types.fn()
    header, _, _ = guide.partition("These codes are a cross-jurisdiction taxonomy")
    assert "filings_list` only" in header or "`filings_list` only" in header, (
        "the guide no longer says its `search=` recipes are filings_list-only"
    )
    assert "source_filing_type" in header


def test_the_scoping_claim_still_matches_the_tool_signatures(mcp_module) -> None:
    """The guide asserts two facts about `filings_search`. Pin them to the code.

    A prose claim about another tool's interface rots the moment that interface
    changes, and the guide is the one place a model is told to trust it. If
    `filings_search` ever grows a `search` parameter, this fails here rather
    than in a user's session.
    """
    import inspect

    search_params = set(
        inspect.signature(mcp_module.filings_search.fn).parameters
    )
    list_params = set(inspect.signature(mcp_module.filings_list.fn).parameters)

    assert "search" not in search_params, (
        "filings_search grew a `search` parameter — the taxonomy guide says it "
        "has none, and says so to steer agents to filings_list"
    )
    assert "types" in search_params, "filings_search lost `types`"
    # The control: the claim is a CONTRAST, so the other side has to hold too.
    assert "search" in list_params, (
        "filings_list lost `search` — the guide's recipes are written for it"
    )
