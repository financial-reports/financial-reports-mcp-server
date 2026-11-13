"""Every published tool count must be DERIVED from the module, not typed (#196).

`docs/token-budget.md` has the property these counts lack: CI regenerates it and
diffs it against the committed file, so it cannot go stale silently — and that
gate has already caught a real drift. The tool counts had no such check, so they
went stale on every surface change. Measured on `origin/main` before this test
existed: the READMEs and `AGENTS.md` said **17 / 55**, the generator's own
comment said **~52**, `docs/WORKFLOWS.md` said **52 / 16**,
`skills/GETTING-STARTED.md` said **16**, and the module emitted **19 / 61**.
Four different numbers for two facts, in one repo, with the wrong one in the
first sentence a prospective user reads.

So these tests do not assert constants. They regenerate the module in a
subprocess — once per surface, ~0.7s each — walk the AST, and compare every
documented number against what came out. The next surface change fails here
instead of shipping.

⚠ AST, never grep: a text pattern matches mentions as well as occurrences, and
`@mcp.tool` appears in comments in this repo.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED = REPO_ROOT / "src/financial_reports_mcp.py"
GENERATOR = REPO_ROOT / "scripts/generate_mcp_tools.py"

# The three tools the generator emits from inline `*_BLOCK` templates rather
# than from the OpenAPI schema. Named so the decomposition in the docs
# ("N schema-derived + 3 guide + 3 hand-written") stays checkable.
HAND_WRITTEN = {
    "filings_search",
    "filings_markdown_search",
    "filings_markdown_search_batch",
}


def _tool_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any("mcp.tool" in ast.unparse(d) for d in node.decorator_list)
    }


def _regenerate(full_surface: bool) -> set[str]:
    env = dict(os.environ)
    env["FR_PIN_SCHEMA"] = "1"  # the committed snapshot, never the live schema
    if full_surface:
        env["MCP_FULL_SURFACE"] = "1"
    else:
        env.pop("MCP_FULL_SURFACE", None)
    proc = subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"generator failed:\n{proc.stderr[-2000:]}"
    return _tool_names(GENERATED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def surfaces() -> dict[str, set[str]]:
    """Both surfaces, measured. Restores the default module afterwards.

    Module-scoped: two regenerations, not two per test.
    """
    default = _regenerate(full_surface=False)
    full = _regenerate(full_surface=True)
    _regenerate(full_surface=False)  # leave the tree as the rest of the suite expects
    return {"default": default, "full": full}


def _doc(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


# --- the measurements themselves ---------------------------------------------

def test_the_default_surface_decomposes_as_the_docs_describe_it(surfaces) -> None:
    """13 schema-derived + 3 guide + 3 hand-written. Pin the parts, not just the sum.

    A total alone cannot catch a tool moving between categories, and the docs
    describe the categories.
    """
    default = surfaces["default"]
    guide = {n for n in default if n.startswith("get_fr_")}
    hand = default & HAND_WRITTEN
    schema = default - guide - hand
    assert len(guide) == 3, sorted(guide)
    assert len(hand) == 3, sorted(hand)
    assert len(default) == len(schema) + len(guide) + len(hand)


def test_the_full_surface_is_not_a_superset_of_the_default(surfaces) -> None:
    """MCP_FULL_SURFACE=1 DROPS the three guide tools. This is deliberate.

    The generator says why: the guide tools "stand in for the dropped
    ISIC/reference tools", so they are emitted on the pruned surface only. But
    every doc called `MCP_FULL_SURFACE=1` the switch that "restores the full
    surface", which invites a reader to assume nesting — and a client that set
    it would silently LOSE three tools it had.

    Pinned because it is surprising: if the generator ever makes full a true
    superset, this fails and the docs' wording must change with it.
    """
    default, full = surfaces["default"], surfaces["full"]
    assert not default <= full
    assert sorted(default - full) == [
        "get_fr_filing_type_taxonomy",
        "get_fr_industry_classification_isic",
        "get_fr_markdown_fetch_strategy",
    ]


# --- every published number --------------------------------------------------
#
# ⛔ THE FIRST VERSION OF THIS SECTION WAS A GATE THAT COULD NOT FAIL, and SPECHT
# caught it 3/3 on `a4e7cd9`. It asserted two things: that the OLD constant (17 /
# `55-tool`) was absent, and that `str(measured) in text`. Both are satisfied by a
# stale document:
#
#   * rejecting only `17` says nothing about a README that says 18, or 20, or any
#     other wrong number — reproduced: changing the headline 19 -> 18 left all 11
#     tests green;
#   * `str(n) in text` is a SUBSTRING test over the whole file. Both READMEs carry
#     `2025` and `2026`, so `"20" in text` is True for free — a 20-tool surface
#     with a stale 19 in the headline would have passed on the strength of a date.
#
# So the PR body's claim that "the next surface change fails here instead of
# shipping" was false as implemented. The gate accrued eleven green tests while
# measuring nothing: the same shape as a check that always answers "no".
#
# The fix is to COMPARE, not to search: pull the number out of each count-bearing
# PHRASE and assert it equals the measured count. Every phrase shape the docs use
# is listed below, and a file with NO recognised claim is a failure too — a
# silently deleted claim must not read as a passing one.

# (pattern, which surface it describes). Anchored on the surrounding words, never
# on a bare digit.
_COUNT_CLAIMS: list[tuple[str, str]] = [
    # English prose
    (r"\*\*(\d+) curated tools by default\*\*", "default"),
    (r"\*\*(\d+) LLM-callable tools by default\*\*", "default"),
    (r"curated to a focused (\d+)-tool set", "default"),
    (r"exposes (\d+) tools covering", "default"),
    (r"curated \*\*(\d+)\*\* tools by default", "default"),
    (r"for the full (\d+)-tool surface", "full"),
    (r"the full \*\*(\d+)-tool\*\* surface", "full"),
    (r"emit the full (\d+)-tool surface", "full"),
    # The ASCII architecture diagram, both READMEs
    (r"│\s+(\d+) tools\s+│", "default"),
    # Chinese prose
    (r"\*\*默认提供 (\d+) 个精选工具\*\*", "default"),
    (r"\*\*默认提供 (\d+) 个可由 LLM 调用的工具\*\*", "default"),
    (r"默认工具集精选为 (\d+) 个", "default"),
    (r"完整的 (\d+) 个工具", "full"),
    (r"完整的 \*\*(\d+) 个工具\*\*", "full"),
]

# Which files must carry a claim about which surface. A file listed here with no
# recognised claim FAILS: that is how a deleted or reworded claim is caught
# instead of silently passing.
_DOCS_WITH_COUNTS: dict[str, tuple[str, ...]] = {
    "README.md": ("default", "full"),
    "README.zh-CN.md": ("default", "full"),
    "AGENTS.md": ("default", "full"),
    "docs/WORKFLOWS.md": ("default",),
    "skills/GETTING-STARTED.md": ("default",),
    "scripts/generate_mcp_tools.py": ("full",),
}


def _claims(text: str) -> list[tuple[str, int, str]]:
    """Every count claim in `text`, as (surface, number, the matched phrase)."""
    found = []
    for pattern, surface in _COUNT_CLAIMS:
        for m in re.finditer(pattern, text):
            found.append((surface, int(m.group(1)), m.group(0)))
    return found


def test_the_claim_extractor_actually_discriminates() -> None:
    """The control, because the gate is only as good as this function.

    A pattern list is an instrument, and an instrument that silently matches
    nothing turns every check below into a pass. These assert it finds the right
    number, and — the half the first version lacked — that it does NOT accept a
    wrong one just because the right digits appear somewhere.
    """
    good = "**19 curated tools by default** (set `X` for the full 61-tool surface). MCP spec 2025-06-18."
    assert sorted(_claims(good)) == sorted(
        [("default", 19, "**19 curated tools by default**"), ("full", 61, "for the full 61-tool surface")]
    )

    # The exact exploit SPECHT named: a stale count beside an unrelated 2025.
    stale = "**19 curated tools by default** (set `X` for the full 61-tool surface). MCP spec 2025-06-18."
    by_surface = {s: n for s, n, _ in _claims(stale)}
    assert by_surface["default"] == 19
    assert 20 not in by_surface.values(), "a date must not be read as a count"

    # And a reworded claim must come back as ABSENT, not as a pass.
    assert not _claims("roughly twenty tools, give or take")


@pytest.mark.parametrize("relpath", sorted(_DOCS_WITH_COUNTS))
def test_every_published_count_equals_the_measured_surface(
    surfaces, relpath: str
) -> None:
    """Compare each documented number with what the generator emits."""
    measured = {"default": len(surfaces["default"]), "full": len(surfaces["full"])}
    text = _doc(relpath)
    claims = _claims(text)

    for surface in _DOCS_WITH_COUNTS[relpath]:
        got = [(n, phrase) for s, n, phrase in claims if s == surface]
        assert got, (
            f"{relpath} states no recognised {surface}-surface tool count. Either "
            f"it lost one, or it was reworded past _COUNT_CLAIMS — add the new "
            f"phrasing there rather than deleting this expectation."
        )
        wrong = [(n, phrase) for n, phrase in got if n != measured[surface]]
        assert not wrong, (
            f"{relpath} claims {[n for n, _ in wrong]} for the {surface} surface; "
            f"the generator emits {measured[surface]}. Offending phrases: "
            f"{[p for _, p in wrong]}"
        )


def test_the_generator_comment_agrees_with_the_generator(surfaces) -> None:
    """The third number, and the one with least excuse: it is in the file that
    produces the surface it miscounts."""
    text = GENERATOR.read_text(encoding="utf-8")
    assert "~52-tool" not in text, "the generator still claims a ~52-tool full surface"


@pytest.mark.parametrize(
    "relpath,stale",
    [
        ("docs/WORKFLOWS.md", ("The 52 tools", "curated **16**")),
        ("skills/GETTING-STARTED.md", ("exposes 16 tools",)),
    ],
)
def test_the_secondary_docs_lost_their_stale_counts(relpath: str, stale) -> None:
    """Kept alongside the comparison above, not instead of it.

    This one pins the SPECIFIC wrong strings that shipped, so a revert to the
    exact prior wording is named in the failure. The comparison test is what
    catches an arbitrary wrong number.
    """
    text = _doc(relpath)
    still = [s for s in stale if s in text]
    assert not still, f"{relpath} still says {still}"
