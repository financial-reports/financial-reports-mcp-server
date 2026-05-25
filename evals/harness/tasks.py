"""Eval task schema + loader.

A task is a single analyst request with graded success criteria. Tasks are
plain YAML so non-engineers can add them. This module is pure (no network,
no LLM) so it is unit-testable without secrets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Task:
    """One eval task.

    Fields:
      id              stable slug, used in reports
      prompt          the user message handed to the model
      domain          tool domain (companies/filings/isin/isic/reference/...)
      expected_tools  tools a correct run SHOULD call (order-insensitive set)
      forbidden_tools tools a correct run should NOT call (confusion signal)
      assert_contains substrings the final answer MUST contain (deterministic
                      ground-truth check; empty => rely on the rubric judge)
      success_rubric  natural-language pass criteria for the LLM judge
    """

    id: str
    prompt: str
    domain: str = "general"
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    assert_contains: tuple[str, ...] = ()
    success_rubric: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Task":
        missing = [k for k in ("id", "prompt") if not d.get(k)]
        if missing:
            raise ValueError(f"task is missing required field(s): {', '.join(missing)}")
        return Task(
            id=str(d["id"]),
            prompt=str(d["prompt"]),
            domain=str(d.get("domain", "general")),
            expected_tools=tuple(d.get("expected_tools", []) or []),
            forbidden_tools=tuple(d.get("forbidden_tools", []) or []),
            assert_contains=tuple(d.get("assert_contains", []) or []),
            success_rubric=str(d.get("success_rubric", "")),
        )


def load_tasks(tasks_dir: str | Path) -> list[Task]:
    """Load every *.yaml task in a directory. Each file holds one task or a
    list of tasks under a top-level `tasks:` key. Raises on duplicate ids."""
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"tasks dir not found: {tasks_dir}")

    out: list[Task] = []
    seen: set[str] = set()
    for path in sorted(tasks_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        raw = doc.get("tasks", doc) if isinstance(doc, dict) else doc
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            task = Task.from_dict(item)
            if task.id in seen:
                raise ValueError(f"duplicate task id {task.id!r} (in {path.name})")
            seen.add(task.id)
            out.append(task)
    if not out:
        raise ValueError(f"no tasks found in {tasks_dir}")
    return out
