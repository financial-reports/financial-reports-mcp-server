"""Success grading: cheap deterministic asserts first, LLM judge for the rest.

The judge is a separate, tool-less model call so grading is decoupled from the
model under test. Use a strong model as judge (Claude by default); it can also
be the same Ollama model if you'd rather not spend Claude tokens.
"""
from __future__ import annotations

import json

from .tasks import Task


def deterministic_pass(task: Task, final_text: str) -> bool | None:
    """True/False if the task declares assert_contains substrings; None if it
    relies solely on the rubric judge. Case-insensitive substring match."""
    if not task.assert_contains:
        return None
    hay = (final_text or "").lower()
    return all(sub.lower() in hay for sub in task.assert_contains)


_JUDGE_PROMPT = """You are grading whether an AI assistant's answer satisfies a rubric.

TASK PROMPT:
{prompt}

PASS RUBRIC:
{rubric}

ASSISTANT'S ANSWER:
{answer}

Reply with ONLY a JSON object: {{"pass": true|false, "reason": "<=20 words"}}.
Judge strictly against the rubric. Fabricated or hedged answers fail."""


class ClaudeJudge:
    def __init__(self, model: str, api_key: str):
        from anthropic import AsyncAnthropic
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def judge(self, task: Task, final_text: str) -> tuple[bool, str]:
        prompt = _JUDGE_PROMPT.format(
            prompt=task.prompt, rubric=task.success_rubric, answer=final_text or "(empty)"
        )
        resp = await self._client.messages.create(
            model=self._model, max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _parse_verdict(text)


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Tolerant JSON extraction — models sometimes wrap JSON in prose."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
        return bool(obj.get("pass", False)), str(obj.get("reason", ""))[:120]
    except (ValueError, json.JSONDecodeError):
        return False, f"unparseable judge output: {text[:80]}"
