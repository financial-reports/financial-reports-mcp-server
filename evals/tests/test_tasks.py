"""Unit tests for task loading + the shipped seed task suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.tasks import Task, load_tasks  # noqa: E402

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"


def test_from_dict_requires_id_and_prompt():
    with pytest.raises(ValueError):
        Task.from_dict({"prompt": "x"})
    with pytest.raises(ValueError):
        Task.from_dict({"id": "x"})


def test_from_dict_defaults():
    t = Task.from_dict({"id": "a", "prompt": "p"})
    assert t.domain == "general"
    assert t.expected_tools == ()


def test_seed_tasks_load_and_are_unique():
    tasks = load_tasks(TASKS_DIR)
    assert len(tasks) >= 5
    ids = [t.id for t in tasks]
    assert len(ids) == len(set(ids))  # no dupes
    # every task has a rubric or a deterministic assert to grade against
    for t in tasks:
        assert t.success_rubric or t.assert_contains, f"{t.id} has no grading criteria"


def test_duplicate_ids_raise(tmp_path):
    (tmp_path / "a.yaml").write_text("tasks:\n  - {id: dup, prompt: x}\n")
    (tmp_path / "b.yaml").write_text("tasks:\n  - {id: dup, prompt: y}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(tmp_path)
