"""Model adapters. Each runs ONE task through an agentic tool-use loop against
the shared MCP session, so every model is measured through identical machinery.

Deliberately minimal system prompt: we are benchmarking how well a model
operates the MCP's *own* tool descriptions, not how well a hand-written skill
coaches it. Don't inject the skill content here.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod

from .mcp_client import MCPSession, ToolSpec
from .results import RunResult, ToolCall

MAX_TURNS = 12
SYSTEM_PROMPT = (
    "You are a financial-research assistant with access to the FinancialReports "
    "tools. Use them to answer the user's question with real data. If the question "
    "is outside what these tools provide, say so plainly instead of guessing."
)


class ModelAdapter(ABC):
    name: str

    @abstractmethod
    async def run(self, task_id: str, run_index: int, prompt: str,
                  tools: list[ToolSpec], mcp: MCPSession) -> RunResult: ...


class ClaudeAdapter(ModelAdapter):
    def __init__(self, model: str, api_key: str, max_tokens: int = 4096):
        from anthropic import AsyncAnthropic
        self.name = model
        self._model = model
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key)

    async def run(self, task_id, run_index, prompt, tools, mcp) -> RunResult:
        result = RunResult(task_id=task_id, model=self.name, run_index=run_index)
        anth_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        messages: list = [{"role": "user", "content": prompt}]
        t0 = time.monotonic()
        try:
            for _ in range(MAX_TURNS):
                result.turns += 1
                resp = await self._client.messages.create(
                    model=self._model, max_tokens=self._max_tokens,
                    system=SYSTEM_PROMPT, tools=anth_tools, messages=messages,
                )
                result.input_tokens += resp.usage.input_tokens
                result.output_tokens += resp.usage.output_tokens
                messages.append({"role": "assistant", "content": resp.content})
                tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                if not tool_uses:
                    result.final_text = "".join(
                        b.text for b in resp.content if getattr(b, "type", None) == "text"
                    )
                    break
                tool_results = []
                for tu in tool_uses:
                    text, ok = await mcp.call_tool(tu.name, tu.input or {})
                    result.tool_calls.append(ToolCall(tu.name, ok=ok, error=None if ok else text[:200]))
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tu.id,
                        "content": text, "is_error": not ok,
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                result.final_text = "(max turns reached)"
        except Exception as exc:  # adapter/network/auth failure — not a model failure
            result.crashed = True
            result.crash_reason = f"{type(exc).__name__}: {exc}"
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result


class OpenAICompatAdapter(ModelAdapter):
    """Works for any OpenAI-compatible endpoint — used here for DeepSeek V4
    Flash via Ollama Cloud (base_url=https://ollama.com/v1). Honors the pi
    fleet's compat flags: no `developer` role, no `reasoning_effort`."""

    def __init__(self, model: str, api_key: str, base_url: str, max_tokens: int = 4096):
        from openai import AsyncOpenAI
        self.name = model
        self._model = model
        self._max_tokens = max_tokens
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def run(self, task_id, run_index, prompt, tools, mcp) -> RunResult:
        result = RunResult(task_id=task_id, model=self.name, run_index=run_index)
        oai_tools = [
            {"type": "function", "function": {
                "name": t.name, "description": t.description[:1024], "parameters": t.input_schema,
            }}
            for t in tools
        ]
        messages: list = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        t0 = time.monotonic()
        try:
            for _ in range(MAX_TURNS):
                result.turns += 1
                resp = await self._client.chat.completions.create(
                    model=self._model, messages=messages, tools=oai_tools,
                    tool_choice="auto", max_tokens=self._max_tokens,
                )
                if resp.usage:
                    result.input_tokens += resp.usage.prompt_tokens or 0
                    result.output_tokens += resp.usage.completion_tokens or 0
                msg = resp.choices[0].message
                messages.append(msg.model_dump(exclude_none=True))
                if not msg.tool_calls:
                    result.final_text = msg.content or ""
                    break
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    text, ok = await mcp.call_tool(tc.function.name, args)
                    result.tool_calls.append(
                        ToolCall(tc.function.name, ok=ok, error=None if ok else text[:200])
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            else:
                result.final_text = "(max turns reached)"
        except Exception as exc:
            result.crashed = True
            result.crash_reason = f"{type(exc).__name__}: {exc}"
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result
