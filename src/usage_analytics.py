"""Usage-analytics capture for the FinancialReports MCP server.

A FastMCP server middleware records every tool/prompt invocation —
``{sub, client_id, host, tool name, sanitized arguments, status, latency}`` —
and fire-and-forwards it to the web backend's internal ingest endpoint
(``POST /api/internal/mcp-events/``). The MCP server never sees the raw user
prompt, so the typed arguments are the closest proxy for intent.

Hard guarantees:
  * Capture NEVER adds latency to, or fails, a real tool call. Emission is a
    non-blocking enqueue onto a bounded queue, drained by a background worker;
    if the queue is full or the backend is down, events are DROPPED, not retried
    inline.
  * Arguments are sanitized here (allowlist values, redact everything else) so
    secrets (webhook target_url / secret) never leave this process. The backend
    re-applies the same denylist (defence in depth).
  * Inert unless BOTH ``MCP_ANALYTICS_INGEST_URL`` and ``MCP_INGEST_SHARED_SECRET``
    are configured.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger(__name__)

# --- argument sanitization (kept in sync with users.mcp_analytics on the backend) ---

ALLOWED_ARG_KEYS = frozenset({
    "search", "ticker", "isin", "lei",
    "filing_type_code", "filing_category", "category",
    "line_items", "section_keyword",
    "fiscal_year", "fiscal_period", "current_fiscal_year", "prior_fiscal_year",
    "countries", "country", "sector", "industry", "industry_group", "sub_industry",
    "ordering", "view", "on_watchlist",
    "id", "company_id", "filing_id", "ticker_or_name",
    "page", "page_size",
})

DENY_ARG_SUBSTRINGS = (
    "secret", "token", "password", "authorization", "auth",
    "url", "uri", "endpoint", "signing", "api_key", "apikey",
    "credential", "bearer", "private", "cert",
)
# NOTE: deliberately NOT a bare "key" — it would redact the legitimate
# "section_keyword" intent field. "api_key"/"apikey" cover the secret case.

REDACTED = "<redacted>"
MAX_ARG_STRLEN = 256
MAX_ARG_KEYS = 40

# Error-detail capture (issue #32): the exception *message* is the part the
# dashboard was missing — but it may quote a credential, so scrub anything
# JWT- or bearer-shaped before it leaves the process.
MAX_ERROR_DETAIL = 300
# Anchored on "eyJ" — base64url of '{"', the start of every real JOSE header.
# Catches JWTs of any segment length without falsely redacting dotted module
# paths ("pkg.module.attr"), which are often the most diagnostic part of an
# exception message.
_JWT_SHAPED_RE = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}")


def sanitize_error_detail(detail: str) -> str:
    """Redact token-shaped substrings from an exception message, truncate."""
    cleaned = _JWT_SHAPED_RE.sub("<redacted-jwt>", detail)
    cleaned = _BEARER_RE.sub("<redacted-bearer>", cleaned)
    return cleaned[:MAX_ERROR_DETAIL]


def _truncate(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_ARG_STRLEN]
    if isinstance(value, list):
        return [_truncate(v) for v in value[:25]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_ARG_STRLEN]


def sanitize_mcp_arguments(arguments: Any) -> dict:
    """Allowlist values, redact everything else. Returns a new dict."""
    if not isinstance(arguments, dict):
        return {}
    clean: dict = {}
    for raw_key, value in list(arguments.items())[:MAX_ARG_KEYS]:
        key = str(raw_key)
        key_lower = key.lower()
        if any(bad in key_lower for bad in DENY_ARG_SUBSTRINGS):
            clean[key] = REDACTED
        elif key_lower in ALLOWED_ARG_KEYS:
            clean[key] = _truncate(value)
        else:
            clean[key] = REDACTED
    return clean


# --- emitter: bounded queue + background worker, fire-and-forget ---

class UsageAnalyticsEmitter:
    """Non-blocking, drop-on-full emitter for analytics events."""

    def __init__(
        self,
        ingest_url: str,
        token: str,
        *,
        queue_size: int = 1000,
        timeout: float = 2.0,
    ) -> None:
        self.ingest_url = ingest_url
        self.token = token
        self.enabled = bool(ingest_url and token)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._worker: Optional[asyncio.Task] = None
        self._dropped = 0

    async def start(self) -> None:
        if not self.enabled or self._worker is not None:
            return
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._worker = asyncio.create_task(self._run(), name="usage-analytics-worker")
        logger.info("Usage analytics emitter started -> %s", self.ingest_url)

    def emit(self, event: dict) -> None:
        """Enqueue an event. Never blocks, never raises, drops when full."""
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                logger.warning("usage analytics queue full — dropped %d events", self._dropped)
        except Exception:
            logger.debug("usage analytics emit skipped", exc_info=True)

    async def _run(self) -> None:
        if self._client is None:  # guard (not assert — survives python -O)
            return
        while True:
            event = await self._queue.get()
            if event is None:  # shutdown sentinel
                self._queue.task_done()
                return
            try:
                resp = await self._client.post(
                    self.ingest_url,
                    json=event,
                    headers={"X-Internal-Token": self.token},
                )
                if resp.status_code >= 400:
                    # Surfaces a misconfigured token (401) or backend error so the
                    # pipeline isn't silently broken. Debug-level: high volume, best-effort.
                    logger.debug("usage analytics ingest rejected: status=%d", resp.status_code)
            except Exception:
                # Backend down / network blip — drop, never retry inline.
                logger.debug("usage analytics POST failed", exc_info=True)
            finally:
                self._queue.task_done()

    async def aclose(self) -> None:
        if self._worker is None:
            return
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            self._worker.cancel()
        try:
            await asyncio.wait_for(self._worker, timeout=self._timeout + 1)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._worker.cancel()
        finally:
            if self._client is not None:
                await self._client.aclose()
            self._worker = None


def build_emitter_from_env() -> UsageAnalyticsEmitter:
    """Construct an emitter from environment configuration (inert if unset)."""
    return UsageAnalyticsEmitter(
        ingest_url=os.environ.get("MCP_ANALYTICS_INGEST_URL", "").strip(),
        token=os.environ.get("MCP_INGEST_SHARED_SECRET", "").strip(),
    )


# --- text-tool error context (#40 §1, issue #32) ---------------------------
#
# Text tools return their error as a *successful* string (no exception raised),
# so the middleware would otherwise record status="ok" and the dashboard error
# rate would be structurally understated. A generated tool error-helper stashes
# structured error info in this contextvar; `on_call_tool` folds it into the
# event when the call returned normally. Set inside the tool, read in the
# middleware finally — propagation through the FastMCP middleware chain is the
# load-bearing assumption, pinned by tests/test_text_tool_analytics.py.
_tool_error: ContextVar[Optional[dict]] = ContextVar("_tool_error", default=None)


def record_tool_error(
    error_type: str,
    detail: str,
    *,
    upstream_status: Optional[int] = None,
    request_id: Optional[str] = None,
) -> None:
    """Record that the current text-tool call failed but returned an error
    *string* instead of raising. The analytics middleware promotes the event to
    status="error" from this. Safe to call from any tool error-helper; never
    raises (a capture failure must never break a tool call)."""
    try:
        _tool_error.set(
            {
                "error_type": error_type,
                "detail": detail,
                "upstream_status": upstream_status if isinstance(upstream_status, int) else None,
                "request_id": request_id if isinstance(request_id, str) else None,
            }
        )
    except Exception:  # pragma: no cover — contextvar.set effectively never fails
        logger.debug("record_tool_error skipped", exc_info=True)


# --- middleware: capture tool + prompt calls ---

@dataclass(frozen=True)
class _ErrorInfo:
    """Sanitized error context extracted from a tool/prompt exception."""

    error_type: Optional[str] = None
    detail: Optional[str] = None
    upstream_status: Optional[int] = None
    request_id: Optional[str] = None
    error_kind: str = ""

    @classmethod
    def from_exception(cls, exc: BaseException) -> "_ErrorInfo":
        upstream_status = getattr(exc, "upstream_status", None)
        request_id = getattr(exc, "request_id", None)
        error_kind = getattr(exc, "error_kind", "") or ""
        return cls(
            error_type=type(exc).__name__,
            detail=sanitize_error_detail(str(exc)),
            upstream_status=upstream_status if isinstance(upstream_status, int) else None,
            request_id=request_id if isinstance(request_id, str) else None,
            error_kind=error_kind if isinstance(error_kind, str) else "",
        )

    @classmethod
    def from_recorded(cls, data: dict) -> "_ErrorInfo":
        """Build from a `record_tool_error` payload (a text tool that returned
        an error string rather than raising)."""
        upstream_status = data.get("upstream_status")
        request_id = data.get("request_id")
        return cls(
            error_type=data.get("error_type") or "ToolError",
            detail=sanitize_error_detail(str(data.get("detail") or "")),
            upstream_status=upstream_status if isinstance(upstream_status, int) else None,
            request_id=request_id if isinstance(request_id, str) else None,
        )


_RESULT_LIST_KEYS = ("results", "periods", "items", "data")


def _count_results(sc: dict) -> Optional[int]:
    """Cardinality of a structured result: length of a known list envelope, or a
    paginated ``count`` / ``period_count``. None for a single-object (retrieve)
    result (which is handled as has_data via truthiness)."""
    for k in _RESULT_LIST_KEYS:
        v = sc.get(k)
        if isinstance(v, list):
            return len(v)
    for k in ("count", "period_count"):
        v = sc.get(k)
        if isinstance(v, bool):  # bool is an int subclass — exclude
            continue
        if isinstance(v, int):
            return v
    return None


_ID_KEYS = ("id", "company_id", "filing_id", "isin")
_COUNTRY_KEYS = ("country_code", "country")
_ENTITY_CAP = 50


def _extract_entities(sc: dict):
    """Best-effort: the entity ids surfaced + distinct country codes (the query-geo
    signal — which markets the user is actually pulling). Looks at each result row
    and a nested ``company`` (filings carry country under company). Never raises."""
    ids, countries = [], set()
    items = None
    for k in _RESULT_LIST_KEYS:
        v = sc.get(k)
        if isinstance(v, list):
            items = v
            break
    rows = items if items is not None else [sc]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for scope in (row, row.get("company") if isinstance(row.get("company"), dict) else None):
            if scope is None:
                continue
            for ik in _ID_KEYS:
                iv = scope.get(ik)
                if isinstance(iv, (int, str)) and not isinstance(iv, bool):
                    ids.append(iv)
                    break
            for ck in _COUNTRY_KEYS:
                cv = scope.get(ck)
                if isinstance(cv, str) and 2 <= len(cv) <= 3:
                    countries.add(cv.upper())
                    break
        if len(ids) >= _ENTITY_CAP:
            break
    return ids[:_ENTITY_CAP], sorted(countries)


def _result_metrics(result) -> dict:
    """Best-effort, never-raises shape metrics about a tool result.

    Returns ``{result_count, has_data, response_bytes, returned_ids, result_countries}``.
    Captures NO response *content* — only how much came back, whether it was empty
    (``has_data=False`` on a 200 = the "demand we couldn't fill" signal), the entity
    ids surfaced, and the distinct country codes (which markets are in demand).
    """
    out = {"result_count": None, "has_data": None, "response_bytes": None,
           "returned_ids": [], "result_countries": []}
    try:
        sc = getattr(result, "structured_content", None)
        if sc is None and isinstance(result, dict):
            sc = result
        if isinstance(sc, dict):
            out["response_bytes"] = len(json.dumps(sc, default=str))
            cnt = _count_results(sc)
            out["result_count"] = cnt
            out["has_data"] = (cnt > 0) if cnt is not None else bool(sc)
            out["returned_ids"], out["result_countries"] = _extract_entities(sc)
            return out
        # Non-structured (text) result: size + non-empty only.
        text = None
        content = getattr(result, "content", None)
        if content:
            text = "".join(p for p in (getattr(b, "text", None) for b in content) if p)
        elif isinstance(result, str):
            text = result
        if text is not None:
            out["response_bytes"] = len(text)
            out["has_data"] = bool(text.strip())
    except Exception:
        pass
    return out


# --- Request-level signals: cross-client workflow stitching + client discovery ---
# ChatGPT (openai-mcp) mints a fresh Mcp-Session-Id every tool call (a known MCP spec
# violation, not fixable server-side), so `session_id` can't group its calls. It instead
# carries per-conversation context in the JSON-RPC `_meta` object: `openai/session`
# (stable per conversation), `openai/subject` (user), `openai/userAgent`, `openai/locale`.
# We read those (body, not headers), derive a unified `correlation_id`, and — as a
# fallback and a discovery aid — capture header NAMES and a salted token fingerprint.
# No credentials, cookies, client IPs, or response content are ever captured.
_META_NAMESPACE = "openai/"
_META_EXCLUDE = frozenset({
    "openai/userLocation",  # user geography — out of analytics scope
    "openai/subject",       # OpenAI account id — avoid cross-platform identity linkage (mcp_sub already identifies the user)
})
_META_KEYS_CAP = 20
_META_VAL_CAP = 256
_HEADER_KEYS_CAP = 60
# Salt the token fingerprint so it is never a bare hash of the credential. Falls back to
# the ingest shared secret, which is REQUIRED for analytics to emit at all — so the
# fingerprint is always salted in any environment where this capture path is active.
_FP_SALT = os.environ.get("MCP_ANALYTICS_FP_SALT") or os.environ.get("MCP_INGEST_SHARED_SECRET", "")


def _extract_meta(message) -> dict:
    """OpenAI control metadata from the tool-call ``_meta`` (JSON-RPC body, not headers).
    Captures every ``openai/*`` key except user-geography. Values are protocol metadata,
    never user content or credentials. Never raises."""
    out: dict = {}
    try:
        meta = getattr(message, "meta", None)
        extra = getattr(meta, "model_extra", None) or {}
    except Exception:
        logger.debug("usage analytics: meta access skipped", exc_info=True)
        return {}
    for key, val in extra.items():
        try:
            if not isinstance(key, str) or not key.startswith(_META_NAMESPACE) or key in _META_EXCLUDE:
                continue
            if val is None:
                continue
            out[key[:64]] = val if isinstance(val, (int, float, bool)) else str(val)[:_META_VAL_CAP]
            if len(out) >= _META_KEYS_CAP:
                break
        except Exception:
            continue  # one hostile/unstringable value must not drop the others
    return out


def _http_header_keys() -> list:
    """Sorted incoming HTTP header NAMES (names only — never values). Discovery aid to
    confirm whether a client sends any stable correlation header. Never raises."""
    try:
        raw = get_http_headers(include_all=True) or {}
        return sorted({str(k).lower() for k in raw.keys()})[:_HEADER_KEYS_CAP]
    except Exception:
        logger.debug("usage analytics: header-key capture skipped", exc_info=True)
        return []


def _token_fingerprint() -> str:
    """Salted, truncated SHA-256 of the access token — a stable per-token key that never
    exposes the token. ``''`` when no token is in context. Never raises."""
    try:
        tok = getattr(get_access_token(), "token", None)
    except Exception:
        tok = None
    if not tok:
        return ""
    try:
        return hashlib.sha256((_FP_SALT + tok).encode("utf-8")).hexdigest()[:32]
    except Exception:
        return ""


class UsageAnalyticsMiddleware(Middleware):
    """Captures every tool call and prompt fetch and hands it to the emitter.

    Reads identity (``sub``/``client_id``) from the verified Cognito access
    token and the MCP host name/version from the session's clientInfo. All
    capture work is wrapped so a failure here can never break a tool call.
    """

    def __init__(self, emitter: UsageAnalyticsEmitter, server_version: str = "") -> None:
        self._emitter = emitter
        self._server_version = server_version or os.environ.get("MCP_VERSION", "dev")

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        started = time.monotonic()
        _tool_error.set(None)  # clear any value carried over within this context
        status, err, result = "ok", _ErrorInfo(), None
        try:
            result = await call_next(context)
            return result
        except Exception as exc:
            status, err = "error", _ErrorInfo.from_exception(exc)
            raise
        finally:
            if status == "ok":
                # Text tools surface their error as a normal string (no raise);
                # promote the event to status="error" when a tool error-helper
                # recorded structured context for this call.
                recorded = _tool_error.get()
                if recorded:
                    status, err = "error", _ErrorInfo.from_recorded(recorded)
            self._safe_emit(context, kind="tool", status=status, err=err,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            result=result)

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        started = time.monotonic()
        status, err = "ok", _ErrorInfo()
        try:
            return await call_next(context)
        except Exception as exc:
            status, err = "error", _ErrorInfo.from_exception(exc)
            raise
        finally:
            self._safe_emit(context, kind="prompt", status=status, err=err,
                            latency_ms=int((time.monotonic() - started) * 1000))

    def _safe_emit(self, context, *, kind, status, err, latency_ms, result=None) -> None:
        try:
            self._emitter.emit(self._build_event(context, kind, status, err, latency_ms, result))
        except Exception:
            logger.debug("usage analytics build/emit skipped", exc_info=True)

    def _build_event(self, context, kind, status, err, latency_ms, result=None) -> dict:
        message = getattr(context, "message", None)
        name = getattr(message, "name", "") or ""
        arguments = getattr(message, "arguments", None) or {}
        sub, client_id, host_name, host_version = self._identity(context)
        metrics = _result_metrics(result)
        session_id = ""
        try:
            fc = getattr(context, "fastmcp_context", None)
            session_id = (getattr(fc, "session_id", "") or "")[:64]
        except Exception:
            session_id = ""
        meta = _extract_meta(message)
        header_keys = _http_header_keys()
        conv = str(meta.get("openai/session") or "").strip()
        if conv:
            correlation_id, correlation_source = conv[:128], "meta:openai/session"
        elif session_id:
            correlation_id, correlation_source = session_id, "mcp_session"
        else:
            fp = _token_fingerprint()
            correlation_id, correlation_source = (fp, "token_fp") if fp else ("", "")
        return {
            "ts": time.time(),
            "sub": sub or "",
            "client_id": client_id or "",
            "host_name": host_name or "",
            "host_version": host_version or "",
            "kind": kind,
            "name": name,
            "arguments": sanitize_mcp_arguments(arguments),
            "status": status,
            "upstream_status": err.upstream_status,
            "upstream_request_id": err.request_id or "",
            "error_type": err.error_type or "",
            "error_detail": err.detail or "",
            "error_kind": err.error_kind or "",
            "latency_ms": latency_ms,
            # Result shape — how much data came back, and whether it was empty.
            # has_data=False on a 200 (e.g. financials period_count=0, empty search)
            # is the "demand we couldn't fill" signal. Carries no response content.
            "result_count": metrics["result_count"],
            "has_data": metrics["has_data"],
            "response_bytes": metrics["response_bytes"],
            # Specific entities surfaced + which markets (query-geo). No content.
            "returned_ids": metrics["returned_ids"],
            "result_countries": metrics["result_countries"],
            # Stable per-connection id → stitch a user's call sequence into a workflow.
            "session_id": session_id,
            # Cross-client workflow stitching. ChatGPT mints a fresh Mcp-Session-Id per
            # call, so session_id can't group its calls; openai/session in _meta can.
            # correlation_id = best available stable key (openai/session > Mcp-Session-Id
            # > salted token fingerprint); correlation_source records which one was used.
            "correlation_id": correlation_id,
            "correlation_source": correlation_source,
            # OpenAI control metadata from the tool-call _meta (openai/* keys; no user geo).
            "mcp_meta": meta,
            # Incoming HTTP header NAMES only — discovery aid; confirms no stable header.
            "request_header_keys": header_keys,
            "server_version": self._server_version,
            "protocol_version": "",
        }

    @staticmethod
    def _identity(context):
        sub = client_id = host_name = host_version = None
        try:
            token = get_access_token()  # None under DEV_MODE_API_KEY bypass
        except Exception:
            token = None
        if token is not None:
            claims = getattr(token, "claims", {}) or {}
            sub = claims.get("sub")
            client_id = claims.get("client_id") or getattr(token, "client_id", None)
        fc = getattr(context, "fastmcp_context", None)
        try:
            client_info = fc.session.client_params.clientInfo
            host_name = getattr(client_info, "name", None)
            host_version = getattr(client_info, "version", None)
        except Exception:
            pass
        return sub, client_id, host_name, host_version
