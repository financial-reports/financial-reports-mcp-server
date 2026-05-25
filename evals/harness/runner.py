"""Orchestration: for each model × task × N runs, execute through the shared
MCP session, grade, and return raw results for scoring/reporting."""
from __future__ import annotations

from .grader import ClaudeJudge, deterministic_pass
from .mcp_client import ToolSpec, open_mcp
from .models import ModelAdapter
from .results import RunResult
from .tasks import Task


async def _grade(task: Task, run: RunResult, judge: ClaudeJudge | None) -> None:
    if run.crashed:
        return
    det = deterministic_pass(task, run.final_text)
    if det is False:
        run.success, run.success_reason = False, "missing required substring"
        return
    if task.success_rubric and judge is not None:
        run.success, run.success_reason = await judge.judge(task, run.final_text)
        return
    if det is True:
        run.success, run.success_reason = True, "assert_contains matched"
    else:
        run.success, run.success_reason = None, "no grader available"


async def run_eval(
    *,
    adapters: list[ModelAdapter],
    tasks: list[Task],
    n_runs: int,
    mcp_url: str,
    token: str,
    judge: ClaudeJudge | None,
) -> tuple[dict[tuple[str, str], list[RunResult]], list[ToolSpec]]:
    """Returns {(model_name, task_id): [RunResult, ...]} and the tool catalog."""
    results: dict[tuple[str, str], list[RunResult]] = {}
    async with open_mcp(mcp_url, token) as mcp:
        tools = await mcp.list_tools()
        for adapter in adapters:
            for task in tasks:
                runs: list[RunResult] = []
                for i in range(n_runs):
                    run = await adapter.run(task.id, i, task.prompt, tools, mcp)
                    await _grade(task, run, judge)
                    runs.append(run)
                results[(adapter.name, task.id)] = runs
    return results, tools
