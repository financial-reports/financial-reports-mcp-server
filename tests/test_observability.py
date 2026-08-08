"""Correlation plumbing and Cloud Logging output (issue #77).

Three things pinned here:

1. `upstream_request_id` falls back to `cf-ray`. The upstream emits no
   `x-request-id` — probing five endpoints (200/403/404/schema/server-card) found
   zero occurrences of it or any equivalent, while `cf-ray` was present on all
   five. That is why the column sat at 0 of 31,445 rows: the MCP had been sending
   an id it never received. `cf-ray` is additionally already captured origin-side
   in nginx's access log (`ray=$http_cf_ray`), so it joins an MCPToolEvent row to
   a request line with no upstream change and no migration.

2. A per-call UUID is minted per tool call and forwarded upstream as
   `X-Client-Request-Id`, host-scoped like the auth header.

3. Cloud Logging gets single-line JSON, so a traceback stays ONE entry instead of
   N unrelated textPayload rows.
"""
from __future__ import annotations

import json
import logging
import sys

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _structured_tool(mcp_module, name="companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


async def _noop() -> None:
    return None


# --- 1. cf-ray fallback ------------------------------------------------------


def test_x_request_id_still_wins_when_present(mcp_module) -> None:
    """Ordering matters: stay correct if the monolith ever adds the header."""
    resp = httpx.Response(
        500, headers={"x-request-id": "req-abc", "cf-ray": "ray-xyz-FRA"}
    )
    assert mcp_module._upstream_request_id(resp) == "req-abc"


def test_cf_ray_is_used_when_x_request_id_is_absent(mcp_module) -> None:
    resp = httpx.Response(500, headers={"cf-ray": "a27ed888ac7a7aef-FRA"})
    assert mcp_module._upstream_request_id(resp) == "a27ed888ac7a7aef-FRA"


def test_blank_headers_are_treated_as_missing(mcp_module) -> None:
    """An empty header must not be persisted as a bogus id."""
    assert mcp_module._upstream_request_id(
        httpx.Response(500, headers={"x-request-id": "   "})
    ) is None
    assert mcp_module._upstream_request_id(httpx.Response(500)) is None


@pytest.mark.asyncio
async def test_typed_error_carries_cf_ray_as_request_id(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """End-to-end: the id reaches UpstreamHTTPError and the client-facing text."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(
            403, json={"detail": "nope"}, headers={"cf-ray": "deadbeefcafe-AMS"}
        )
    )

    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _structured_tool(mcp_module)()

    assert ei.value.request_id == "deadbeefcafe-AMS"
    assert "deadbeefcafe-AMS" in str(ei.value)


# --- 2. per-call correlation id ----------------------------------------------


def test_call_id_is_empty_outside_a_tool_call() -> None:
    from src.usage_analytics import current_call_id

    assert current_call_id() == ""


@pytest.mark.asyncio
async def test_correlation_header_is_forwarded_upstream(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    monkeypatch.setattr(mcp_module, "current_call_id", lambda: "cafef00d" * 4)
    captured: dict[str, str] = {}

    def _respond(request):
        captured["cid"] = request.headers.get("X-Client-Request-Id", "")
        return httpx.Response(200, json={"count": 0, "results": []})

    respx_router.get(f"{TEST_API_BASE}/companies/").mock(side_effect=_respond)

    await _structured_tool(mcp_module)()
    assert captured["cid"] == "cafef00d" * 4


@pytest.mark.asyncio
async def test_correlation_header_is_host_scoped(mcp_module, monkeypatch) -> None:
    """Our diagnostic id has no business reaching the CDN or any other host — the
    same scoping rule `_inject_auth` follows for the credential."""
    monkeypatch.setattr(mcp_module, "current_call_id", lambda: "abc123")

    foreign = httpx.Request("GET", "https://cdn.example.invalid/icon.png")
    await mcp_module._inject_correlation(foreign)
    assert "X-Client-Request-Id" not in foreign.headers

    ours = httpx.Request("GET", f"{TEST_API_BASE}/companies/")
    await mcp_module._inject_correlation(ours)
    assert ours.headers["X-Client-Request-Id"] == "abc123"


@pytest.mark.asyncio
async def test_no_correlation_header_outside_a_tool_call(mcp_module) -> None:
    """Boot-time calls — the startup self-check — have no call id to attach."""
    req = httpx.Request("GET", f"{TEST_API_BASE}/health/")
    await mcp_module._inject_correlation(req)
    assert "X-Client-Request-Id" not in req.headers


def test_header_name_uses_hyphens_not_underscores(mcp_module) -> None:
    """nginx silently drops headers containing underscores unless
    `underscores_in_headers` is enabled, and it is not. An underscored name would
    vanish before reaching gunicorn."""
    import inspect

    src = inspect.getsource(mcp_module._inject_correlation)
    assert "X-Client-Request-Id" in src
    assert "X_Client_Request_Id" not in src


@pytest.mark.asyncio
async def test_call_id_is_fresh_per_call_and_resets(monkeypatch) -> None:
    """Deliberately per-call, unlike `correlation_id` which spans a session."""
    from src import usage_analytics as ua

    seen: list[str] = []

    class _Ctx:
        message = type("M", (), {"name": "companies_list", "arguments": {}})()

    async def _call_next(_ctx):
        seen.append(ua.current_call_id())
        return None

    mw = ua.UsageAnalyticsMiddleware(emitter=None)
    monkeypatch.setattr(mw, "_resolve_client_info", lambda _c: _noop())
    monkeypatch.setattr(mw, "_safe_emit", lambda *a, **k: None)

    await mw.on_call_tool(_Ctx(), _call_next)
    await mw.on_call_tool(_Ctx(), _call_next)

    assert len(seen) == 2
    assert all(len(s) == 32 for s in seen)
    assert seen[0] != seen[1]
    # Reset afterwards, so an id never leaks into an unrelated context.
    assert ua.current_call_id() == ""


@pytest.mark.asyncio
async def test_event_payload_carries_client_request_id(monkeypatch) -> None:
    """The Django ingest serializer ignores unknown keys, so this ships safely
    ahead of the web-repo column."""
    from src import usage_analytics as ua

    class _Ctx:
        message = type("M", (), {"name": "companies_list", "arguments": {}})()

    captured: dict = {}

    mw = ua.UsageAnalyticsMiddleware(emitter=None)
    monkeypatch.setattr(mw, "_resolve_client_info", lambda _c: _noop())

    def _capture(context, **kwargs):
        captured.update(
            mw._build_event(
                context,
                kind=kwargs["kind"],
                status=kwargs["status"],
                err=kwargs["err"],
                latency_ms=kwargs["latency_ms"],
                result=kwargs.get("result"),
            )
        )

    monkeypatch.setattr(mw, "_safe_emit", _capture)

    async def _call_next(_ctx):
        return None

    await mw.on_call_tool(_Ctx(), _call_next)

    assert len(captured["client_request_id"]) == 32
    # The session-stitching field is a different thing and must still be present.
    assert "correlation_id" in captured


# --- 3. Cloud Logging output -------------------------------------------------


def test_structured_formatter_keeps_a_traceback_on_one_line(mcp_module) -> None:
    """The reason this formatter exists.

    Cloud Logging splits multi-line stdout into separate entries, so a plain
    traceback becomes N unrelated rows and Error Reporting gets no stack trace.
    Carrying the whole traceback as the JSON `message` string keeps it one entry —
    newlines escaped inside the string, one line of output.
    """
    formatter = mcp_module._StructuredLogFormatter("%(name)s: %(message)s")
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="financial-reports-mcp",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="upstream exploded",
            args=(),
            exc_info=sys.exc_info(),
        )

    out = formatter.format(record)
    assert "\n" not in out, "multi-line output would be split into separate entries"

    payload = json.loads(out)
    assert payload["severity"] == "ERROR"
    assert "Traceback (most recent call last)" in payload["message"]
    assert "ValueError: boom" in payload["message"]
    labels = payload["logging.googleapis.com/labels"]
    assert labels["logger"] == "financial-reports-mcp"


def test_structured_formatter_survives_a_non_serialisable_arg(mcp_module) -> None:
    """`default=str` keeps one odd log argument from taking the logging path down."""
    formatter = mcp_module._StructuredLogFormatter("%(message)s")
    record = logging.LogRecord(
        name="x",
        level=logging.WARNING,
        pathname="p",
        lineno=2,
        msg="value=%s",
        args=(object(),),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["severity"] == "WARNING"


def test_text_logging_is_the_default_off_cloud_run(mcp_module, monkeypatch) -> None:
    """Self-hosters must not be forced into JSON. K_SERVICE is Cloud Run's marker;
    LOG_FORMAT=json forces it anywhere."""
    import importlib

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    importlib.reload(mcp_module)
    handler = logging.getLogger().handlers[0]
    assert not isinstance(handler.formatter, mcp_module._StructuredLogFormatter)

    monkeypatch.setenv("LOG_FORMAT", "json")
    importlib.reload(mcp_module)
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler.formatter, mcp_module._StructuredLogFormatter)
