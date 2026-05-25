"""Unit tests for the pure grading logic (no LLM call)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.grader import _parse_verdict, deterministic_pass  # noqa: E402
from harness.tasks import Task  # noqa: E402


def test_deterministic_none_when_no_asserts():
    assert deterministic_pass(Task(id="t", prompt="p"), "anything") is None


def test_deterministic_all_substrings_present():
    task = Task(id="t", prompt="p", assert_contains=("Apple", "US0378331005"))
    assert deterministic_pass(task, "That ISIN US0378331005 is Apple Inc.") is True


def test_deterministic_case_insensitive_and_missing():
    task = Task(id="t", prompt="p", assert_contains=("apple",))
    assert deterministic_pass(task, "APPLE INC") is True
    assert deterministic_pass(task, "Microsoft") is False


def test_parse_verdict_clean_json():
    assert _parse_verdict('{"pass": true, "reason": "ok"}') == (True, "ok")


def test_parse_verdict_wrapped_in_prose():
    ok, reason = _parse_verdict('Sure!\n{"pass": false, "reason": "fabricated"} done')
    assert ok is False and reason == "fabricated"


def test_parse_verdict_garbage_fails_closed():
    ok, _ = _parse_verdict("no json here")
    assert ok is False
