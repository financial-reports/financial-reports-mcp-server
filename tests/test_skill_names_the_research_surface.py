"""The skill must not fall behind the tool surface it teaches (#182's missing half).

`test_generated_server_names_no_pruned_tool` already guards one direction: server
text must not name a tool the default surface PRUNES, because a client told about
a tool it cannot call will try to call it.

Nothing guarded the other direction, and that is the one that bit. The shipped
skill was written before `filings_search` (v1.4.169, 2026-11-06) and before
`filings_markdown_search_batch`, so its Tools table named 14 tools while its own
prose said "16 research tools" — internally inconsistent by exactly the two that
had shipped since. A visitor loading it gets routed through the per-filing path
for "which filings mention X", and `filings_list?search=` matches titles only, so
the answer comes back empty. That is a measured failure, not a hypothetical: a
ChatGPT client made 11 `filings_list` title searches with boolean strings and got
0 results before its connector was rescanned.

The asymmetry is the point: over-promising a tool is loud (the model calls it and
errors), while under-promising is silent (the model uses a worse tool and returns
a plausible wrong answer). Only the first had a test.

RESEARCH SURFACE, defined as the skill itself defines it: the default surface
minus the administrative and reference tools the skill explicitly excludes. That
subset is derived here from the generated module rather than hardcoded, so a new
tool joins this test's expectation automatically — the whole point.

SCOPE: this pins the TOOLS TABLE's coverage and the prose count's arithmetic. It
says nothing about whether the guidance for each tool is any good.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills/financial-filings-research/SKILL.md"

# Named by the skill as outside the "research surface": administrative (spend)
# and reference-data lookups. Kept as an explicit, reviewable list — if a future
# tool belongs here, adding it is a deliberate act, not a silent omission.
NOT_RESEARCH = {
    "usage_retrieve",          # administrative: spend and quota
    "filing_types_list",       # reference data
    "filing_categories_list",  # reference data
}


def _default_surface(mcp_module) -> set[str]:
    return set(mcp_module.mcp._tool_manager._tools)


def _research_surface(mcp_module) -> set[str]:
    return _default_surface(mcp_module) - NOT_RESEARCH


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _tools_named_in_table() -> set[str]:
    """WHOLE backticked tool names in the `## Tools` section.

    SPECHT caught the substring bug (S3 on 7fdc2f7, 1/3 passes, reproduced
    before acting): a plain `in` test let `filings_markdown_search` be
    satisfied by `filings_markdown_search_batch`, which CONTAINS it. Deleting
    the single-filing tool's entry therefore left all five tests green.

    That is the SECOND time this file's check was looser than its own claim —
    first whole-file vs the table, now substring vs whole name. Both times the
    docstring described the stricter check.
    """
    return set(re.findall(r"`([a-z][a-z0-9_]*)`", _tools_table()))


def _tools_table() -> str:
    """Just the `## Tools` section — the table a model reads to pick a tool.

    SPECHT caught the first version of this file searching the WHOLE skill
    (S3 on 0c6350e, 2/3 passes, verified by reproducing its mutation): deleting
    `filings_search`'s table row while leaving the Pitfalls paragraph intact
    left every test green, because the name still appeared somewhere in the
    file. The docstring claimed to pin the Tools table and the code pinned
    file-wide presence — the check was looser than the claim made from it.
    """
    text = _skill_text()
    _, _, after = text.partition("## Tools")
    assert after, "the skill no longer has a `## Tools` section"
    section, _, _ = after.partition("\n## ")
    return section


CHEATSHEET = REPO_ROOT / "skills/financial-filings-research/references/tool-cheatsheet.md"


def _tools_with_a_cheatsheet_entry() -> set[str]:
    """Tools that have their OWN `### \u0060name\u0060` entry in the cheatsheet.

    A HEADING, not a mention. `filings_markdown_search` appeared in the
    cheatsheet before this guard existed \u2014 inside another tool's pitfall
    paragraph \u2014 and a grep for the name therefore said it was documented
    while the parameter reference had no entry for it. A mention is not an
    occurrence.
    """
    text = CHEATSHEET.read_text(encoding="utf-8")
    return set(re.findall(r"^### `([a-z][a-z0-9_]*)`", text, re.M))


def test_the_skill_names_every_research_tool(mcp_module) -> None:
    """A tool we serve but never mention is a silently worse answer."""
    named = _tools_named_in_table()
    missing = sorted(_research_surface(mcp_module) - named)
    assert not missing, (
        f"the `## Tools` table in skills/financial-filings-research/SKILL.md "
        f"never names {missing}. The default surface serves them, so a model "
        "loading this skill will reach for a worse tool instead. A mention "
        "elsewhere in the file does not count — the table is what a model "
        "reads to pick a tool."
    )


# A backticked name in the skill is a TOOL name or a PARAMETER name, and only
# the first kind belongs in the complement check below. The discriminator is
# name SHAPE: every tool is either a `get_fr_*` guide tool or ends in one of the
# OpenAPI operation suffixes, while `release_datetime_from`, `on_watchlist` and
# `source_filing_type` are none of those.
#
# SPECHT caught the first version missing the `get_fr_*` arm (S3 on 0fb3ae8,
# reproduced before acting): the suffix list alone matches none of the three
# guide tools, which are precisely the three this PR newly recommends. The
# complement claimed the fix could not overshoot and could not see the overshoot
# this PR was in a position to make.
#
# The shape test is a heuristic, so it gets a control: see
# test_the_tool_name_matcher_can_see_every_served_tool.
_TOOL_NAME_IN_PROSE = re.compile(
    r"`(get_fr_[a-z0-9_]+|[a-z][a-z0-9_]*(?:_list|_retrieve|_create|_search|_batch))`"
)


def test_the_tool_name_matcher_can_see_every_served_tool(mcp_module) -> None:
    """The control for the heuristic below, and the reason it cannot go blind again.

    The complement check can only flag a name it MATCHES, so a tool whose name
    fits no known shape is invisible to it — silently, and in the reassuring
    direction. Rather than trusting the pattern, assert it covers the surface we
    actually serve. The day a tool lands with a new naming shape, this fails
    here instead of the complement quietly narrowing.
    """
    blind = sorted(
        name
        for name in _default_surface(mcp_module)
        if not _TOOL_NAME_IN_PROSE.fullmatch(f"`{name}`")
    )
    assert not blind, (
        f"the tool-name matcher cannot see {blind}, so the complement check "
        "below is blind to them: the skill could recommend one that we stop "
        "serving and no test would fail. Widen _TOOL_NAME_IN_PROSE."
    )


def test_the_skill_names_no_tool_we_do_not_serve(mcp_module) -> None:
    """The complement, so the fix for the above cannot overshoot.

    Deliberately file-wide, unlike the coverage check: recommending a tool we
    do not serve is wrong wherever it appears, not only in the Tools table.
    """
    served = _default_surface(mcp_module)
    named = set(_TOOL_NAME_IN_PROSE.findall(_skill_text()))
    unknown = sorted(n for n in named if n not in served)
    assert not unknown, (
        f"the skill names tools the default surface does not serve: {unknown}"
    )


def test_the_prose_count_matches_the_research_surface(mcp_module) -> None:
    """The count in the prose is a claim like any other; pin it to the module.

    It read "16 research tools" while the table listed 14 — the prose was right
    and the table was stale, which is why the count is checked against the
    module rather than against the table.
    """
    text = _skill_text()
    m = re.search(r"\*\*(\d+) research tools\*\*", text)
    assert m, "the skill no longer states a research-tool count"
    claimed = int(m.group(1))
    actual = len(_research_surface(mcp_module))
    assert claimed == actual, (
        f"the skill claims {claimed} research tools; the default surface minus "
        f"{sorted(NOT_RESEARCH)} is {actual}. Update the prose and the table together."
    )


def test_the_skill_warns_that_search_matches_names_not_text(mcp_module) -> None:
    """The skill must not undercut the connector's own routing guidance.

    `filings_list`'s live description says: don't use `search` to find filings
    that DISCUSS a topic, it matches titles and company names only, use
    `filings_search`. A skill file loads as INSTRUCTIONS and in practice
    outranks a tool description, so a skill that omits this quietly overrides it.
    """
    text = _skill_text().lower()
    # Pin the SUBSTANCE, not a phrasing. The first version asserted the literal
    # "titles and company names only", which SPECHT then showed to be FALSE of
    # `companies_list?search=` (it also matches ticker and LEI/ISIN prefixes).
    # A test that pins exact wording makes correcting that wording look like a
    # regression — so it anchors on the claim that is true and load-bearing:
    # `search=` never reaches filing text, and `filings_search` is the route.
    assert "never matches filing text" in text or "not filing text" in text, (
        "the skill no longer warns that `search=` does not reach filing text — "
        "the warning `filings_list`'s own description carries."
    )
    assert "filings_search" in text


def test_the_coverage_check_reads_the_table_and_not_the_whole_file(
    mcp_module, monkeypatch
) -> None:
    """SPECHT's mutation, encoded so the blindness cannot return.

    A tool named only in Pitfalls must NOT satisfy the coverage check. Without
    this, a later refactor back to a file-wide search would pass every other
    test here and silently stop pinning the table.

    SPECHT then caught this test ITSELF (S3 on ce21ff6, 1/3 passes, reproduced
    before acting). Two defects, and both made it a control that could not
    fail:

      1. It applied the mutation to a local string and asked `in table_without`
         directly, never calling `_tools_named_in_table()`. Changing that
         helper back to scanning the whole file left this test green — the one
         regression it exists to catch.
      2. The `in` it used was the SUBSTRING comparison the helper had just been
         fixed to stop using, so the test re-implemented the bug it guards.

    Both are gone. The mutation is applied to `_tools_table`, so the real
    parser runs over it, and the assertion reads that parser's output as a set
    of whole names.
    """
    sentinel = "filings_search"
    assert sentinel in _tools_named_in_table(), (
        "precondition: the table names filings_search"
    )

    # Simulate the row being dropped while the Pitfalls mention survives.
    table_without = _tools_table().replace(sentinel, "REMOVED")
    assert sentinel in _skill_text().replace(_tools_table(), table_without), (
        "precondition: filings_search is also mentioned outside the table, "
        "which is what made the file-wide search blind"
    )

    monkeypatch.setattr(
        "tests.test_skill_names_the_research_surface._tools_table",
        lambda: table_without,
    )

    # Through the real parser, exactly as the coverage test computes it.
    missing = _research_surface(mcp_module) - _tools_named_in_table()
    assert sentinel in missing, (
        "the coverage check is reading the whole file again, not the `## Tools` "
        "table: a tool mentioned only in Pitfalls should count as missing."
    )


def test_every_tool_the_table_names_has_a_cheatsheet_entry(mcp_module) -> None:
    """SKILL.md says "Full parameters in `references/tool-cheatsheet.md`".

    That sentence is a promise, and SPECHT found it broken (S4 on ce21ff6):
    the table had just started recommending `filings_search` and
    `filings_markdown_search_batch`, and neither had an entry \u2014 so an agent
    that followed the pointer could not find `queries` or `filing_ids`.
    `filings_markdown_search` was missing too, which the finding did not say.

    The table and the reference now move together or this fails.
    """
    promised = _tools_named_in_table() & _default_surface(mcp_module)
    documented = _tools_with_a_cheatsheet_entry()
    missing = sorted(promised - documented)
    assert not missing, (
        f"the Tools table recommends {missing}, SKILL.md promises full "
        "parameters in references/tool-cheatsheet.md, and the cheatsheet has "
        "no `### ` entry for them. A mention inside another tool's paragraph "
        "does not count."
    )
