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


# --- error context (issue #32) ----------------------------------------------


async def test_middleware_records_upstream_status_and_detail(_fake_token):
    """A typed upstream error must land in the event as a real status + detail."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    class _UpstreamError(RuntimeError):
        def __init__(self):
            super().__init__("upstream companies_list returned 403 (request-id: req-1)")
            self.upstream_status = 403
            self.request_id = "req-1"

    async def call_next(_):
        raise _UpstreamError()

    with pytest.raises(_UpstreamError):
        await mw.on_call_tool(ctx, call_next)

    ev = emitter.events[0]
    assert ev["status"] == "error"
    assert ev["upstream_status"] == 403
    assert ev["upstream_request_id"] == "req-1"
    assert "returned 403" in ev["error_detail"]


async def test_middleware_error_detail_redacts_jwt(_fake_token):
    """A JWT-shaped substring in an exception message must never reach the DB."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4eHh4In0.c2lnbmF0dXJlLXh4eHg"

    async def call_next(_):
        raise RuntimeError(f"rejected bearer {jwt} by upstream")

    with pytest.raises(RuntimeError):
        await mw.on_call_tool(ctx, call_next)

    ev = emitter.events[0]
    assert jwt not in ev["error_detail"]
    assert "<redacted" in ev["error_detail"]


