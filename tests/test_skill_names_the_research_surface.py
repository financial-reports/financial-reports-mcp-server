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


def test_the_skill_names_every_research_tool(mcp_module) -> None:
    """A tool we serve but never mention is a silently worse answer."""
    text = _skill_text()
    missing = sorted(t for t in _research_surface(mcp_module) if t not in text)
    assert not missing, (
        f"skills/financial-filings-research/SKILL.md never names {missing}. "
        "The default surface serves them, so a model loading this skill will "
        "reach for a worse tool instead. Add them to the Tools table."
    )


def test_the_skill_names_no_tool_we_do_not_serve(mcp_module) -> None:
    """The complement, so the fix for the above cannot overshoot."""
    served = _default_surface(mcp_module)
    named = set(re.findall(r"`([a-z][a-z0-9_]*(?:_list|_retrieve|_create|_search|_batch))`", _skill_text()))
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
    assert "titles and company names only" in text, (
        "the skill no longer warns that `search=` matches names rather than "
        "filing text — the warning `filings_list`'s own description carries."
    )
    assert "filings_search" in text
