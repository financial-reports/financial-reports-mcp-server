"""`error_kind` must survive the trip to analytics (issue #73 secondary finding).

Measured in prod: `error_kind` is the empty string on all 31,399 rows, all time —
the column has never carried a triage signal. Two independent causes:

  1. **Structured path.** FastMCP's tool manager catches the tool's exception and
     re-raises it wrapped in a generic `ToolError`
     (`fastmcp/tools/tool_manager.py`, `raise ToolError(...) from e`). The
     middleware sits outside the tool manager, so `_ErrorInfo.from_exception`
     receives the *wrapper*, which has no `error_kind` / `upstream_status` /
     `request_id`. Consequence: every structured-tool upstream failure is filed
     as a bare `ToolError` with a NULL `upstream_status` — which is why 30 days
     of prod data shows 4,319 "ToolError" rows that are really 429s and 403s,
     and why the 429 count in #73 was 5x low.

  2. **Text path.** `record_tool_error` had no `error_kind` parameter at all, so
     `_ErrorInfo.from_recorded` always fell through to the dataclass default.

Both are pinned here. The existing `test_middleware_records_error_kind` in
test_usage_analytics.py hand-drives `call_next` with a raw exception, so it
never observed cause 1 — the real-dispatch test below is the one that does.
"""
from __future__ import annotations

import types

import httpx
import pytest

from src import usage_analytics
from src.usage_analytics import UsageAnalyticsMiddleware, record_tool_error

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


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


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


# --- cause 1: unwrap the ToolError the tool manager raised `from` our error ---


async def test_wrapped_upstream_error_still_yields_error_kind(_fake_token) -> None:
    """A typed error re-raised as `ToolError(...) from exc` must not lose its
    classification — the middleware has to look one `__cause__` link down."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    class _UpstreamErr(RuntimeError):
        def __init__(self):
            super().__init__("upstream companies_list returned 429")
            self.upstream_status = 429
            self.request_id = "req-abc"
            self.error_kind = "quota_exhausted"

    class _ToolError(RuntimeError):
        """Stands in for fastmcp.exceptions.ToolError — no upstream attributes."""

    async def call_next(_):
        try:
            raise _UpstreamErr()
        except _UpstreamErr as exc:
            raise _ToolError(f"Error calling tool 'companies_list': {exc}") from exc

    with pytest.raises(_ToolError):
        await mw.on_call_tool(_fake_context(), call_next)

    ev = emitter.events[0]
    assert ev["error_kind"] == "quota_exhausted"
    assert ev["upstream_status"] == 429
    assert ev["upstream_request_id"] == "req-abc"


async def test_unwrap_does_not_override_attributes_on_the_outer_error(_fake_token) -> None:
    """If the outer exception carries its own context, it wins — unwrapping is a
    fallback for the wrapper case, not a blanket preference for the cause."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    class _Inner(RuntimeError):
        def __init__(self):
            super().__init__("inner")
            self.error_kind = "transient"
            self.upstream_status = 503

    class _Outer(RuntimeError):
        def __init__(self):
            super().__init__("outer")
            self.error_kind = "quota_exhausted"
            self.upstream_status = 429

    async def call_next(_):
        try:
            raise _Inner()
        except _Inner as exc:
            raise _Outer() from exc

    with pytest.raises(_Outer):
        await mw.on_call_tool(_fake_context(), call_next)

    ev = emitter.events[0]
    assert ev["error_kind"] == "quota_exhausted"
    assert ev["upstream_status"] == 429


async def test_unwrap_stops_at_one_link(_fake_token) -> None:
    """Walk exactly one `__cause__`. Deeper chains are someone else's bug and
    must not turn an unrelated inner exception into our classification."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    class _Deep(RuntimeError):
        def __init__(self):
            super().__init__("deep")
            self.error_kind = "quota_exhausted"
            self.upstream_status = 429

    class _Mid(RuntimeError):
        pass

    class _Top(RuntimeError):
        pass

    async def call_next(_):
        try:
            try:
                raise _Deep()
            except _Deep as deep:
                raise _Mid("mid") from deep
        except _Mid as mid:
            raise _Top("top") from mid

    with pytest.raises(_Top):
        await mw.on_call_tool(_fake_context(), call_next)

    ev = emitter.events[0]
    assert ev["error_kind"] == ""
    assert ev["upstream_status"] is None


async def test_error_type_still_names_the_raised_exception(_fake_token) -> None:
    """Unwrapping recovers *context*, not identity: `error_type` must keep
    naming what was actually raised, or the taxonomy stops matching the logs."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    class _Inner(RuntimeError):
        def __init__(self):
            super().__init__("inner")
            self.error_kind = "burst_limit"
            self.upstream_status = 429

    class _ToolError(RuntimeError):
        pass

    async def call_next(_):
        try:
            raise _Inner()
        except _Inner as exc:
            raise _ToolError("wrapped") from exc

    with pytest.raises(_ToolError):
        await mw.on_call_tool(_fake_context(), call_next)

    assert emitter.events[0]["error_type"] == "_ToolError"
    assert emitter.events[0]["error_kind"] == "burst_limit"


# --- cause 2: record_tool_error must be able to carry a kind -----------------


async def test_recorded_tool_error_carries_error_kind(_fake_token) -> None:
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    async def call_next(_):
        record_tool_error(
            "UpstreamHTTPError",
            "429 Too Many Requests",
            upstream_status=429,
            error_kind="quota_exhausted",
        )
        return "Error 429: ..."

    await mw.on_call_tool(_fake_context(name="filing_types_list"), call_next)

    ev = emitter.events[0]
    assert ev["status"] == "error"
    assert ev["error_kind"] == "quota_exhausted"


async def test_recorded_tool_error_without_kind_stays_blank(_fake_token) -> None:
    """Column stability: absent classification is '', never None."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)

    async def call_next(_):
        record_tool_error("ResponseFormatError", "boom")
        return "Error formatting response: boom"

    await mw.on_call_tool(_fake_context(name="filing_types_list"), call_next)
    assert emitter.events[0]["error_kind"] == ""


# --- the end-to-end proof, through REAL FastMCP dispatch ---------------------


@pytest.mark.asyncio
async def test_structured_429_reaches_analytics_with_kind_through_real_dispatch(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The regression test for the prod defect: drive a structured tool through
    the real FastMCP middleware chain (which really does wrap in ToolError) and
    assert the analytics event still knows this was a quota 429.

    Fails on main — `error_kind` arrives blank and `upstream_status` NULL.
    """
    from fastmcp import Client

    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            429,
            json={
                "type": "quota_limit_exceeded",
                "message": "You have used all 500 API credits included with your plan this month.",
                "resolution": (
                    "Enable pay-as-you-go billing at "
                    "https://financialreports.eu/accounts/payg/"
                ),
                "payg_url": "https://financialreports.eu/accounts/payg/",
            },
        )
    )
    captured: list[dict] = []
    monkeypatch.setattr(mcp_module._usage_emitter, "emit", lambda ev: captured.append(ev))

    async with Client(mcp_module.mcp) as client:
        with pytest.raises(Exception):
            await client.call_tool("companies_list", {})

    events = [e for e in captured if e["name"] == "companies_list" and e["kind"] == "tool"]
    assert events, "no analytics event captured for the tool call"
    ev = events[-1]
    assert ev["status"] == "error"
    assert ev["upstream_status"] == 429, "structured-path upstream_status still NULL"
    assert ev["error_kind"] == "quota_exhausted", "structured-path error_kind still blank"
