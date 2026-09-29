"""`processing_status` must never be a selection gate the model cannot satisfy (#106).

`filings_list(view='full')` returns more fields than the default view but, as of
2026-08-28, returned `processing_status` as null on EVERY row (the upstream full
serializer omitted it; fixed separately in financial-reports/web). Guidance that
told the model to "take the first row whose processing_status is COMPLETED" was
therefore unsatisfiable whenever a model chose `view='full'` — and models do.
Measured in the issue: correct newest annual report 4/5 -> 2/5.

Two guards:

* NEGATIVE, a regression denylist of the gate phrasings that actually shipped,
  checked in every model-facing source AND in the generated module (so prompts
  and resources are covered too).
* POSITIVE, over the RENDERED surface (tool descriptions, server instructions,
  resource bodies): any text that makes `COMPLETED` a condition must, in the same
  text, say what a null/absent value means. That catches a NEW gate added in a
  new place, which a denylist cannot.

SCOPE, stated honestly: the positive rule is per-text, not per-sentence, so a
text that mentions null somewhere and gates somewhere else would pass. It is a
floor, not a proof that no guidance gates.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MODEL_FACING = [
    "scripts/tool_overrides.yaml",
    "scripts/generate_mcp_tools.py",
    "docs/WORKFLOWS.md",
    "skills/financial-filings-research/SKILL.md",
    "skills/financial-filings-research/references/tool-cheatsheet.md",
    "src/financial_reports_mcp.py",
]

# Each of these shipped and is unsatisfiable when processing_status is null.
GATE_PHRASES = [
    "take the first row whose processing_status is 'COMPLETED'",
    "Read the `processing_status` field on each filing returned by filings_list before calling markdown",
    "confirm that filing's `processing_status` is `COMPLETED`",
    "check that field (returned by `filings_list`; it is NOT on the `filings_retrieve` response) before calling this tool",
    "processing_status gating",
    "prefer rows whose `processing_status` is `COMPLETED`",
]

NULL_MEANING = re.compile(r"\b(null|absent|unknown|omitted)\b", re.I)


def _flat(text: str) -> str:
    # Collapse YAML folding, Python string-concatenation seams and escaped
    # newlines so a phrase split across source lines still matches.
    text = text.replace('\\\\n', " ").replace("\\n", " ")
    text = re.sub(r'"\s*\n\s*"', "", text)
    return re.sub(r"\s+", " ", text)


def test_no_shipped_gate_phrasing_survives() -> None:
    hits = []
    for rel in MODEL_FACING:
        path = REPO / rel
        if not path.exists():
            continue
        flat = _flat(path.read_text(encoding="utf-8"))
        for phrase in GATE_PHRASES:
            if _flat(phrase) in flat:
                hits.append(f"{rel}: {phrase!r}")
    assert not hits, "processing_status gate phrasing is back:\n" + "\n".join(hits)


def test_denylist_matcher_positive_control() -> None:
    """The flattening must actually find a phrase split across concatenated
    Python string literals, or the test above passes vacuously."""
    split = '"take the first row "\n        "whose processing_status is \'COMPLETED\'"'
    assert _flat(GATE_PHRASES[0]) in _flat(split)


async def _rendered_texts(mcp_module) -> dict[str, str]:
    m = mcp_module
    texts = {f"tool:{n}": (t.description or "") for n, t in m.mcp._tool_manager._tools.items()}
    texts["instructions"] = m.mcp.instructions or ""
    for uri, res in m.mcp._resource_manager._resources.items():
        texts[f"resource:{uri}"] = res.fn()
    # Prompts are model-facing too. Render each with a string for every
    # argument (MCP transports prompt arguments as strings); no API call is
    # made at render time.
    for name, prompt in (await m.mcp.get_prompts()).items():
        args = {a.name: "AAPL" for a in (prompt.arguments or [])}
        messages = await prompt.render(arguments=args)
        texts[f"prompt:{name}"] = " ".join(
            msg.content.text if hasattr(msg.content, "text") else str(msg.content)
            for msg in messages
        )
    return texts


@pytest.mark.asyncio
async def test_every_completed_condition_says_what_null_means(mcp_module) -> None:
    texts = await _rendered_texts(mcp_module)
    # Positive control for the prompt leg: prompts were actually rendered.
    assert any(k.startswith("prompt:") for k in texts), sorted(texts)
    conditioned = {
        k: v for k, v in texts.items()
        if "processing_status" in v and "COMPLETED" in v
    }
    # Positive control: the texts that genuinely discuss the COMPLETED
    # condition must be found, or this test checks nothing.
    assert "tool:filings_markdown_retrieve" in conditioned
    assert "resource:fr://guide/markdown-strategy" in conditioned
    missing = [k for k, v in conditioned.items() if not NULL_MEANING.search(v)]
    assert not missing, (
        "these texts make processing_status == COMPLETED a condition without "
        f"saying what a null/absent value means: {missing}"
    )


def test_filings_list_says_both_views_carry_processing_status(mcp_module) -> None:
    """web#4192 (deployed 2026-09-29) made `view='full'` carry
    `processing_status`, so the old "null on every row under view='full'"
    caveat became false. The no-gate rule stays: a single row can still be null."""
    desc = _flat(mcp_module.mcp._tool_manager._tools["filings_list"].description or "")
    assert "both views carry `processing_status`" in desc, desc
    assert not re.search(r"processing_status` as null on every row", desc), desc
    assert "Never gate filing selection on `processing_status`" in desc


def test_no_guidance_claims_view_full_or_retrieve_lacks_processing_status(mcp_module) -> None:
    """Every surface a model reads (tool descriptions, resources, prompts) must
    stop saying the field is missing from view='full' or filings_retrieve."""
    # The generated module holds every tool description, resource body and
    # prompt template, so scanning its source reaches all three.
    blob = _flat(Path(mcp_module.__file__).read_text())
    for stale in (
        "null under view='full'",
        "as in `view='full'`",
        "as under view='full'",
        "OMITTED (null) when you pass `view='full'`",
        "not on the `filings_retrieve`",
        "superset of the default view",
    ):
        assert stale not in blob, stale


def test_markdown_strategy_resource_is_not_a_gate(mcp_module) -> None:
    body = _flat(mcp_module._resource_markdown.fn())
    assert "never a selection gate" in body
    assert "view='full'" in body
    # The fallback workflow picks the NEWEST row and skips only on a
    # present, non-COMPLETED value.
    assert "take the newest row" in body
    assert "is not a reason to skip" in body


@pytest.mark.asyncio
async def test_not_found_is_not_promised_as_pending(mcp_module) -> None:
    """A markdown 404 carries reasons that are permanent (`no_narrative_content`)
    as well as pending (`not_processed`), and the tool does not forward the
    reason to the model. Guidance must therefore not tell the model a
    not-found means markdown is coming "yet"."""
    texts = await _rendered_texts(mcp_module)
    offenders = [
        k for k, v in texts.items()
        if re.search(r"no markdown yet|not available yet", _flat(v), re.I)
    ]
    assert not offenders, offenders
