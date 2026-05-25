"""Unit tests for the pure scoring layer — runnable without any secrets."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.results import RunResult, ToolCall  # noqa: E402
from harness.scorer import (  # noqa: E402
    confusion_signals,
    first_tool_correct,
    outcome_consistency,
    path_consistency,
    score_task,
    selection_score,
    tool_usage_frequency,
)
from harness.tasks import Task  # noqa: E402


def _run(task_id="t", model="m", i=0, tools=(), **kw) -> RunResult:
    return RunResult(
        task_id=task_id, model=model, run_index=i,
        tool_calls=[t if isinstance(t, ToolCall) else ToolCall(t) for t in tools],
        **kw,
    )


def test_selection_full_credit():
    task = Task(id="t", prompt="p", expected_tools=("a", "b"))
    run = _run(tools=("a", "b"))
    assert selection_score(task, run) == 1.0


def test_selection_partial_coverage():
    task = Task(id="t", prompt="p", expected_tools=("a", "b"))
    run = _run(tools=("a",))
    assert selection_score(task, run) == 0.5


def test_selection_forbidden_penalty():
    task = Task(id="t", prompt="p", expected_tools=("a",), forbidden_tools=("z",))
    run = _run(tools=("a", "z"))
    # coverage 1.0 - 0.25 penalty
    assert selection_score(task, run) == 0.75


def test_selection_no_expected_is_neutral():
    task = Task(id="t", prompt="p")
    assert selection_score(task, _run(tools=("anything",))) == 1.0


def test_first_tool_correct():
    task = Task(id="t", prompt="p", expected_tools=("a", "b"))
    assert first_tool_correct(task, _run(tools=("a", "b"))) is True
    assert first_tool_correct(task, _run(tools=("b", "a"))) is True
    assert first_tool_correct(task, _run(tools=("z", "a"))) is False
    assert first_tool_correct(task, _run(tools=())) is None


def test_confusion_counts_errors_and_retries():
    run = _run(tools=[ToolCall("a", ok=False), ToolCall("a", ok=True), ToolCall("b", ok=True)])
    sig = confusion_signals(run)
    assert sig["errored_calls"] == 1
    assert sig["retries"] == 1  # 'a' retried right after it errored


def test_confusion_forbidden():
    task = Task(id="t", prompt="p", forbidden_tools=("z",))
    run = _run(tools=("a", "z", "z"))
    assert confusion_signals(run, task)["forbidden_calls"] == 2


def test_path_consistency():
    runs = [_run(i=0, tools=("a", "b")), _run(i=1, tools=("a", "b")), _run(i=2, tools=("a",))]
    # 2 of 3 share the modal path
    assert abs(path_consistency(runs) - 2 / 3) < 1e-9


def test_outcome_consistency_flapping():
    runs = [_run(i=0, success=True), _run(i=1, success=False), _run(i=2, success=True)]
    assert abs(outcome_consistency(runs) - 2 / 3) < 1e-9


def test_crashed_runs_excluded_from_path_consistency():
    runs = [_run(i=0, tools=("a",)), _run(i=1, tools=("a",)), _run(i=2, crashed=True)]
    assert path_consistency(runs) == 1.0  # the two live runs agree


def test_score_task_aggregates():
    task = Task(id="t", prompt="p", expected_tools=("a",))
    runs = [
        _run(i=0, tools=("a",), success=True, turns=2, input_tokens=100, output_tokens=50),
        _run(i=1, tools=("a",), success=True, turns=3, input_tokens=120, output_tokens=40),
    ]
    s = score_task(task, runs)
    assert s.success_rate == 1.0
    assert s.first_tool_accuracy == 1.0
    assert s.selection_accuracy == 1.0
    assert s.mean_turns == 2.5
    assert s.mean_total_tokens == 155.0
    assert s.n_crashed == 0


def test_tool_usage_frequency():
    runs = [_run(tools=("a", "b")), _run(tools=("a",))]
    freq = tool_usage_frequency(runs)
    assert freq["a"] == 2 and freq["b"] == 1
