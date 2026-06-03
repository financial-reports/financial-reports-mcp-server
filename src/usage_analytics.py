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
import logging
import os
import time
from typing import Any, Optional

import httpx
from fastmcp.server.dependencies import get_access_token
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


# --- middleware: capture tool + prompt calls ---

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
        status, error_type = "ok", None
        try:
            return await call_next(context)
        except Exception as exc:
            status, error_type = "error", type(exc).__name__
            raise
        finally:
            self._safe_emit(context, kind="tool", status=status,
                            error_type=error_type,
                            latency_ms=int((time.monotonic() - started) * 1000))

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        started = time.monotonic()
        status, error_type = "ok", None
        try:
            return await call_next(context)
        except Exception as exc:
            status, error_type = "error", type(exc).__name__
            raise
        finally:
            self._safe_emit(context, kind="prompt", status=status,
                            error_type=error_type,
                            latency_ms=int((time.monotonic() - started) * 1000))

    def _safe_emit(self, context, *, kind, status, error_type, latency_ms) -> None:
        try:
            self._emitter.emit(self._build_event(context, kind, status, error_type, latency_ms))
        except Exception:
            logger.debug("usage analytics build/emit skipped", exc_info=True)

    def _build_event(self, context, kind, status, error_type, latency_ms) -> dict:
        message = getattr(context, "message", None)
        name = getattr(message, "name", "") or ""
        arguments = getattr(message, "arguments", None) or {}
        sub, client_id, host_name, host_version = self._identity(context)
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
            "upstream_status": None,
            "error_type": error_type or "",
            "latency_ms": latency_ms,
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
