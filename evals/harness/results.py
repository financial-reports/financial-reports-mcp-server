"""Run-result data model — what one execution of a task produces.

Kept separate from scoring so the model adapters (which import this) don't
pull in scoring logic, and so both are independently testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCall:
    name: str
    ok: bool = True          # False when the tool returned isError / raised
    error: str | None = None


@dataclass
class RunResult:
    task_id: str
    model: str
    run_index: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    # success is graded post-hoc (deterministic asserts and/or LLM judge)
    success: bool | None = None
    success_reason: str = ""
    # populated when the run itself errored (network, auth, adapter bug)
    crashed: bool = False
    crash_reason: str = ""

    @property
    def tool_sequence(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.tool_calls)
