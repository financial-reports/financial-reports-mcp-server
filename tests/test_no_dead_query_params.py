"""Guard against instructing the model to send parameters the API does not have.

Every string in this repo that reaches a model — tool descriptions, the prompts
and resource guides emitted by the generator, and the shipped skill/docs
markdown — is an INSTRUCTION. Naming a parameter the API does not accept is a
real defect, and it fails in one of two ways:

  * an unknown TOOL ARGUMENT is rejected by pydantic before any HTTP call, so
    the model burns a turn on a `unexpected_keyword_argument` error; or
  * a real parameter with an unaccepted VALUE (notably `ordering`) passes
    validation, reaches DRF, and is SILENTLY DROPPED by the ordering allow-list
    — the caller gets default-ordered results and no error at all. That one
    returns a wrong answer with no signal, which is why it is tested here.

Both classes shipped simultaneously across 15 references before this test
existed. The denylist is deliberately literal rather than clever: it encodes
names that were actually wrong in this repo, so it cannot drift into false
positives on prose.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Files whose content is read by a model, either at runtime or after a user
# installs the skill. src/ is generated, so the generator is the source of truth.
MODEL_FACING = [
    "scripts/tool_overrides.yaml",
    "scripts/generate_mcp_tools.py",
    "docs/WORKFLOWS.md",
    "skills/financial-filings-research/SKILL.md",
    "skills/financial-filings-research/references/tool-cheatsheet.md",
]

# name -> what it should be. Each of these was a live defect.
DEAD_PARAMS = {
    "filing_type_code": "type / types",
    "filing_category": "category / categories",
    "from_date": "release_datetime_from",
    "to_date": "release_datetime_to",
    "isic_class": "sub_industry (param) / sub_industry_code (field)",
    "period_type": "fiscal_period / fiscal_year",
}

# Ordering values DRF will silently discard. filings_list's allow-list is
# ordering_fields = ['release_datetime', 'added_to_platform', 'id'].
DEAD_ORDERING = ["publication_datetime", "publication_date"]

# `name=` used as a query parameter, i.e. preceded by ? & , ( or whitespace and
# followed by a value. Avoids matching prose comparisons like `x == y`.
def _param_uses(text: str, name: str) -> list[str]:
    hits = []
    for m in re.finditer(rf"[?&,(\s`]{re.escape(name)}\s*=(?!=)", text):
        hits.append(text[max(0, m.start() - 60):m.start() + 40].replace("\n", " "))
    return hits


@pytest.mark.parametrize("relpath", MODEL_FACING)
def test_no_dead_query_params_in_model_facing_text(relpath: str) -> None:
    path = REPO / relpath
    if not path.exists():  # skills/ is optional in some checkouts
        pytest.skip(f"{relpath} not present")
    text = path.read_text(encoding="utf-8")
    problems = []
    for name, correct in DEAD_PARAMS.items():
        for ctx in _param_uses(text, name):
            problems.append(f"{name}= (use {correct}) ... {ctx.strip()}")
    assert not problems, (
        f"{relpath} instructs the model to send parameters the API does not "
        f"accept:\n  " + "\n  ".join(problems)
    )


@pytest.mark.parametrize("relpath", MODEL_FACING)
def test_no_silently_dropped_ordering_values(relpath: str) -> None:
    """`ordering` is a REAL param, so a bad value passes tool validation and is
    dropped by DRF without error — the caller silently gets default order."""
    path = REPO / relpath
    if not path.exists():
        pytest.skip(f"{relpath} not present")
    text = path.read_text(encoding="utf-8")
    bad = [v for v in DEAD_ORDERING if v in text]
    assert not bad, (
        f"{relpath} references ordering field(s) {bad} that are not in "
        f"filings_list's ordering allow-list (release_datetime, "
        f"added_to_platform, id). DRF discards them silently."
    )


def test_denylisted_names_are_genuinely_absent_from_the_schema() -> None:
    """Positive control for the denylist itself.

    If the API ever grows one of these as a real parameter, this test fails and
    the entry must be removed — otherwise the guard above would be rejecting
    correct instructions. A denylist nobody re-validates becomes wrong silently.
    """
    snapshot = json.loads((REPO / "scripts/openapi.snapshot.json").read_text())
    real_params = set()
    for item in snapshot.get("paths", {}).values():
        for op in item.values():
            if not isinstance(op, dict):
                continue
            for param in op.get("parameters", []):
                real_params.add(param.get("name"))

    now_real = sorted(set(DEAD_PARAMS) & real_params)
    assert not now_real, (
        f"{now_real} are now REAL query parameters in the schema. Remove them "
        f"from DEAD_PARAMS — this guard is currently rejecting valid usage."
    )
    # And the replacements this test steers people toward must actually exist.
    for expected in ("type", "types", "category", "categories",
                     "release_datetime_from", "sub_industry", "fiscal_year"):
        assert expected in real_params, (
            f"{expected!r} is recommended by this test but is not a real "
            f"parameter — the guidance itself has drifted."
        )
