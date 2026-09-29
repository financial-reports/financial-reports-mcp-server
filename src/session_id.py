"""Issue an ``Mcp-Session-Id`` so one client connection's calls can be grouped.

Why this exists
---------------
The connector runs with ``stateless_http=True`` (#63): a fresh transport per
request, no in-memory session table, because replicas behind Cloud Run have no
session affinity. A stateless transport never *issues* ``Mcp-Session-Id``, so a
conforming client never *sends* one, and FastMCP's ``Context.session_id`` then
mints a fresh uuid per request. Measured on prod telemetry (7 days to
2026-09-29): every ``mcp_session`` correlation id grouped exactly 1.00 calls —
claude-code 1,886 ids for 1,886 calls, claude.ai 1,647/1,647, Glean 1,398/1,398.
Nothing could say which calls belonged to one conversation.

What this does
--------------
On the HTTP response to an ``initialize`` request that arrived WITHOUT a session
id, add ``Mcp-Session-Id: fr-<random>``. Clients echo it on every later request
(MCP spec, Transports > Session Management), FastMCP's ``Context.session_id``
reads the echoed header, and the usage-analytics event already records it as
``session_id`` / ``correlation_id`` — no backend change.

It stays stateless: the id is random, never stored, never validated. The
stateless transport runs with ``mcp_session_id=None`` and so skips session
validation, which means an id minted on replica A is accepted by replica B —
exactly the property #63 needed. The id carries no user or token material.

Side effect handled here
------------------------
A client holding a session id may open a standalone ``GET /mcp`` SSE stream for
server-initiated messages (the Python MCP client does so only when it has a
session id). A stateless server can never deliver on that stream, so it would
only idle — the ``stream_timeout`` noise #63 removed. We answer such a GET with
405, which the spec explicitly allows and clients handle (the Python client
gives up after 2 attempts). This applies only to GETs carrying an id WE issued
(``fr-`` prefix), so no existing client's behaviour changes. ``DELETE`` with a
session id is already answered 405 by the stateless transport.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SESSION_HEADER = b"mcp-session-id"
SESSION_PREFIX = "fr-"
# Only bodies small enough to be an `initialize` are inspected; anything larger,
# or without a Content-Length, passes through untouched (no id issued).
MAX_PEEK_BYTES = 64 * 1024


def new_session_id() -> str:
    """A fresh opaque id: visible ASCII only (spec), <= 64 chars (ingest cap)."""
    return SESSION_PREFIX + secrets.token_urlsafe(24)


def _is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value
    return None


def _is_initialize(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    messages = payload if isinstance(payload, list) else [payload]
    return any(isinstance(m, dict) and m.get("method") == "initialize" for m in messages)


async def _send_405(send: Send) -> None:
    body = b'{"error":"method_not_allowed","error_description":"This server does not offer a standalone SSE stream."}'
    await send({
        "type": "http.response.start",
        "status": 405,
        "headers": [
            (b"content-type", b"application/json"),
            (b"allow", b"POST, DELETE"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class McpSessionIdMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so SSE responses stream untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not _is_mcp_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        incoming = _header(scope, SESSION_HEADER)

        if method == "GET" and incoming and incoming.startswith(SESSION_PREFIX.encode()):
            await _send_405(send)
            return

        if method != "POST" or incoming:
            await self.app(scope, receive, send)
            return

        length = _header(scope, b"content-length")
        try:
            size = int(length) if length is not None else -1
        except ValueError:
            size = -1
        if not 0 <= size <= MAX_PEEK_BYTES:
            await self.app(scope, receive, send)
            return

        # Buffer the (small) body, then replay it to the app unchanged.
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                # Client went away mid-body: hand the app what it would have seen.
                await self.app(scope, _replay(chunks, message, receive), send)
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)

        replay = _replay([body], None, receive)
        if not _is_initialize(body):
            await self.app(scope, replay, send)
            return

        session_id = new_session_id().encode()

        async def send_with_session(message: Message) -> None:
            if message["type"] == "http.response.start" and 200 <= message.get("status", 0) < 300:
                headers = list(message.get("headers") or [])
                if not any(k.lower() == SESSION_HEADER for k, _ in headers):
                    headers.append((SESSION_HEADER, session_id))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, replay, send_with_session)


def _replay(chunks: list[bytes], tail: Message | None, receive: Receive) -> Receive:
    """A receive() that first yields the buffered body, then defers to the original."""
    pending: list[Message] = [
        {"type": "http.request", "body": b"".join(chunks), "more_body": False}
    ]
    if tail is not None:
        pending.append(tail)

    async def _receive() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return _receive
