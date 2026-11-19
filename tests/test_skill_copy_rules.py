"""The shipped skill files must follow the plugin's copy rules.

#208 (from #187's copy rules): no long dashes, and the description says
"official filings, as published" rather than "regulatory filings".

⛔ WHY THIS IS A TEST AND NOT A CHECKLIST ITEM. #208 asked for these rules, the PR
that implemented them removed 70 long dashes, and then reintroduced them -- six
in later disposition rounds of the same PR, three of which survived to be found
only by grepping the shipped tree by hand. A rule I was actively enforcing, in
the PR that exists to enforce it, did not hold by vigilance. It holds by a test.

Scope is deliberately the SHIPPED plugin skill tree, which is what the Claude
plugin directory serves and what its reviewer reads. docs/ and README files are
outside #208's copy rule and carry pre-existing long dashes.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIPPED = sorted((ROOT / "plugins" / "financialfilings" / "skills").rglob("*.md"))


def test_the_shipped_tree_is_not_empty() -> None:
    """Positive control: an empty glob passes every assertion below."""
    assert len(SHIPPED) >= 6, f"expected 5 SKILL.md files plus references, found {SHIPPED}"


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_long_dashes(path: pathlib.Path) -> None:
    lines = [
        (n, line.strip())
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "—" in line
    ]
    assert not lines, (
        f"{path.relative_to(ROOT)} carries long dashes, which the plugin copy rules "
        f"forbid. Use a comma, colon or full stop. Lines: {lines[:5]}"
    )


def test_no_regulatory_filings_wording_in_descriptions() -> None:
    offenders = []
    for path in SHIPPED:
        if path.name != "SKILL.md":
            continue
        head = path.read_text(encoding="utf-8").split("---")[1]
        if "regulatory filings" in head.lower():
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "these skill descriptions say 'regulatory filings'; the copy rule is "
        f"'official filings, as published': {offenders}"
    )


def test_the_dash_check_can_fail() -> None:
    """Mutation control: prove the detector sees the character it guards."""
    assert "—" in "a — b"
    assert "—" not in "a, b"