async def test_middleware_error_detail_truncated(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        raise RuntimeError("x" * 5000)

    with pytest.raises(RuntimeError):
        await mw.on_call_tool(ctx, call_next)

    assert len(emitter.events[0]["error_detail"]) <= 300


async def test_middleware_ok_event_has_blank_error_fields(_fake_token):
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        return "RESULT"

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    assert ev["upstream_status"] is None
    assert ev["error_detail"] == ""
    assert ev["upstream_request_id"] == ""


def test_error_detail_redacts_short_header_jwt():
    """JWT with a minimal header must still be redacted (eyJ-anchored regex)."""
    from src.usage_analytics import sanitize_error_detail

    short = "eyJhbGciOiJub25lIn0.eyJ4IjoxfQ.sig"
    out = sanitize_error_detail(f"rejected {short} upstream")
    assert short not in out
    assert "<redacted-jwt>" in out


def test_error_detail_keeps_module_paths():
    """Dotted module paths in exception text must NOT be falsely redacted —
    they are often the most diagnostic part of the message."""
    from src.usage_analytics import sanitize_error_detail

    msg = "call failed in financial_reports.server_module.dependencies at startup"
    assert sanitize_error_detail(msg) == msg


async def test_middleware_records_error_kind(_fake_token):
    """A typed upstream error's error_kind must land in the analytics event,
    so dashboards can GROUP BY failure class."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    class _UpstreamErr(RuntimeError):
        def __init__(self):
            super().__init__("upstream companies_list returned 403")
            self.upstream_status = 403
            self.request_id = None
            self.error_kind = "missing_profile"

    async def call_next(_):
        raise _UpstreamErr()

    with pytest.raises(_UpstreamErr):
        await mw.on_call_tool(ctx, call_next)

    ev = emitter.events[0]
    assert ev["error_kind"] == "missing_profile"


async def test_middleware_ok_event_has_blank_error_kind(_fake_token):
    """OK events must emit error_kind as '' (not null) for column stability."""
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        return "RESULT"

    await mw.on_call_tool(ctx, call_next)
    assert emitter.events[0]["error_kind"] == ""


# --- result metrics (Stage 1: result_count / has_data / response_bytes) ------

def test_result_metrics_list_envelope():
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"count": 2, "results": [{"id": 1}, {"id": 2}]})
    assert m["result_count"] == 2 and m["has_data"] is True and m["response_bytes"] > 0


def test_result_metrics_empty_search_has_no_data():
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"count": 0, "results": []})
    assert m["result_count"] == 0 and m["has_data"] is False


def test_result_metrics_financials_period_count_zero_has_no_data():
    # The US-financials gap: entity exists, but no structured data → has_data False.
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"company_id": 29734, "period_count": 0, "periods": []})
    assert m["result_count"] == 0 and m["has_data"] is False


def test_result_metrics_single_object_retrieve_has_data():
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"id": 3813, "name": "ASML Holding N.V."})
    assert m["result_count"] is None and m["has_data"] is True


def test_result_metrics_structured_content_attr_and_text_fallback():
    import types
    from src.usage_analytics import _result_metrics
    # FastMCP-style result object exposing structured_content
    res = types.SimpleNamespace(structured_content={"results": [1, 2, 3]})
    assert _result_metrics(res)["result_count"] == 3
    # plain string result → size only, never raises
    m = _result_metrics("plain text")
    assert m["response_bytes"] == len("plain text") and m["has_data"] is True
    # unparseable / None → all None + empty entities, no raise
    assert _result_metrics(None) == {"result_count": None, "has_data": None,
                                     "response_bytes": None, "returned_ids": [], "result_countries": []}


async def test_middleware_emits_result_metrics(_fake_token):
    import types
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _fake_context()

    async def call_next(_):
        return types.SimpleNamespace(structured_content={"count": 0, "results": []})

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    assert ev["result_count"] == 0
    assert ev["has_data"] is False
    assert ev["response_bytes"] is not None


# --- entities + geo + session_id (returned_ids / result_countries / session) -

def test_result_metrics_extracts_ids_and_countries():
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"results": [
        {"id": 3813, "country_code": "NL"}, {"id": 222, "country_code": "DE"}]})
    assert m["returned_ids"] == [3813, 222]
    assert m["result_countries"] == ["DE", "NL"]


def test_result_metrics_country_from_nested_company():
    # filings_list shape: country lives under a nested company object
    from src.usage_analytics import _result_metrics
    m = _result_metrics({"results": [{"id": 99, "company": {"id": 3813, "country_code": "nl"}}]})
    assert 99 in m["returned_ids"]
    assert m["result_countries"] == ["NL"]


def test_result_metrics_entities_default_empty():
    from src.usage_analytics import _result_metrics
    assert _result_metrics(None)["returned_ids"] == []
    assert _result_metrics("text")["result_countries"] == []


async def test_middleware_emits_session_id_and_entities(_fake_token):
    import types
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ci = types.SimpleNamespace(name="claude-ai", version="1.0")
    session = types.SimpleNamespace(client_params=types.SimpleNamespace(clientInfo=ci))
    ctx = types.SimpleNamespace(
        message=types.SimpleNamespace(name="companies_list", arguments={"search": "ASML"}),
        fastmcp_context=types.SimpleNamespace(session=session, session_id="sess-xyz"))

    async def call_next(_):
        return types.SimpleNamespace(structured_content={"results": [{"id": 3813, "country_code": "NL"}]})

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    assert ev["session_id"] == "sess-xyz"
    assert ev["returned_ids"] == [3813]
    assert ev["result_countries"] == ["NL"]


# --- request signals: mcp_meta + correlation_id + header-key discovery ----------

def _ctx_with_meta(meta_dict=None, session_id="", name="companies_list", arguments=None):
    """Context whose tool-call message carries a JSON-RPC _meta (as ChatGPT sends)."""
    import mcp.types as mt
    msg_meta = mt.RequestParams.Meta.model_validate(meta_dict) if meta_dict is not None else None
    message = types.SimpleNamespace(name=name, arguments=arguments or {}, meta=msg_meta)
    ci = types.SimpleNamespace(name="openai-mcp", version="1.0")
    session = types.SimpleNamespace(client_params=types.SimpleNamespace(clientInfo=ci))
    return types.SimpleNamespace(
        message=message,
        fastmcp_context=types.SimpleNamespace(session=session, session_id=session_id),
    )


def test_extract_meta_captures_openai_keys_excludes_user_location():
    import mcp.types as mt
    from src.usage_analytics import _extract_meta
    meta = mt.RequestParams.Meta.model_validate({
        "openai/session": "conv_1", "openai/subject": "user_1",
        "openai/userAgent": "ChatGPT", "openai/userLocation": "Jakarta",
        "progressToken": "p", "other/ns": "ignored",
    })
    out = _extract_meta(types.SimpleNamespace(meta=meta))
    assert out["openai/session"] == "conv_1"
    assert out["openai/userAgent"] == "ChatGPT"
    assert "openai/subject" not in out        # OpenAI account id excluded (cross-platform linkage)
    assert "openai/userLocation" not in out   # user geography deliberately excluded
    assert "progressToken" not in out         # non-namespaced metadata excluded
    assert "other/ns" not in out              # foreign namespace excluded


def test_extract_meta_missing_or_none_returns_empty():
    from src.usage_analytics import _extract_meta
    assert _extract_meta(types.SimpleNamespace(meta=None)) == {}
    assert _extract_meta(types.SimpleNamespace()) == {}


def test_extract_meta_value_truncated():
    import mcp.types as mt
    from src.usage_analytics import _extract_meta, _META_VAL_CAP
    meta = mt.RequestParams.Meta.model_validate({"openai/session": "x" * 1000})
    out = _extract_meta(types.SimpleNamespace(meta=meta))
    assert len(out["openai/session"]) == _META_VAL_CAP


def test_token_fingerprint_stable_salted_and_never_leaks_token(monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_access_token", lambda: types.SimpleNamespace(token="abc.def.ghi"))
    fp1, fp2 = ua._token_fingerprint(), ua._token_fingerprint()
    assert fp1 and fp1 == fp2 and len(fp1) == 32     # stable, fixed width
    assert "abc.def.ghi" not in fp1                   # raw token never present
    monkeypatch.setattr(ua, "get_access_token", lambda: types.SimpleNamespace(token="zzz"))
    assert ua._token_fingerprint() != fp1             # different token -> different fp


def test_token_fingerprint_empty_without_token(monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_access_token", lambda: None)
    assert ua._token_fingerprint() == ""
    monkeypatch.setattr(ua, "get_access_token", lambda: types.SimpleNamespace(claims={}))  # no .token
    assert ua._token_fingerprint() == ""


def test_header_keys_are_names_only(monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_http_headers",
                        lambda include_all=False: {"Authorization": "Bearer SECRET", "X-Request-Id": "r1"})
    keys = ua._http_header_keys()
    assert keys == ["authorization", "x-request-id"]              # lowercased, sorted, names only
    assert all("SECRET" not in k and "r1" not in k for k in keys)  # no values ever


async def test_correlation_prefers_openai_session(_fake_token, monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_http_headers", lambda include_all=False: {"host": "x"})
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _ctx_with_meta({"openai/session": "conv_42"}, session_id="mcp-sess-1")

    async def call_next(_):
        return "ok"

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    assert ev["correlation_id"] == "conv_42"               # openai/session beats Mcp-Session-Id
    assert ev["correlation_source"] == "meta:openai/session"
    assert ev["mcp_meta"]["openai/session"] == "conv_42"
    assert ev["request_header_keys"] == ["host"]


async def test_correlation_falls_back_session_then_token(_fake_token, monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_http_headers", lambda include_all=False: {})

    async def call_next(_):
        return "ok"

    # no meta, but Mcp-Session-Id present -> mcp_session
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    await mw.on_call_tool(_ctx_with_meta(None, session_id="mcp-sess-9"), call_next)
    ev = emitter.events[0]
    assert ev["correlation_id"] == "mcp-sess-9"
    assert ev["correlation_source"] == "mcp_session"
    assert ev["mcp_meta"] == {}

    # no meta, no session -> salted token fingerprint
    monkeypatch.setattr(ua, "get_access_token",
                        lambda: types.SimpleNamespace(claims={"sub": "s"}, token="tok-123"))
    emitter2 = _FakeEmitter()
    mw2 = UsageAnalyticsMiddleware(emitter2)
    await mw2.on_call_tool(_ctx_with_meta(None, session_id=""), call_next)
    ev2 = emitter2.events[0]
    assert ev2["correlation_source"] == "token_fp"
    assert ev2["correlation_id"] and len(ev2["correlation_id"]) == 32


async def test_request_signal_fields_present_on_every_call(_fake_token, monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_http_headers", lambda include_all=False: {"host": "x"})
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    # basic call: no _meta, no Mcp-Session-Id, fixture token has no .token -> all defaults
    ctx = _ctx_with_meta(None, session_id="")

    async def call_next(_):
        return "ok"

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    for f in ("correlation_id", "correlation_source", "mcp_meta", "request_header_keys"):
        assert f in ev                          # field is emitted on every call
    assert ev["mcp_meta"] == {}
    assert ev["request_header_keys"] == ["host"]
    assert ev["correlation_source"] == ""       # no meta, no session, no token fp -> empty source
    assert ev["correlation_id"] == ""


async def test_correlation_ignores_whitespace_session(_fake_token, monkeypatch):
    from src import usage_analytics as ua
    monkeypatch.setattr(ua, "get_http_headers", lambda include_all=False: {})
    emitter = _FakeEmitter()
    mw = UsageAnalyticsMiddleware(emitter)
    ctx = _ctx_with_meta({"openai/session": "   "}, session_id="mcp-sess-5")

    async def call_next(_):
        return "ok"

    await mw.on_call_tool(ctx, call_next)
    ev = emitter.events[0]
    # a whitespace-only session id must not win; it falls through to Mcp-Session-Id
    assert ev["correlation_id"] == "mcp-sess-5"
    assert ev["correlation_source"] == "mcp_session"
