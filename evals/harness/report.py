"""Render results into a markdown scorecard + a JSON dump."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from .mcp_client import ToolSpec
from .results import RunResult
from .scorer import TaskScore, score_task, tool_usage_frequency
from .tasks import Task


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.0f}%" if pct else f"{x:.1f}"


def build_report(
    results: dict[tuple[str, str], list[RunResult]],
    tasks: list[Task],
    tools: list[ToolSpec],
) -> tuple[str, dict]:
    tasks_by_id = {t.id: t for t in tasks}
    scores: list[TaskScore] = [
        score_task(tasks_by_id[task_id], runs)
        for (_model, task_id), runs in results.items()
    ]
    models = sorted({s.model for s in scores})
    all_runs = [r for runs in results.values() for r in runs]
    freq = tool_usage_frequency(all_runs)
    used = set(freq)
    never_used = sorted(t.name for t in tools if t.name not in used)

    lines: list[str] = []
    lines.append("# FinancialReports MCP — Eval Scorecard")
    lines.append("")
    lines.append(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · "
                 f"{len(tasks)} tasks · {len(tools)} tools advertised")
    lines.append("")

    # Per-model summary
    lines.append("## Model summary")
    lines.append("")
    lines.append("| Model | Success | First-tool acc | Path consist. | Outcome consist. | "
                 "Mean turns | Mean tokens | Errored | Retries |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for m in models:
        ms = [s for s in scores if s.model == m]
        def avg(attr, pct=False, skip_none=False):
            vals = [getattr(s, attr) for s in ms]
            if skip_none:
                vals = [v for v in vals if v is not None]
            return _fmt(sum(vals) / len(vals) if vals else None, pct)
        lines.append(
            f"| {m} | {avg('success_rate', pct=True)} | "
            f"{avg('first_tool_accuracy', pct=True, skip_none=True)} | "
            f"{avg('path_consistency', pct=True)} | {avg('outcome_consistency', pct=True)} | "
            f"{avg('mean_turns')} | {avg('mean_total_tokens')} | "
            f"{sum(s.errored_calls for s in ms)} | {sum(s.retries for s in ms)} |"
        )
    lines.append("")

    # Per-task breakdown
    lines.append("## Per-task breakdown")
    lines.append("")
    lines.append("| Task | Model | Success | 1st-tool | Selection | Path | Outcome | Turns | Tokens |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for s in sorted(scores, key=lambda s: (s.task_id, s.model)):
        lines.append(
            f"| {s.task_id} | {s.model} | {_fmt(s.success_rate, pct=True)} | "
            f"{_fmt(s.first_tool_accuracy, pct=True)} | {_fmt(s.selection_accuracy, pct=True)} | "
            f"{_fmt(s.path_consistency, pct=True)} | {_fmt(s.outcome_consistency, pct=True)} | "
            f"{_fmt(s.mean_turns)} | {_fmt(s.mean_total_tokens)} |"
        )
    lines.append("")

    # Tool usage — the pruning signal
    lines.append("## Tool usage frequency")
    lines.append("")
    for name, n in freq.most_common():
        lines.append(f"- `{name}` — {n}")
    if never_used:
        lines.append("")
        lines.append(f"**Never used ({len(never_used)} — demotion/consolidation candidates):** "
                     + ", ".join(f"`{n}`" for n in never_used))
    lines.append("")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_tasks": len(tasks),
        "n_tools": len(tools),
        "scores": [asdict(s) for s in scores],
        "tool_usage": dict(freq),
        "never_used": never_used,
    }
    return "\n".join(lines), payload


def write_report(md: str, payload: dict, out_dir: str) -> tuple[str, str]:
    import os
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "scorecard.md")
    json_path = os.path.join(out_dir, "scorecard.json")
    with open(md_path, "w") as fh:
        fh.write(md)
    with open(json_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return md_path, json_path
