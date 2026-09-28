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
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger(__name__)

# --- argument sanitization (kept in sync with users.mcp_analytics on the backend) ---

ALLOWED_ARG_KEYS = frozenset({
    "search", "ticker", "isin", "lei",
    # Date bounds. Sanitisation runs on BOTH ends — here, and again in the
    # platform's users/mcp_analytics.py — so the stricter side wins. The
    # receiver allowlisted these on 2026-08-06 specifically to measure whether
    # history-fenced callers request past their cutoff, but this sender was
    # still stamping them <redacted> first, so every recorded event carried no
    # usable value and the question stayed unanswerable. Values are query
    # bounds, not identifiers or secrets, and DENY_ARG_SUBSTRINGS is still
    # applied first — a key like "date_auth_token" is redacted regardless.
    "release_datetime_from", "release_datetime_to",
    "date", "date_from", "date_to", "year",
    "filing_type_code", "filing_category", "category",
    "line_items", "section_keyword",
    "fiscal_year", "fiscal_period", "current_fiscal_year", "prior_fiscal_year",
    "countries", "country", "sector", "industry", "industry_group", "sub_industry",
    "ordering", "view", "on_watchlist",
    "id", "company_id", "filing_id", "ticker_or_name",
    "page", "page_size",
    # Keys the RECEIVER already allowlists that this sender was still redacting
    # first — so they reached the table as <redacted> regardless: lookup
    # identifiers (platform, 2026-07-01) and the real filing-list type filters
    # (platform, 2026-09-08); `type`/`types` were <redacted> on every filings_list
    # call, so type-filter failures could not be read from analytics at all.
    # Several of these are unconstrained strings in the schema, so their values
    # pass through _scrub_token_shapes like every other allowlisted string.
    "code", "cik", "figi", "symbol", "exchange", "mic", "name",
    "type", "types",
    # DELIBERATELY NOT HERE, although the receiver allowlists them: "query", "q".
    # They are free text, and value-level scrubbing cannot recognise an arbitrary
    # opaque credential (only JWT / Bearer shapes), so a pasted key would be
    # stored durably. Whether raw in-text search terms may be logged is an open
    # product/privacy decision, not an allowlist tweak — see #119.
    # New on both ends (the platform allowlist must add these too, or the
    # stricter receiver keeps redacting them). Enums, integers, dates and public
    # identifiers — none names a person or carries a credential.
    "statement_type", "fiscal_year_from", "fiscal_year_to", "as_of",
    "company", "company_isin",
    "max_hits", "context_chars", "offset", "limit",
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


def sanitize_error_detail(detail: str, max_len: int = MAX_ERROR_DETAIL) -> str:
    """Redact token-shaped substrings from an exception message, truncate.

    ``max_len`` defaults to the analytics column budget. Callers forwarding
    upstream copy on to the *client* pass a larger cap (#73) — there the
    redaction is the load-bearing part, not the truncation.
    """
    cleaned = _JWT_SHAPED_RE.sub("<redacted-jwt>", detail)
    cleaned = _BEARER_RE.sub("<redacted-bearer>", cleaned)
    return cleaned[:max_len]


# An unbroken run of 24+ URL-safe characters mixing letters AND digits: the shape
# of an opaque API key or secret (`sk_live_…`, hex digests, UUIDs). The values
# analytics exists to capture fall short of it: filing-type codes, tickers,
# ISINs (12), LEIs (20), CIKs, ISO dates (broken up by `:`/`.`/`+`), and
# snake_case line-item codes (letters only, however long).
_OPAQUE_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{24,}")


def _redact_if_opaque(match: "re.Match[str]") -> str:
    run = match.group(0)
    has_letter = any(c.isalpha() for c in run)
    has_digit = any(c.isdigit() for c in run)
    return "<redacted-token>" if has_letter and has_digit else run


def _scrub_token_shapes(text: str) -> str:
    """Redact credential-shaped substrings from an allowlisted string VALUE.

    The allowlist decides which KEYS keep their value; it cannot constrain what a
    caller puts in one. Several allowlisted keys are unconstrained strings in the
    schema (`search`, `type`, `types`, `name`, `symbol`, ...), so a credential
    placed in any of them would otherwise be stored verbatim. This is a
    best-effort VALUE-SHAPE gate applied to every allowlisted string, not a
    per-key list: JWT and Bearer shapes (sanitize_error_detail's patterns), then
    any long letters-and-digits run. It does NOT catch a short or letters-only
    secret. Applied BEFORE truncation: cutting first can split a token so no
    pattern matches and a prefix leaks.
    """
    cleaned = _JWT_SHAPED_RE.sub("<redacted-jwt>", text)
    cleaned = _BEARER_RE.sub("<redacted-bearer>", cleaned)
    return _OPAQUE_TOKEN_RE.sub(_redact_if_opaque, cleaned)


# Scrub only a bounded window, never the whole value: a caller-controlled
# multi-megabyte string must not be regex-scanned synchronously in the request
# path. The window is 4x the stored length, so a token that starts inside the
# stored prefix still has >=3x MAX_ARG_STRLEN of its body in view and matches.
_SCRUB_WINDOW = MAX_ARG_STRLEN * 4


def _scrub_and_cap(text: str) -> str:
    return _scrub_token_shapes(text[:_SCRUB_WINDOW])[:MAX_ARG_STRLEN]


# --- closed-grammar validation of allowlisted values (#124) ------------------
#
# `_scrub_token_shapes` is best effort: it cannot enumerate credential formats, and
# six review rounds on #119 each found a shape it missed. So every allowlisted key
# whose values come from a CLOSED grammar is validated instead: the value is stored
# only when it conforms, otherwise a marker is. For these keys nothing a caller
# types can reach the table unless it IS a valid value — and the marker still
# records HOW OFTEN an invalid value is sent, which is the diagnostic #119 exists
# for. Keys with no closed grammar (search, name, symbol, ticker_or_name, code,
# ticker, ...) keep the best-effort scrub above.

UNRECOGNIZED = "<unrecognized>"
INVALID = "<invalid>"

# The FinancialFilings filing-type taxonomy: the codes `filings_list` `type` /
# `types` accept. Kept in step with the 30-code table in the generator's
# `fr://guide/filing-types` resource by tests/test_usage_analytics.py, and equal to
# prod `filings_filingtype.code` when measured on 2026-09-28. A constant rather
# than a lookup because capture runs in the request path and must not make a
# network call; a code added upstream records as <unrecognized> until added here.
FILING_TYPE_CODES = frozenset({
    "10-K", "10-K-ESEF", "IR", "ER", "XLSX", "AR",
    "MDA", "MANG", "DEF 14A", "DIRS",
    "SR", "CGR",
    "CT", "IP", "RPA",
    "TAR", "LTR",
    "AGM-R", "DVA", "PSI",
    "CAP", "IRAT",
    "MRQ", "DIV", "SHA", "POS",
    "FS", "NAV",
    "DLST",
    "RNS",
})
# SEC form names agents send INSTEAD of a code (10-Q for IR, 20-F for 10-K, ...).
# Not valid filter values — the API returns an empty list for them — but a closed
# set, and precisely the misuse the filing-type guidance targets, so they are
# stored verbatim rather than collapsed into <unrecognized>. Beyond #124's table
# by design; drop entries here to trade that diagnostic away.
_SEC_FORM_NAMES = frozenset({
    "10-Q", "10-Q/A", "10-K/A", "8-K", "8-K/A", "20-F", "20-F/A", "6-K", "40-F",
    "S-1", "S-3", "S-4", "F-1", "424B3", "4", "4/A", "3", "5", "13F-HR",
    "SC 13D", "SC 13G", "11-K", "ARS", "DEFA14A", "DEFM14A", "N-CSR",
})
_FILING_TYPE_VOCAB = {v.upper(): v for v in FILING_TYPE_CODES | _SEC_FORM_NAMES}
_FISCAL_PERIODS = frozenset({"FY", "H1", "H2", "Q1", "Q2", "Q3", "Q4", "9M"})
# BS/IS/CFS on financials; line_item_definitions_list also takes SUP.
_STATEMENT_TYPES = frozenset({"BS", "IS", "CFS", "SUP"})

_CIK_RE = re.compile(r"(?i)(?:cik)?[0-9]{1,10}")
_ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
_LEI_RE = re.compile(r"[A-Z0-9]{18}[0-9]{2}")
# OpenFIGI: two consonants, "G", eight consonants/digits, a check digit. The check
# digit itself is not verified (structure only).
_FIGI_RE = re.compile(r"[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]")
_MIC_RE = re.compile(r"[A-Z0-9]{4}")
_ID_MAXLEN = 32  # no identifier grammar here is longer; refuse before any work


def _alnum_digits(text: str) -> str:
    """ISO 6166 / ISO 17442 letter expansion: A=10 ... Z=35, digits as-is."""
    return "".join(str(int(c, 36)) for c in text)


def _isin_check_ok(isin: str) -> bool:
    digits = _alnum_digits(isin[:-1]) + isin[-1]
    total = 0
    for i, ch in enumerate(reversed(digits)):
        v = int(ch)
        if i % 2 == 1:
            v = v * 2 - 9 if v * 2 > 9 else v * 2
        total += v
    return total % 10 == 0


def _id_grammar(pattern: "re.Pattern[str]", check: Optional[Callable[[str], bool]] = None):
    def validate(value: Any) -> Any:
        if not isinstance(value, str) or len(value) > _ID_MAXLEN:
            return INVALID
        stripped = value.strip()
        upper = stripped.upper()
        if not pattern.fullmatch(upper) or (check is not None and not check(upper)):
            return INVALID
        return stripped
    return validate


def _cik(value: Any) -> Any:
    if isinstance(value, bool):
        return INVALID
    if isinstance(value, int):
        return value if 0 <= value < 10**10 else INVALID
    if isinstance(value, str) and len(value) <= _ID_MAXLEN and _CIK_RE.fullmatch(value.strip()):
        return value.strip()
    return INVALID


def _enum(members: frozenset):
    def validate(value: Any) -> Any:
        if isinstance(value, str) and len(value) <= _ID_MAXLEN and value.strip().upper() in members:
            return value.strip()
        return INVALID
    return validate


def _filing_types(value: Any) -> Any:
    """Comma-separated filing-type codes: each member kept as sent if it is a code
    (or a known SEC form name), else <unrecognized>. The output alphabet is closed."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return UNRECOGNIZED
    text = str(value)
    if len(text) > _SCRUB_WINDOW:  # 30 codes fit in ~300 chars; never split a huge value
        return UNRECOGNIZED
    members = []
    for part in text.split(","):
        member = part.strip()
        members.append(member if not member or member.upper() in _FILING_TYPE_VOCAB else UNRECOGNIZED)
    return ",".join(members)[:MAX_ARG_STRLEN]


_GRAMMARS: dict = {
    "type": _filing_types,
    "types": _filing_types,
    "cik": _cik,
    "isin": _id_grammar(_ISIN_RE, _isin_check_ok),
    "company_isin": _id_grammar(_ISIN_RE, _isin_check_ok),
    "lei": _id_grammar(_LEI_RE, lambda s: int(_alnum_digits(s)) % 97 == 1),
    "figi": _id_grammar(_FIGI_RE),
    "mic": _id_grammar(_MIC_RE),
    "fiscal_period": _enum(_FISCAL_PERIODS),
    "statement_type": _enum(_STATEMENT_TYPES),
}


def _apply_grammar(value: Any, validate: Callable[[Any], Any]) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [None if v is None else validate(v) for v in value[:25]]
    return validate(value)


def _truncate(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_and_cap(value)
    if isinstance(value, list):
        return [_truncate(v) for v in value[:25]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _scrub_and_cap(str(value))


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
            grammar = _GRAMMARS.get(key_lower)
            clean[key] = _apply_grammar(value, grammar) if grammar else _truncate(value)
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

# --- per-call correlation id -------------------------------------------------
#
# A fresh UUID per tool call, forwarded upstream as `X-Client-Request-Id`, so one
# value joins an MCP log line to its MCPToolEvent row to the origin request log.
#
# Distinct from `correlation_id` further down, which stitches a SESSION together
# and is stable across many calls. This one is deliberately per-call: it answers
# "which upstream request did THIS tool call make". Note #75's retry can turn one
# tool call into two upstream requests; both carry the same id, so the origin-side
# join is intentionally one-to-many.
#
# Propagation through the FastMCP middleware chain is the same load-bearing
# assumption `_tool_error` already relies on: `await call_next(context)` runs in
# the same task, so the value set here is visible inside the tool body and in
# httpx's request event hook.
_call_id: ContextVar[str] = ContextVar("_call_id", default="")


def current_call_id() -> str:
    """This tool call's correlation id, or '' outside a tool call."""
    return _call_id.get()

# --- clientInfo carry-over across the stateless transport -------------------
#
# `clientInfo` (host name/version) is sent ONCE, in the MCP `initialize`
# handshake, and used to live in the per-session transport state. Since
# stateless_http=True (#63 — required, it fixed cross-replica session-loss
# 404s) a fresh transport is built per request, so by the time a tool call
# arrives `session.client_params` is gone and every event logged a blank host.
# Measured: 100% blank from 2026-07-16, i.e. the host-split analytics went dark.
#
# So we carry it ourselves: capture at `initialize`, key it by the CONNECTION
# (see `_connection_key`), and resolve it on the way into an event. Two tiers — a
# bounded per-process dict, and the shared Redis the connector already runs —
# because with horizontal scaling the `initialize` and the tool call routinely
# land on different replicas, which is the same reason #63 existed.
#
# The key is NOT the validated token's `client_id` claim (#97). That claim is the
# Cognito app client, and every host reaches us through the same one, so keying
# on it made the cache a single global slot: whichever host initialized last was
# stamped on every later call, from every host and every user (12 host names on
# one id in prod). The per-connection key that survives the stateless transport
# is the bearer the client presents: the OAuth proxy's reference JWT, whose
# `client_id` is that client's own DCR registration, stable across token refresh.
# Mcp-Session-Id is not an option: with stateless_http the server never issues
# one, so a conforming client never sends it and FastMCP mints a fresh id per
# request — it could never join an `initialize` to a later call.
_client_info: ContextVar[Optional[tuple]] = ContextVar("_client_info", default=None)

# Bounded so a hostile or buggy client cannot grow it without limit. One entry
# per (DCR registration, user); an overflow clears it and it repopulates on the
# next `initialize`, falling back to the shared store meanwhile.
_CLIENT_INFO_LOCAL_MAX = 512
_client_info_local: dict[str, tuple] = {}

# Long enough to span a client's normal reconnect cadence, short enough that a
# renamed/upgraded host converges without manual eviction.
CLIENT_INFO_TTL_SECONDS = 30 * 24 * 3600
# v2: entries written under the v1 key ("mcp-client-info::<cognito client id>")
# are the misattributed global slot of #97; a new prefix guarantees none is read
# back. They age out under the TTL above.
_CLIENT_INFO_KEY = "mcp-client-info:v2::{key}"

# A bearer is a few KB at most; never base64-decode an unbounded header value.
_MAX_BEARER_LEN = 8192

# This module's contract is that capture never adds latency to a real call. A
# store round-trip inside the request path would break that, and a `try/except`
# does not catch a HANG — an unreachable Redis blocks rather than raising. So the
# write is fired and forgotten, and the read is bounded: miss the deadline and we
# log a blank host, which is strictly better than delaying the user's tool call.
_CLIENT_INFO_READ_TIMEOUT = 0.25

# create_task returns a task the event loop only weakly references; without a
# strong ref it can be garbage-collected mid-flight. Keep them until they finish.
_client_info_writes: set = set()


def record_tool_error(
    error_type: str,
    detail: str,
    *,
    upstream_status: Optional[int] = None,
    request_id: Optional[str] = None,
    error_kind: str = "",
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
                "error_kind": error_kind if isinstance(error_kind, str) else "",
            }
        )
    except Exception:  # pragma: no cover — contextvar.set effectively never fails
        logger.debug("record_tool_error skipped", exc_info=True)


# --- text-tool result cardinality --------------------------------------------
#
# `_result_metrics` can only count a STRUCTURED result. A text tool's payload is
# prose, so it logged result_count=NULL and has_data=bool(text) — and a "No match"
# message is non-empty text, so every filings_markdown_search miss was recorded as
# has_data=True. Measured: result_count NULL on 100% of ok search events, has_data
# true on 100%, and misses recoverable only by guessing from response_bytes. A text
# tool that knows its own count stashes it here; the middleware prefers it.
_tool_result_count: ContextVar[Optional[int]] = ContextVar("_tool_result_count", default=None)


def record_result_count(count: int) -> None:
    """Record how many results the current text-tool call produced (0 = empty).

    The middleware folds it into the event as result_count, with has_data derived
    from it. Never raises; a non-int or negative value is ignored rather than
    logged, so a caller bug cannot fabricate a count.
    """
    try:
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            _tool_result_count.set(count)
    except Exception:  # pragma: no cover — contextvar.set effectively never fails
        logger.debug("record_result_count skipped", exc_info=True)


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
        # FastMCP's tool manager re-raises anything a tool throws wrapped in a
        # generic ToolError (`raise ToolError(...) from e`), and this middleware
        # sits OUTSIDE the tool manager — so what arrives here is the wrapper,
        # carrying none of our typed context. Look exactly one `__cause__` link
        # down to recover it. Without this every structured-tool upstream
        # failure lands as a bare ToolError with a NULL upstream_status: 30 days
        # of prod showed 4,319 such rows that were really 429s and 403s, which
        # is why #73's own 429 count came out 5x low. One link only — a deeper
        # chain is someone else's bug and must not become our classification.
        if upstream_status is None and request_id is None and not error_kind:
            cause = exc.__cause__
            if cause is not None:
                upstream_status = getattr(cause, "upstream_status", None)
                request_id = getattr(cause, "request_id", None)
                error_kind = getattr(cause, "error_kind", "") or ""
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
        error_kind = data.get("error_kind") or ""
        return cls(
            error_type=data.get("error_type") or "ToolError",
            detail=sanitize_error_detail(str(data.get("detail") or "")),
            upstream_status=upstream_status if isinstance(upstream_status, int) else None,
            request_id=request_id if isinstance(request_id, str) else None,
            error_kind=error_kind if isinstance(error_kind, str) else "",
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


def _content_text(result) -> Optional[str]:
    """Concatenated text blocks of a tool result's ``content``, or None."""
    content = getattr(result, "content", None)
    if not content:
        return None
    return "".join(p for p in (getattr(b, "text", None) for b in content) if p)


def _wrapped_text(sc: Any, result: Any) -> Optional[str]:
    """The text of a ``str``-returning tool, or None for anything else (#127).

    FastMCP reports a ``str`` return as ``structured_content={"result": <text>}``,
    so the structured branch below used to measure ``len(json.dumps(...))`` — every
    newline and quote in the payload cost an extra character (152,131 logged for a
    150,000-char slice). A tool that genuinely returns the dict
    ``{"result": "..."}`` has the same structured_content, so the shape alone
    cannot tell them apart; the content blocks can. The client of a wrapped
    ``str`` receives exactly that string as text, while a real dict arrives as its
    JSON serialization. Only the former is unwrapped.
    """
    if not isinstance(sc, dict) or len(sc) != 1:
        return None
    inner = sc.get("result")
    if not isinstance(inner, str):
        return None
    return inner if _content_text(result) == inner else None


def _result_metrics(result) -> dict:
    """Best-effort, never-raises shape metrics about a tool result.

    Returns ``{result_count, has_data, response_bytes, returned_ids, result_countries}``.
    Captures NO response *content* — only how much came back, whether it was empty
    (``has_data=False`` on a 200 = the "demand we couldn't fill" signal), the entity
    ids surfaced, and the distinct country codes (which markets are in demand).

    ``response_bytes`` is a size PROXY, not wire bytes — the name is kept only for
    column stability across this repo and the web ingest serializer (#54). It is a
    CHARACTER count of what the client receives as the tool's text: for a
    structured tool, ``len()`` of the re-serialized ``structured_content`` JSON;
    for a ``str``-returning tool, ``len()`` of the text itself (#127 — see
    `_wrapped_text`). It diverges from UTF-8 bytes for non-ASCII and excludes the
    MCP envelope, framing, headers, and transport encoding. Good for relative size
    trends and for comparison against the text tools' character ceilings; never
    reconcile it against load-balancer / APM / CDN byte counters. Rows written
    before #127 measured text tools as JSON (an upper bound, content-dependent).
    """
    out = {"result_count": None, "has_data": None, "response_bytes": None,
           "returned_ids": [], "result_countries": []}
    try:
        sc = getattr(result, "structured_content", None)
        if sc is None and isinstance(result, dict):
            sc = result
        wrapped = _wrapped_text(sc, result)
        if wrapped is not None:
            # A str-returning tool: structured_content is FastMCP's wrapper, not
            # the payload. Measure it exactly like any other text result.
            out["response_bytes"] = len(wrapped)
            out["has_data"] = bool(wrapped.strip())
            return out
        if isinstance(sc, dict):
            out["response_bytes"] = len(json.dumps(sc, default=str))
            cnt = _count_results(sc)
            out["result_count"] = cnt
            out["has_data"] = (cnt > 0) if cnt is not None else bool(sc)
            out["returned_ids"], out["result_countries"] = _extract_entities(sc)
            return out
        # Non-structured (text) result: size + non-empty only.
        text = _content_text(result)
        if text is None and isinstance(result, str):
            text = result
        if text is not None:
            out["response_bytes"] = len(text)
            out["has_data"] = bool(text.strip())
    except Exception:
        pass
    return out


# --- Request-level signals: cross-client workflow stitching + client discovery ---
# ChatGPT (openai-mcp) mints a fresh Mcp-Session-Id every tool call (a known MCP spec
# violation, not fixable server-side), so `session_id` can't group its calls. It carries
# per-conversation context in two places, and #94 established that the one we were
# reading is not the one it actually populates:
#
#   * the `x-openai-session` HTTP HEADER — what openai-mcp really sends. Measured over
#     the whole prod table: 4,104 requests carried it, every one fell through to
#     `mcp_session`, and each produced exactly 1.00 rows per correlation group (against
#     1.25 for everything else). Every ChatGPT call was its own singleton "workflow".
#   * the JSON-RPC `_meta` object — `openai/session`, `openai/userAgent`, `openai/locale`.
#     Kept as the preferred tier because it is the MCP-spec-native channel, but it has
#     never been observed in production. See `_request_context` for why we could not
#     have observed it even if clients did send it.
#
# We read both, prefer `_meta`, and — as further fallbacks and a discovery aid — capture
# header NAMES, the Mcp-Session-Id, and a salted token fingerprint. Header VALUES are
# never captured except `x-openai-session`, which is an opaque conversation id.
# No credentials, cookies, client IPs, or response content are ever captured.
_META_NAMESPACE = "openai/"
# The correlation header openai-mcp actually sends. Lower-case: `_http_headers`
# normalizes, and HTTP header names are case-insensitive.
_CORRELATION_HEADER = "x-openai-session"
_META_EXCLUDE = frozenset({
    "openai/userLocation",  # user geography — out of analytics scope
    "openai/subject",       # OpenAI account id — avoid cross-platform identity linkage (mcp_sub already identifies the user)
    # OpenAI org id — same identifier class as openai/subject, excluded for the same reason.
    # Undocumented in #55; only became visible once #96 fixed the _meta plumbing, by which
    # point it was already being persisted. Default to not retaining a third-party account
    # id we have no question for. See #98 before re-enabling.
    "openai/organization",
})
_META_KEYS_CAP = 20
_META_VAL_CAP = 256
_HEADER_KEYS_CAP = 60
# Salt the token fingerprint so it is never a bare hash of the credential. Falls back to
# the ingest shared secret, which is REQUIRED for analytics to emit at all — so the
# fingerprint is always salted in any environment where this capture path is active.
_FP_SALT = os.environ.get("MCP_ANALYTICS_FP_SALT") or os.environ.get("MCP_INGEST_SHARED_SECRET", "")


def _request_context(context):
    """The MCP ``RequestContext`` for this call, or ``None``. Never raises.

    Deliberately NOT ``context.message``. FastMCP discards the client's validated
    request and rebuilds the middleware message from name+arguments alone
    (``fastmcp/server/server.py:1618`` for tools, ``:1812`` for prompts), so
    ``context.message.meta`` is structurally always ``None`` — which is why
    ``mcp_meta`` was empty on all 31,541 prod rows, and why the ``openai/session``
    tier could never fire regardless of what any client sent (#94).

    The wire ``_meta`` survives only here: the low-level server copies
    ``params.meta`` onto the RequestContext (``mcp/shared/session.py:367``).
    """
    try:
        return getattr(getattr(context, "fastmcp_context", None), "request_context", None)
    except Exception:
        logger.debug("usage analytics: request-context access skipped", exc_info=True)
        return None


def _openai_session_header() -> str:
    """Value of the ``x-openai-session`` request header, or ``''``. Never raises.

    The only header whose VALUE we capture. It is an opaque per-conversation id —
    not a credential and not a user identifier (``openai/subject`` stays excluded
    for exactly that reason). Truncated to match the ``_meta`` tier.
    """
    try:
        raw = get_http_headers(include_all=True) or {}
        for key, val in raw.items():
            if str(key).lower() == _CORRELATION_HEADER:
                return str(val or "").strip()[:128]
    except Exception:
        logger.debug("usage analytics: correlation-header capture skipped", exc_info=True)
    return ""


def _extract_meta(request_context) -> dict:
    """OpenAI control metadata from the request's ``_meta`` (JSON-RPC body, not headers).
    Captures every ``openai/*`` key except user-geography. Values are protocol metadata,
    never user content or credentials. Never raises.

    Takes the ``RequestContext`` from `_request_context`, NOT the middleware message —
    see that function for why the message can never carry ``_meta``."""
    out: dict = {}
    try:
        meta = getattr(request_context, "meta", None)
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


def _cache_client_info_locally(key: str, value: tuple) -> None:
    """The ONE writer of the process-local tier, so both paths into it — capture
    at `initialize` and a read-back from the shared store — honour the bound.
    With per-connection keys (#97) a replica that only ever reads from the store
    sees one key per (registration, user), so that path needs it as much."""
    if key not in _client_info_local and len(_client_info_local) >= _CLIENT_INFO_LOCAL_MAX:
        _client_info_local.clear()  # cheap bound; repopulates from the store / next initialize
    _client_info_local[key] = value


def _presented_client_id() -> str:
    """The ``client_id`` claim of the bearer JWT this request PRESENTED, or ``''``.

    Under the OAuth proxy that bearer is the proxy's own reference token, issued
    per DCR registration — unlike the swapped upstream token `get_access_token()`
    returns, whose ``client_id`` is the shared Cognito app client (#97). The
    signature is not checked here: the auth middleware already verified this exact
    credential for this request before any MCP handler ran, and the value is used
    only as an analytics cache key, never for authorization. Never raises.
    """
    try:
        raw = get_http_headers(include_all=True) or {}
        auth = ""
        for key, val in raw.items():
            if str(key).lower() == "authorization":
                auth = str(val or "")
                break
        scheme, _, token = auth.strip().partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > _MAX_BEARER_LEN:
            return ""
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        cid = claims.get("client_id") if isinstance(claims, dict) else None
        return cid[:256] if isinstance(cid, str) else ""
    except Exception:
        logger.debug("usage analytics: presented client_id unavailable", exc_info=True)
        return ""


class UsageAnalyticsMiddleware(Middleware):
    """Captures every tool call and prompt fetch and hands it to the emitter.

    Reads identity (``sub``/``client_id``) from the verified Cognito access
    token and the MCP host name/version from the session's clientInfo. All
    capture work is wrapped so a failure here can never break a tool call.
    """

    def __init__(
        self,
        emitter: UsageAnalyticsEmitter,
        server_version: str = "",
        client_info_store: Any = None,
    ) -> None:
        self._emitter = emitter
        self._server_version = server_version or os.environ.get("MCP_VERSION", "dev")
        # Optional async Redis handle. None in dev/tests/disk mode — the local
        # tier alone still restores attribution on a single replica, so this
        # degrades rather than failing.
        self._client_info_store = client_info_store

    @staticmethod
    def _token_client_id() -> str:
        try:
            token = get_access_token()
        except Exception:
            return ""
        if token is None:
            return ""
        claims = getattr(token, "claims", {}) or {}
        return str(claims.get("client_id") or getattr(token, "client_id", "") or "")

    @classmethod
    def _connection_key(cls) -> str:
        """Per-connection clientInfo cache key, or ``''`` when there is none (#97).

        ``(DCR registration, user)``: the registration separates host programs,
        and the user separates the many people a hosted connector can serve from
        one registration (ChatGPT's are shared). Hashed so the store holds neither
        identifier. Returns ``''`` — i.e. log a blank host — when the presented
        bearer carries no client_id, or carries the SHARED Cognito app client id,
        which identifies no connection at all: a blank host is honest, a
        neighbour's host is not. Never raises.
        """
        try:
            presented = _presented_client_id()
            if not presented:
                return ""
            shared = os.environ.get("COGNITO_CLIENT_ID", "").strip() or cls._token_client_id()
            if presented == shared:
                return ""
            sub = ""
            try:
                token = get_access_token()
                sub = str((getattr(token, "claims", {}) or {}).get("sub") or "") if token else ""
            except Exception:
                sub = ""
            return hashlib.sha256(f"{presented}\x00{sub}".encode("utf-8")).hexdigest()[:32]
        except Exception:
            logger.debug("usage analytics: connection key unavailable", exc_info=True)
            return ""

    async def on_initialize(self, context: MiddlewareContext, call_next):
        # Capture from the initialize REQUEST — at this point in the chain the
        # session is not populated yet (verified: reading session.client_params
        # here raises), but message.params.clientInfo is present in both
        # stateful and stateless mode.
        try:
            params = getattr(getattr(context, "message", None), "params", None)
            info = getattr(params, "clientInfo", None)
            name = (getattr(info, "name", "") or "")[:128]
            version = (getattr(info, "version", "") or "")[:64]
            key = self._connection_key()
            if name and key:
                await self._remember_client_info(key, (name, version))
        except Exception:
            logger.debug("clientInfo capture skipped", exc_info=True)
        return await call_next(context)

    async def _remember_client_info(self, key: str, value: tuple) -> None:
        _cache_client_info_locally(key, value)
        store = self._client_info_store
        if store is None:
            return

        async def _write():
            try:
                await store.set(
                    _CLIENT_INFO_KEY.format(key=key),
                    json.dumps({"name": value[0], "version": value[1]}),
                    ex=CLIENT_INFO_TTL_SECONDS,
                )
            except Exception:
                logger.debug("clientInfo durable write skipped", exc_info=True)

        try:
            # Fire-and-forget: `initialize` must not wait on the store. The local
            # tier is already populated above, so this replica is correct either way
            # and the write only matters for the OTHER replicas.
            task = asyncio.create_task(_write())
            _client_info_writes.add(task)
            task.add_done_callback(_client_info_writes.discard)
        except RuntimeError:
            # No running loop (sync tests) — the local tier still holds the value.
            logger.debug("clientInfo durable write not scheduled", exc_info=True)

    async def _resolve_client_info(self, context) -> None:
        """Populate the contextvar for this call. Never raises, never blocks a tool."""
        _client_info.set(None)
        try:
            # Stateful transports still carry it — prefer the live value and
            # skip the lookup entirely, so this is a no-op if #63 is ever reverted.
            fc = getattr(context, "fastmcp_context", None)
            info = fc.session.client_params.clientInfo
            if getattr(info, "name", None):
                return
        except Exception:
            pass
        try:
            key = self._connection_key()
            if not key:
                return
            cached = _client_info_local.get(key)
            if cached:
                _client_info.set(cached)
                return
            store = self._client_info_store
            if store is None:
                return
            # Bounded: a stalled store must not hold up the tool call. On timeout we
            # fall through to a blank host for this call and try again on the next.
            raw = await asyncio.wait_for(
                store.get(_CLIENT_INFO_KEY.format(key=key)),
                timeout=_CLIENT_INFO_READ_TIMEOUT,
            )
            if not raw:
                return
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            value = (str(data.get("name") or ""), str(data.get("version") or ""))
            if value[0]:
                _cache_client_info_locally(key, value)
                _client_info.set(value)
        except Exception:
            logger.debug("clientInfo resolve skipped", exc_info=True)

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        started = time.monotonic()
        _tool_error.set(None)  # clear any value carried over within this context
        _tool_result_count.set(None)  # same: a stale count must not leak into this event
        call_id_token = _call_id.set(uuid.uuid4().hex)
        await self._resolve_client_info(context)
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
            # Reset AFTER _safe_emit so _build_event can still read the id.
            _call_id.reset(call_id_token)

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        started = time.monotonic()
        status, err = "ok", _ErrorInfo()
        await self._resolve_client_info(context)
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
        recorded_count = _tool_result_count.get()
        if kind == "tool" and status == "ok" and recorded_count is not None:
            # The tool's own count beats inference from the payload shape.
            metrics["result_count"] = recorded_count
            metrics["has_data"] = recorded_count > 0
        session_id = ""
        try:
            fc = getattr(context, "fastmcp_context", None)
            session_id = (getattr(fc, "session_id", "") or "")[:64]
        except Exception:
            session_id = ""
        meta = _extract_meta(_request_context(context))
        header_keys = _http_header_keys()
        conv = str(meta.get("openai/session") or "").strip()
        header_conv = _openai_session_header()
        if conv:
            correlation_id, correlation_source = conv[:128], "meta:openai/session"
        elif header_conv:
            correlation_id, correlation_source = header_conv, "header:x-openai-session"
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
            # Whatever per-request id the upstream response carried. Today that is
            # Cloudflare's cf-ray (the monolith emits no x-request-id), which the
            # origin's nginx access log already records as ray=$http_cf_ray.
            "upstream_request_id": err.request_id or "",
            # Our own per-call id, forwarded upstream as X-Client-Request-Id. The
            # Django ingest serializer ignores unknown keys, so sending this before
            # the web-repo column lands is safe — it is simply dropped.
            "client_request_id": _call_id.get(),
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
            # call, so session_id can't group its calls; its per-conversation id can.
            # correlation_id = best available stable key (openai/session in _meta >
            # x-openai-session header > Mcp-Session-Id > salted token fingerprint);
            # correlation_source records which one was used. The header tier is the one
            # that actually fires for ChatGPT traffic today — see the block comment
            # above _META_NAMESPACE for the measurement behind that ordering.
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
        if not host_name:
            # Stateless transport: the session no longer carries clientInfo, so
            # fall back to what `_resolve_client_info` looked up for this call.
            carried = _client_info.get()
            if carried:
                host_name, host_version = carried
        return sub, client_id, host_name, host_version
