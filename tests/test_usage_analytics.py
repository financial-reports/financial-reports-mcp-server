"""Tests for the usage-analytics capture middleware + emitter.

The middleware must (a) sanitize arguments so secrets never leave the process,
(b) hand a well-formed event to the emitter, and (c) never break a tool call.
The emitter must be non-blocking, drop-on-full, and inert unless configured.
"""
from __future__ import annotations

import types

import httpx
import pytest
import respx

from src import usage_analytics
from src.usage_analytics import (
    REDACTED,
    UsageAnalyticsEmitter,
    UsageAnalyticsMiddleware,
    sanitize_mcp_arguments,
)

INGEST_URL = "https://api.test.invalid/api/internal/mcp-events/"
TOKEN = "secret-token"


# --- sanitization -----------------------------------------------------------

def test_allowlisted_values_kept():
    assert sanitize_mcp_arguments({"search": "Apple", "filing_type_code": "10-K"}) == {
        "search": "Apple", "filing_type_code": "10-K",
    }


def test_unknown_and_secretish_keys_redacted():
    out = sanitize_mcp_arguments({
        "mystery": "x", "target_url": "https://h", "secret": "s", "api_key": "k",
    })
    assert out == {
        "mystery": REDACTED, "target_url": REDACTED, "secret": REDACTED, "api_key": REDACTED,
    }


def test_long_value_truncated_and_non_dict_empty():
    assert len(sanitize_mcp_arguments({"search": "x" * 999})["search"]) == 256
    assert sanitize_mcp_arguments(None) == {}


# --- emitter ----------------------------------------------------------------

def test_emitter_inert_without_config():
    emitter = UsageAnalyticsEmitter("", "")
    assert emitter.enabled is False
    emitter.emit({"name": "x"})  # no-op, must not raise


def test_emitter_drops_when_full():
    emitter = UsageAnalyticsEmitter(INGEST_URL, TOKEN, queue_size=1)
    # No worker started -> nothing drains the queue.
    emitter.emit({"name": "a"})
    emitter.emit({"name": "b"})  # dropped
    emitter.emit({"name": "c"})  # dropped
    assert emitter._dropped == 2


async def test_emitter_posts_event():
    async with respx.mock:
        route = respx.post(INGEST_URL).mock(return_value=httpx.Response(202))
        emitter = UsageAnalyticsEmitter(INGEST_URL, TOKEN)
        await emitter.start()
        emitter.emit({"name": "companies_list", "ts": 1.0})
        await emitter._queue.join()  # wait until the worker drains it
        await emitter.aclose()

    assert route.called
    request = route.calls.last.request
    assert request.headers["X-Internal-Token"] == TOKEN
    assert b"companies_list" in request.content


# --- middleware -------------------------------------------------------------

class _FakeEmitter:
    def __init__(self):
        self.events = []
        self.enabled = True

    def emit(self, event):
        self.events.append(event)


def _fake_context(name="companies_list", arguments=None):
    client_info = types.SimpleNamespace(name="claude-ai", version="1.0")
    session = types.SimpleNamespace(client_params=types.SimpleNamespace(clientInfo=client_info))
    return types.SimpleNamespace(
        message=types.SimpleNamespace(name=name, arguments=arguments or {}),
        fastmcp_context=types.SimpleNamespace(session=session),
    )


@pytest.fixture
def _fake_token(monkeypatch):
    token = types.SimpleNamespace(claims={"sub": "sub-1", "client_id": "cid-1"}, client_id="cid-1")
    monkeypatch.setattr(usage_analytics, "get_access_token", lambda: token)
    return token


async def test_middleware_captures_tool_call(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter, server_version="v1.2.3")
    ctx = _fake_context(arguments={"search": "Apple", "secret": "leak"})

    async def call_next(_):
        return "RESULT"

    result = await mw.on_call_tool(ctx, call_next)

    assert result == "RESULT"
    assert len(emitter.events) == 1
    ev = emitter.events[0]
    assert ev["kind"] == "tool"
    assert ev["name"] == "companies_list"
    assert ev["status"] == "ok"
    assert ev["sub"] == "sub-1"
    assert ev["client_id"] == "cid-1"
    assert ev["host_name"] == "claude-ai"
    assert ev["server_version"] == "v1.2.3"
    assert ev["arguments"] == {"search": "Apple", "secret": REDACTED}


async def test_middleware_records_error_and_reraises(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await mw.on_call_tool(ctx, call_next)

    assert emitter.events[0]["status"] == "error"
    assert emitter.events[0]["error_type"] == "ValueError"


async def test_middleware_captures_prompt(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context(name="find_filing_section", arguments={"section_keyword": "going concern"})

    async def call_next(_):
        return "PROMPT"

    await mw.on_get_prompt(ctx, call_next)
    ev = emitter.events[0]
    assert ev["kind"] == "prompt"
    assert ev["name"] == "find_filing_section"
    assert ev["arguments"] == {"section_keyword": "going concern"}


async def test_middleware_prompt_records_error_and_reraises(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context(name="summarize_recent_filings")

    async def call_next(_):
        raise RuntimeError("prompt failure")

    with pytest.raises(RuntimeError):
        await mw.on_get_prompt(ctx, call_next)

    assert emitter.events[0]["status"] == "error"
    assert emitter.events[0]["error_type"] == "RuntimeError"


async def test_middleware_survives_missing_identity():
    """No access token + no session -> event still emitted with blank identity."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = types.SimpleNamespace(
        message=types.SimpleNamespace(name="countries_list", arguments={}),
        fastmcp_context=None,
    )

    async def call_next(_):
        return "RESULT"

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    assert ev["sub"] == ""
    assert ev["host_name"] == ""
