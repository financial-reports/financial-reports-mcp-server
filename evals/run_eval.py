#!/usr/bin/env python3
"""CLI entrypoint for the FinancialReports MCP eval harness.

Examples:
    # Claude only, 3 runs/task
    python run_eval.py --models claude --runs 3

    # Claude + DeepSeek V4 Flash (Ollama Cloud), 5 runs/task
    python run_eval.py --models claude,deepseek --runs 5

Env (see .env.example):
    FR_MCP_URL            default https://mcp.financialfilings.com/mcp
    FR_MCP_TOKEN          bearer token for the MCP (required) — see README token paths
    ANTHROPIC_API_KEY     for the Claude adapter and/or the judge
    CLAUDE_MODEL          default claude-opus-4-7
    OLLAMA_API_KEY        for the DeepSeek/Ollama adapter
    OLLAMA_BASE_URL       default https://ollama.com/v1
    OLLAMA_MODEL          default deepseek-v4-flash:cloud
    JUDGE                 claude (default) | none
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.grader import ClaudeJudge  # noqa: E402
from harness.models import ClaudeAdapter, ModelAdapter, OpenAICompatAdapter  # noqa: E402
from harness.report import build_report, write_report  # noqa: E402
from harness.runner import run_eval  # noqa: E402
from harness.tasks import load_tasks  # noqa: E402


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"ERROR: ${name} is not set (see evals/.env.example).")
    return val


def build_adapters(selected: list[str]) -> list[ModelAdapter]:
    adapters: list[ModelAdapter] = []
    for m in selected:
        m = m.strip().lower()
        if m == "claude":
            adapters.append(ClaudeAdapter(
                model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
                api_key=_require("ANTHROPIC_API_KEY"),
            ))
        elif m in ("deepseek", "ollama"):
            adapters.append(OpenAICompatAdapter(
                model=os.environ.get("OLLAMA_MODEL", "deepseek-v4-flash:cloud"),
                api_key=_require("OLLAMA_API_KEY"),
                base_url=os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1"),
            ))
        else:
            sys.exit(f"ERROR: unknown model '{m}' (use claude / deepseek).")
    return adapters


async def _main(args: argparse.Namespace) -> None:
    tasks = load_tasks(args.tasks_dir)
    adapters = build_adapters(args.models.split(","))
    judge = None
    if args.judge == "claude":
        judge = ClaudeJudge(
            model=os.environ.get("JUDGE_MODEL", "claude-opus-4-7"),
            api_key=_require("ANTHROPIC_API_KEY"),
        )
    results, tools = await run_eval(
        adapters=adapters, tasks=tasks, n_runs=args.runs,
        mcp_url=os.environ.get("FR_MCP_URL", "https://mcp.financialfilings.com/mcp"),
        token=_require("FR_MCP_TOKEN"), judge=judge,
    )
    md, payload = build_report(results, tasks, tools)
    md_path, json_path = write_report(md, payload, args.out_dir)
    print(md)
    print(f"\nWrote {md_path} and {json_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="FinancialReports MCP eval harness")
    p.add_argument("--models", default="claude", help="comma list: claude,deepseek")
    p.add_argument("--runs", type=int, default=3, help="runs per task (variability)")
    p.add_argument("--tasks-dir", default=str(Path(__file__).parent / "tasks"))
    p.add_argument("--out-dir", default=str(Path(__file__).parent / "out"))
    p.add_argument("--judge", choices=["claude", "none"], default="claude")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
