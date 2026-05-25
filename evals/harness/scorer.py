"""Scoring — pure functions over RunResult lists. No network, no LLM here;
the LLM judge runs in the runner and writes `success` onto each RunResult
before these aggregate it. Everything in this module is unit-testable.

Metrics (the five the benchmark answers):
  - success_rate        : fraction of runs graded success
  - selection_accuracy  : did the run call the expected tools, and only those?
  - variability         : how consistent are repeated runs of the same task?
  - efficiency          : mean turns / tokens / latency
  - confusion           : wrong-tool, errored-tool, and retry signals
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean, pstdev

from .results import RunResult
from .tasks import Task


def _safe_mean(xs: list[float]) -> float:
    return mean(xs) if xs else 0.0


def selection_score(task: Task, run: RunResult) -> float:
    """1.0 = called every expected tool and no forbidden tool; partial credit
    for coverage, penalized for forbidden-tool calls. Tasks with no declared
    expected_tools score None-equivalent (returns 1.0 and are excluded by the
    aggregator via `has_expected`)."""
    expected = set(task.expected_tools)
    forbidden = set(task.forbidden_tools)
    called = set(run.tool_sequence)
    if not expected:
        return 1.0
    coverage = len(expected & called) / len(expected)
    forbidden_hits = len(forbidden & called)
    penalty = 0.25 * forbidden_hits
    return max(0.0, coverage - penalty)


def first_tool_correct(task: Task, run: RunResult) -> bool | None:
    """Did the FIRST tool call land in the expected set? None if the task has
    no expected tools or the run made no calls."""
    if not task.expected_tools or not run.tool_calls:
        return None
    return run.tool_calls[0].name in set(task.expected_tools)


def confusion_signals(run: RunResult, task: Task | None = None) -> dict[str, int]:
    """Per-run confusion fingerprint."""
    errored = sum(1 for c in run.tool_calls if not c.ok)
    # retry = the same tool called again immediately after it errored
    retries = 0
    seq = run.tool_calls
    for i in range(1, len(seq)):
        if seq[i].name == seq[i - 1].name and not seq[i - 1].ok:
            retries += 1
    forbidden = 0
    if task is not None and task.forbidden_tools:
        fb = set(task.forbidden_tools)
        forbidden = sum(1 for c in run.tool_calls if c.name in fb)
    return {"errored_calls": errored, "retries": retries, "forbidden_calls": forbidden}


def path_consistency(runs: list[RunResult]) -> float:
    """Variability — tool-path side. 1.0 = every repeat used the identical tool
    sequence; lower = the model takes different routes each time. Computed as
    the share of runs that match the modal (most common) tool sequence."""
    seqs = [r.tool_sequence for r in runs if not r.crashed]
    if len(seqs) < 2:
        return 1.0
    modal_count = Counter(seqs).most_common(1)[0][1]
    return modal_count / len(seqs)


def outcome_consistency(runs: list[RunResult]) -> float:
    """Variability — outcome side. 1.0 = every repeat reached the same
    success verdict. Penalizes flapping (sometimes passes, sometimes fails)."""
    verdicts = [r.success for r in runs if not r.crashed and r.success is not None]
    if len(verdicts) < 2:
        return 1.0
    modal_count = Counter(verdicts).most_common(1)[0][1]
    return modal_count / len(verdicts)


@dataclass
class TaskScore:
    task_id: str
    model: str
    n_runs: int
    n_crashed: int
    success_rate: float
    first_tool_accuracy: float | None
    selection_accuracy: float | None
    path_consistency: float
    outcome_consistency: float
    mean_turns: float
    mean_total_tokens: float
    mean_latency_ms: float
    errored_calls: int
    retries: int
    forbidden_calls: int


def score_task(task: Task, runs: list[RunResult]) -> TaskScore:
    """Aggregate N runs of one task on one model into a TaskScore."""
    if not runs:
        raise ValueError("no runs to score")
    model = runs[0].model
    live = [r for r in runs if not r.crashed]
    n_crashed = len(runs) - len(live)

    successes = [1.0 for r in live if r.success] + [0.0 for r in live if r.success is False]
    success_rate = _safe_mean(successes)

    sel = [selection_score(task, r) for r in live]
    selection_accuracy = _safe_mean(sel) if (task.expected_tools and live) else None

    ftc = [1.0 if first_tool_correct(task, r) else 0.0
           for r in live if first_tool_correct(task, r) is not None]
    first_tool_accuracy = _safe_mean(ftc) if ftc else None

    conf = [confusion_signals(r, task) for r in live]

    return TaskScore(
        task_id=task.id,
        model=model,
        n_runs=len(runs),
        n_crashed=n_crashed,
        success_rate=success_rate,
        first_tool_accuracy=first_tool_accuracy,
        selection_accuracy=selection_accuracy,
        path_consistency=path_consistency(runs),
        outcome_consistency=outcome_consistency(runs),
        mean_turns=_safe_mean([float(r.turns) for r in live]),
        mean_total_tokens=_safe_mean([float(r.input_tokens + r.output_tokens) for r in live]),
        mean_latency_ms=_safe_mean([float(r.latency_ms) for r in live]),
        errored_calls=sum(c["errored_calls"] for c in conf),
        retries=sum(c["retries"] for c in conf),
        forbidden_calls=sum(c["forbidden_calls"] for c in conf),
    )


def tool_usage_frequency(runs: list[RunResult]) -> Counter:
    """Across all runs: how often each tool was called. Answers 'which tools
    get used' and surfaces never-used tools (candidates for demotion)."""
    c: Counter = Counter()
    for r in runs:
        c.update(r.tool_sequence)
    return c
