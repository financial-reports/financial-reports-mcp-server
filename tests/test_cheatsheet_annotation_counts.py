"""The cheatsheet's ToolAnnotations counts, measured instead of typed.

`skills/.../references/tool-cheatsheet.md` publishes four counts about the FULL
surface's annotations: how many tools are `readOnlyHint=true`, how many are
`destructiveHint=true`, how many are non-destructive probes, and how many
advertise an `outputSchema`. They are not surface SIZES, so
`test_published_tool_counts.py` deliberately allowlists them rather than
comparing them, and until #208 nothing checked them at all.

⛔ THREE OF THE FIVE COUNTS IN THAT FILE WERE WRONG WHEN MEASURED on 2026-11-19:
it said 50 tools where the full surface is 64, 35 read-only where it is 52, and 5
destructive where it is 10. The probe count (2) and the `outputSchema` count (6)
were right. A shipped reference file drifted by a factor of two on the number a
reader would use to decide whether a tool is safe to call without confirmation,
which is the one number in the file with a safety meaning.

⚠ The `_pay_*` x402 variants are excluded throughout. They are duplicate
registrations of eleven tools under a payment path, so counting them inflates
every total: the full render emits 75 functions and the surface is 64. The README
and this file both mean 64, and a count that silently included the variants would
disagree with every other published figure for no visible reason.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate_mcp_tools.py"
GENERATED = REPO_ROOT / "src" / "financial_reports_mcp.py"
CHEATSHEETS = (
    "skills/financial-filings-research/references/tool-cheatsheet.md",
    "plugins/financialfilings/skills/financial-filings-research/references/tool-cheatsheet.md",
)


def _render(full_surface: bool) -> str:
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
    return GENERATED.read_text(encoding="utf-8")


def _annotations(source: str) -> dict[str, int]:
    """Annotation tallies over the rendered module, excluding `_pay_*`."""
    tree = ast.parse(source)
    tally = {"tools": 0, "read_only": 0, "destructive": 0, "probes": 0, "output_schema": 0}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = next(
            (d for d in node.decorator_list if "mcp.tool" in ast.unparse(d)), None
        )
        if decorator is None or node.name.startswith("_pay_"):
            continue
        tally["tools"] += 1
        read_only = destructive = None
        for keyword in getattr(decorator, "keywords", []):
            if keyword.arg == "output_schema":
                tally["output_schema"] += 1
            if keyword.arg == "annotations" and isinstance(keyword.value, ast.Call):
                for inner in keyword.value.keywords:
                    if inner.arg == "readOnlyHint":
                        read_only = ast.literal_eval(inner.value)
                    elif inner.arg == "destructiveHint":
                        destructive = ast.literal_eval(inner.value)
        if read_only is True:
            tally["read_only"] += 1
        if destructive is True:
            tally["destructive"] += 1
        if read_only is False and destructive is False:
            tally["probes"] += 1
    return tally


@pytest.fixture(scope="module")
def full_surface_annotations() -> dict[str, int]:
    """Measured over the full render, then the default render is restored.

    Restoring matters: the generator writes `src/financial_reports_mcp.py` AND
    the tracked `README.md` tool list, so a test that left the full surface
    rendered would hand the rest of the suite a different module and leave the
    working tree dirty in a file nobody edited.
    """
    measured = _annotations(_render(full_surface=True))
    _render(full_surface=False)
    return measured


def test_the_tally_is_not_vacuous(full_surface_annotations) -> None:
    """Positive control first. Every assertion below compares a published number
    against this tally, so a tally of zeros would make them all fail loudly
    rather than pass, but a tally that counted the wrong thing could still agree
    with a wrong document. Pin the shape before trusting the numbers."""
    tally = full_surface_annotations
    assert tally["tools"] > 50, f"the full surface should be dozens of tools, got {tally}"
    assert tally["read_only"] < tally["tools"], "some tools must be non-read-only"
    assert tally["destructive"] > 0, "the full surface includes mutating tools"


@pytest.mark.parametrize("relpath", CHEATSHEETS)
def test_the_cheatsheet_annotation_counts_match_the_module(
    full_surface_annotations, relpath
) -> None:
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    tally = full_surface_annotations
    claims = [
        (r"(\d+) tools across \d+ domains\. This file is loaded", "tools"),
        (r"(\d+) tools have `readOnlyHint=true`", "read_only"),
        (r"(\d+) tools have `destructiveHint=true`", "destructive"),
        (r"(\d+) tools are non-destructive probes", "probes"),
        (r"(\d+) tools advertise `outputSchema`", "output_schema"),
    ]
    for pattern, key in claims:
        match = re.search(pattern, text)
        assert match, (
            f"{relpath} no longer carries a claim matching {pattern!r}. A deleted "
            "claim must not read as a passing one: either restore it or drop this "
            "entry deliberately."
        )
        published = int(match.group(1))
        assert published == tally[key], (
            f"{relpath} says {published} for {key}, module has {tally[key]}"
        )
