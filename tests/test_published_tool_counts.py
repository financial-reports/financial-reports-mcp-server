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

def _stated_counts(text: str, pattern: str) -> list[int]:
    return [int(m) for m in re.findall(pattern, text)]


@pytest.mark.parametrize(
    "relpath",
    ["README.md", "README.zh-CN.md", "AGENTS.md"],
)
def test_the_headline_docs_state_the_measured_default_count(
    surfaces, relpath: str
) -> None:
    """Every "<N> tools by default" claim in the front-door docs.

    README.md line 11 is the blurb above the fold — the count a prospective
    user and every directory listing sees.
    """
    n = len(surfaces["default"])
    text = _doc(relpath)
    wrong = sorted(
        {c for c in _stated_counts(text, r"(\d+)\s*(?:个)?\s*(?:curated |LLM-callable |精选)?[  ]?(?:tools?|工具)") if c == 17}
    )
    assert not wrong, (
        f"{relpath} still states a default count of {wrong}; the module emits {n}"
    )
    assert str(n) in text, f"{relpath} never states the real default count ({n})"


@pytest.mark.parametrize("relpath", ["README.md", "README.zh-CN.md", "AGENTS.md"])
def test_the_headline_docs_state_the_measured_full_count(
    surfaces, relpath: str
) -> None:
    n = len(surfaces["full"])
    text = _doc(relpath)
    assert "55-tool" not in text and "55 个工具" not in text, (
        f"{relpath} still advertises a 55-tool full surface; it is {n}"
    )
    assert str(n) in text, f"{relpath} never states the real full count ({n})"


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
    text = _doc(relpath)
    still = [s for s in stale if s in text]
    assert not still, f"{relpath} still says {still}"
