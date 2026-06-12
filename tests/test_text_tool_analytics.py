"""Text-tool failures must be visible to analytics (#40 §1, issue #32).

Text tools return their error as a *successful string* (no exception), so the
middleware would record `status="ok"` and the dashboard error rate would be
structurally understated. The fix: a tool error-helper records structured error
context in a contextvar (`record_tool_error`), and `on_call_tool` folds it into
the event when the call returned normally.

Coverage:
  1. set-site — a text tool hitting a mocked upstream 500 records into the var.
  2. fold — the middleware promotes a recorded error to `status="error"`.
  3. isolation — a recorded error from one call never leaks into the next.
  4. **propagation (the load-bearing one)** — the whole chain works through the
     REAL FastMCP middleware dispatch via the in-memory Client, not a hand-driven
     `call_next`. This is #40's flagged "riskiest assumption".
"""
from __future__ import annotations

import types

import httpx
import pytest

from src import usage_analytics
from src.usage_analytics import UsageAnalyticsMiddleware, record_tool_error

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _text_tool(mcp_module, name="filing_types_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


class _FakeEmitter:
    def __init__(self):
        self.events = []
        self.enabled = True

    def emit(self, event):
        self.events.append(event)


def _fake_context(name="filing_types_list", arguments=None):
    client_info = types.SimpleNamespace(name="claude-ai", version="1.0")
    session = types.SimpleNamespace(client_params=types.SimpleNamespace(clientInfo=client_info))
    return types.SimpleNamespace(
        message=types.SimpleNamespace(name=name, arguments=arguments or {}),
        fastmcp_context=types.SimpleNamespace(session=session),
    )


# --- 1. set-site: the tool records when it returns an error string -----------

@pytest.mark.asyncio
async def test_text_tool_upstream_500_records_into_contextvar(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    usage_analytics._tool_error.set(None)
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(500, text="upstream boom")
    )

    out = await _text_tool(mcp_module)()
    # The tool returns an error STRING (it does not raise) ...
    assert isinstance(out, str) and "500" in out
    # ... and it recorded structured context for the middleware to fold.
    recorded = usage_analytics._tool_error.get()
    assert recorded is not None
    assert recorded["upstream_status"] == 500


# --- 2. fold: the middleware promotes a recorded error -----------------------

@pytest.mark.asyncio
async def test_middleware_folds_recorded_text_error(monkeypatch) -> None:
    monkeypatch.setattr(usage_analytics, "get_access_token", lambda: None)
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        record_tool_error("UpstreamHTTPError", "503 Service Unavailable", upstream_status=503)
        return "Error 503 ...: upstream blip"  # text tool: error as a normal result

    out = await mw.on_call_tool(ctx, call_next)

    assert out.startswith("Error 503")
    ev = emitter.events[0]
    assert ev["status"] == "error"          # promoted from "ok"
    assert ev["upstream_status"] == 503
    assert ev["error_type"] == "UpstreamHTTPError"


# --- 3. isolation: a recorded error must not leak into the next call ---------

@pytest.mark.asyncio
async def test_recorded_error_does_not_leak_to_next_clean_call(monkeypatch) -> None:
    monkeypatch.setattr(usage_analytics, "get_access_token", lambda: None)
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    async def failing(_):
        record_tool_error("UpstreamHTTPError", "500", upstream_status=500)
        return "Error 500"

    async def clean(_):
        return "ok result"

    await mw.on_call_tool(_fake_context(), failing)
    await mw.on_call_tool(_fake_context(), clean)  # must NOT inherit the prior error

    assert emitter.events[0]["status"] == "error"
    assert emitter.events[1]["status"] == "ok"
    assert emitter.events[1]["upstream_status"] is None


# --- 4. propagation through REAL FastMCP dispatch (the load-bearing test) -----

@pytest.mark.asyncio
async def test_text_tool_error_visible_to_analytics_through_real_middleware(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """#40 §1 riskiest assumption: a contextvar set inside the tool reaches the
    middleware via the real FastMCP dispatch, so a text-tool upstream failure is
    recorded `status="error"` end-to-end (not via a hand-driven call_next)."""
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(500, text="upstream boom")
    )
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        await client.call_tool("filing_types_list", {})

    events = [e for e in captured if e["name"] == "filing_types_list" and e["kind"] == "tool"]
    assert events, "no analytics event captured for the tool call"
    ev = events[-1]
    assert ev["status"] == "error", f"text-tool 500 still recorded as {ev['status']!r}"
    assert ev["upstream_status"] == 500
