"""Accept ``client_secret_basic`` on ``/token`` when the body omits ``client_id``.

Why this exists
---------------
RFC 6749 §2.3.1: a client authenticating with HTTP Basic sends its id and
secret in the ``Authorization`` header, and the request body need not repeat
``client_id``. We advertise ``client_secret_basic`` in
``token_endpoint_auth_methods_supported``, but the MCP SDK's
``ClientAuthenticator`` (mcp 1.28.1, unchanged on upstream main as of
2026-10-09) reads ``client_id`` from the form body FIRST and answers 401
``unauthorized_client`` ("Missing client_id") before it ever looks at the
header.

Glama's health checker is such a client: on 2026-10-09 a completed sign-in
handed it a valid code, and its ``POST /token`` came back 401 with no client
lookup logged, so the connector stayed "Not Authenticated". It was the only
client with a ``/token`` 401 in the 7 days before.

What this does
--------------
For ``POST /token`` carrying ``Authorization: Basic`` and a urlencoded body
without ``client_id``, append the header's (URL-decoded) client id to the body.
The SDK then authenticates exactly as it would for a client that repeated it:
it still checks the header's id matches and validates the secret. Every other
request passes through untouched.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote, unquote

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

TOKEN_PATH = "/token"
# A token request is a few hundred bytes; anything bigger passes through as is.
MAX_BODY_BYTES = 16 * 1024


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value
    return None


def basic_client_id(authorization: bytes | None) -> str | None:
    """The client id from a ``Basic`` header, URL-decoded per RFC 6749 §2.3.1."""
    if not authorization or authorization[:6].lower() != b"basic ":
        return None
    try:
        decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    return unquote(decoded.split(":", 1)[0]) or None


class TokenBasicAuthClientIdMiddleware:
    """Pure ASGI, like McpSessionIdMiddleware, so nothing else is buffered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("path") != TOKEN_PATH
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        client_id = basic_client_id(_header(scope, b"authorization"))
        content_type = (_header(scope, b"content-type") or b"").split(b";")[0].strip().lower()
        if client_id is None or content_type != b"application/x-www-form-urlencoded":
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                # Client went away mid-body: hand the app what it would have seen.
                await self.app(scope, _replay(b"".join(chunks), message, receive), send)
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            more = message.get("more_body", False)
            if size > MAX_BODY_BYTES:
                await self.app(scope, _replay(b"".join(chunks), None, receive, more), send)
                return
        body = b"".join(chunks)

        try:
            has_client_id = "client_id" in parse_qs(body.decode("ascii"))
        except UnicodeDecodeError:
            has_client_id = True  # not a form we understand; leave it alone
        if has_client_id:
            await self.app(scope, _replay(body, None, receive), send)
            return

        sep = b"&" if body else b""
        body = body + sep + b"client_id=" + quote(client_id, safe="").encode("ascii")
        headers = [(k, v) for k, v in scope.get("headers") or [] if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await self.app({**scope, "headers": headers}, _replay(body, None, receive), send)


def _replay(body: bytes, tail: Message | None, receive: Receive, more_body: bool = False) -> Receive:
    """A receive() that first yields the buffered body, then defers to the original."""
    pending: list[Message] = [{"type": "http.request", "body": body, "more_body": more_body}]
    if tail is not None:
        pending.append(tail)

    async def _receive() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return _receive
