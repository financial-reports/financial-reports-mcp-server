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

    # \u26d4 THE LINE THAT USED TO BE HERE WAS A TAUTOLOGY, and SPECHT caught it:
    #     assert len(default) == len(schema) + len(guide) + len(hand)
    # `schema` is DEFINED as `default - guide - hand`, so that holds for ANY
    # partition and checks nothing. Meanwhile `docs/WORKFLOWS.md` states a
    # literal "13 schema-derived" that nothing compared against: a schema
    # refresh could add a curated tool, the headline total be updated, and that
    # subtotal stay wrong with this test green.
    documented = re.search(r"(\d+) schema-derived", _doc("docs/WORKFLOWS.md"))
    assert documented, (
        "docs/WORKFLOWS.md no longer states a schema-derived subtotal; it was "
        "the only published breakdown of the default surface"
    )
    assert int(documented.group(1)) == len(schema), (
        f"docs/WORKFLOWS.md says {documented.group(1)} schema-derived tools; "
        f"the generator emits {len(schema)} "
        f"({len(default)} default minus {len(guide)} guide minus {len(hand)} "
        f"hand-written)"
    )


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
    (r"composing the (\d+) FinancialFilings MCP tools", "full"),
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
    return [(surface, n, phrase) for surface, n, phrase, _span in _claims_with_spans(text)]


def _claims_with_spans(text: str) -> list[tuple[str, int, str, tuple[int, int]]]:
    """As `_claims`, plus each match's span.

    The coverage control compares by POSITION, not by substring: its looser
    detector starts at a different offset (it caught the `1` of
    `MCP_FULL_SURFACE=1` before "for the full 61-tool surface"), so a
    containment test reported a recognised claim as unrecognised.
    """
    found = []
    for pattern, surface in _COUNT_CLAIMS:
        for m in re.finditer(pattern, text):
            found.append((surface, int(m.group(1)), m.group(0), m.span()))
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


# Phrases that LOOK like a surface count and are not. Each is a different,
# correct quantity, so a blanket sweep would corrupt them -- which is why the
# gate compares recognised claims rather than rejecting digits. Verified
# individually before being listed here.
_NOT_A_SURFACE_COUNT = (
    # the RESEARCH surface: default minus the 3 administrative/reference tools.
    # Pinned against the module by tests/test_skill_names_the_research_surface.py.
    "16 research tools",
    "**16** tools for regulatory-filings research",
    # my own prose about the default/full overlap, in both READMEs
    "16 tools are on both surfaces",
    "两种工具集共有 16 个工具",
    # decomposition sub-counts, pinned by
    # test_the_default_surface_decomposes_as_the_docs_describe_it
    "3 `get_fr_*` guide tools",
    "3 hand-written search tools",
)

#: Files whose tool-count claims this gate is responsible for.
_COUNT_BEARING_DOCS = (
    "README.md",
    "README.zh-CN.md",
    "AGENTS.md",
    "docs/WORKFLOWS.md",
    "skills/GETTING-STARTED.md",
    "skills/README.md",
)


def test_no_count_phrasing_escapes_the_patterns(surfaces) -> None:
    """The coverage control, and the reason the gate is not just "patterns I thought of".

    `_COUNT_CLAIMS` can only check a phrasing it recognises, and silence from an
    unrecognised one reads exactly like coverage. SPECHT caught that directly
    (S3 on `4ca8629`): `docs/WORKFLOWS.md` line 3 still said "the 52 ... MCP
    tools" while line 22 was correct and the gate was green, because no pattern
    matched line 3's wording.

    So this sweeps a LOOSER detector over the same files and requires every
    number-next-to-"tools" phrase to be either recognised by `_COUNT_CLAIMS` or
    listed in `_NOT_A_SURFACE_COUNT` with a reason. A new phrasing then fails
    here rather than going silently unchecked.

    ⚠ The allowlist is load-bearing and was measured, not assumed: the "16" in
    `skills/README.md` is the RESEARCH surface (default minus the three
    administrative/reference tools), not a stale default count. SPECHT reported
    it as stale; it is correct, and a blanket sweep would have corrupted it.
    """
    loose = re.compile(r"\b(\d+)\b[^.\n]{0,30}?\btools?\b")
    unrecognised: list[tuple[str, str]] = []
    for relpath in _COUNT_BEARING_DOCS:
        text = _doc(relpath)
        spans = [span for _, _, _, span in _claims_with_spans(text)]
        for match in loose.finditer(text):
            phrase = match.group(0)
            lo, hi = match.span()
            # Overlapping a recognised claim's span means it IS that claim,
            # seen from a different starting offset.
            if any(lo < end and start < hi for start, end in spans):
                continue
            if any(ok in phrase or phrase in ok for ok in _NOT_A_SURFACE_COUNT):
                continue
            unrecognised.append((relpath, phrase))
    assert not unrecognised, (
        "these read as tool counts and no pattern in _COUNT_CLAIMS checks them, "
        "so the gate is silent about them: "
        + "; ".join(f"{f}: {p!r}" for f, p in unrecognised)
        + ". Add the phrase shape to _COUNT_CLAIMS, or, if it is a different "
        "quantity, to _NOT_A_SURFACE_COUNT with the reason."
    )


@pytest.mark.parametrize(
    "relpath,qualifier",
    [("README.md", "extracted text"), ("README.zh-CN.md", "已提取文本")],
)
def test_the_readme_does_not_oversell_corpus_search_coverage(
    relpath: str, qualifier: str
) -> None:
    """`filings_search` does not search every filing's text, and saying so
    turns a miss into a reported absence.

    The tool's own description is explicit: an empty result means nothing
    matched "among filings with extracted text, within the first 20 MB of each
    filing's text". The first version of the Filings row in this PR said
    "full-text search across every filing's text" — which is the over-claim
    #197 shipped a whole `EMPTY IS NOT PROOF OF ABSENCE` block to prevent,
    reintroduced one file over by the same author. SPECHT caught it (S2 on
    `4ca8629`).

    Anchored on SUBSTANCE, not phrasing: the row must carry the coverage
    qualifier and must not claim totality. Pinning the exact sentence is the
    trap a sibling guard already paid for — it made correcting the sentence
    read as a regression.
    """
    row = next(
        (line for line in _doc(relpath).splitlines() if "filings_search" in line),
        None,
    )
    assert row, f"{relpath} no longer describes filings_search in its tool table"
    assert qualifier in row, (
        f"{relpath}'s filings_search entry states no coverage limit. The tool "
        f"searches filings WITH EXTRACTED TEXT, first 20 MB of each; a reader "
        f"told it searches everything treats a miss as proven absence."
    )
    for overclaim in ("every filing's text", "全部公告正文"):
        assert overclaim not in row, (
            f"{relpath} claims filings_search covers {overclaim!r}; it does not"
        )
