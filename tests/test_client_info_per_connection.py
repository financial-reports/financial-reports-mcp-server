"""clientInfo must be attributed per connection, not per Cognito app client (#97).

Every host reaches this server through ONE Cognito app client, so the
`client_id` claim on the swapped upstream token is the same for Claude, Codex,
ChatGPT, Cursor, ... Keying the clientInfo cache on it made the cache a single
global slot: whichever host most recently sent `initialize` was stamped on every
later tool call, from every host and every user (12 host names on one id in
prod).

These tests run REAL dispatch: a FastMCP server with `stateless_http=True` (as
prod runs), real Streamable-HTTP clients with distinct `clientInfo`, and an auth
provider that behaves like the OAuth proxy's token swap — the bearer each client
presents is a per-registration reference JWT, the validated token it resolves to
carries the shared Cognito client id. Hand-driven middleware stubs passed while
production was broken (the issue says so explicitly), so the interleaving here
goes through the transport.
"""
from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager

import mcp.types as mt
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.utilities.tests import find_available_port

from src import usage_analytics
from src.usage_analytics import (
    UsageAnalyticsMiddleware,
    _client_info,
    _client_info_local,
)

SHARED_COGNITO_CLIENT_ID = "shared-cognito-app-client"


def _b64(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _reference_jwt(client_id: str, sub: str) -> str:
    # Shaped like the proxy's HS256 reference token. Built at runtime so no
    # token-shaped literal sits in the source; the signature is never checked by
    # the fake verifier below (the real proxy verifies it before we ever run).
    return ".".join([_b64({"alg": "HS256", "typ": "JWT"}),
                     _b64({"client_id": client_id, "sub": sub, "jti": client_id + sub}),
                     "c2lnbmF0dXJl"])


class _SwapLikeVerifier(TokenVerifier):
    """Accepts the reference JWT and returns what the Cognito swap returns: a
    token whose client_id is the SHARED app client, whatever registration the
    caller used."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except Exception:
            return None
        return AccessToken(
            token="upstream-cognito-token",
            client_id=SHARED_COGNITO_CLIENT_ID,
            scopes=[],
            claims={"sub": claims["sub"], "client_id": SHARED_COGNITO_CLIENT_ID},
        )


class _FakeEmitter:
    def __init__(self):
        self.events = []
        self.enabled = True

    def emit(self, event):
        self.events.append(event)


@asynccontextmanager
async def _stateless_server(emitter):
    server = FastMCP("client-info-probe", auth=_SwapLikeVerifier())
    server.add_middleware(UsageAnalyticsMiddleware(emitter, server_version="test"))

    @server.tool
    def ping(tag: str) -> str:
        return tag

    port = find_available_port()
    task = asyncio.create_task(server.run_http_async(
        host="127.0.0.1", port=port, transport="http", path="/mcp",
        show_banner=False, stateless_http=True,
    ))
    await server._started.wait()
    await asyncio.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


def _client(url, *, registration, sub, host):
    transport = StreamableHttpTransport(
        url, headers={"Authorization": f"Bearer {_reference_jwt(registration, sub)}"}
    )
    return Client(transport, client_info=mt.Implementation(name=host, version="9.9"))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COGNITO_CLIENT_ID", raising=False)
    _client_info_local.clear()
    _client_info.set(None)
    yield
    _client_info_local.clear()
    _client_info.set(None)




@pytest.mark.asyncio
async def test_two_hosts_under_one_cognito_client_do_not_overwrite_each_other():
    emitter = _FakeEmitter()
    async with _stateless_server(emitter) as url:
        a = _client(url, registration="dcr-claude-code", sub="user-1", host="claude-code")
        b = _client(url, registration="dcr-openai", sub="user-1", host="openai-mcp")
        async with a, b:                 # both initialize; B's handshake lands LAST
            await a.call_tool("ping", {"tag": "a"})
            await b.call_tool("ping", {"tag": "b"})
            await a.call_tool("ping", {"tag": "a"})

    tool_events = [e for e in emitter.events if e["kind"] == "tool"]
    assert [e["host_name"] for e in tool_events] == ["claude-code", "openai-mcp", "claude-code"]
    # The shared Cognito id is still what identifies the app client — unchanged.
    assert {e["client_id"] for e in tool_events} == {SHARED_COGNITO_CLIENT_ID}


@pytest.mark.asyncio
async def test_same_registration_different_users_are_separate():
    """A hosted connector (e.g. ChatGPT) can serve many users from ONE
    registration; one user's handshake must not label another user's calls."""
    emitter = _FakeEmitter()
    async with _stateless_server(emitter) as url:
        u1 = _client(url, registration="dcr-shared-connector", sub="user-1", host="openai-mcp")
        u2 = _client(url, registration="dcr-shared-connector", sub="user-2", host="openai-mcp (Codex)")
        async with u1, u2:
            await u1.call_tool("ping", {"tag": "1"})
            await u2.call_tool("ping", {"tag": "2"})

    assert [e["host_name"] for e in emitter.events if e["kind"] == "tool"] == [
        "openai-mcp", "openai-mcp (Codex)",
    ]


@pytest.mark.asyncio
async def test_bearer_carrying_the_shared_cognito_id_gets_blank_not_a_neighbours_name():
    """No per-connection key -> blank. A presented bearer whose client_id IS the
    shared Cognito app client identifies nothing, so it must neither be written
    under that id nor read back another host's label."""
    emitter = _FakeEmitter()
    async with _stateless_server(emitter) as url:
        good = _client(url, registration="dcr-claude-code", sub="user-1", host="claude-code")
        bare = _client(url, registration=SHARED_COGNITO_CLIENT_ID, sub="user-1", host="mystery-host")
        async with good, bare:
            await bare.call_tool("ping", {"tag": "x"})
            await good.call_tool("ping", {"tag": "y"})

    assert [e["host_name"] for e in emitter.events if e["kind"] == "tool"] == ["", "claude-code"]


# --- the key itself -----------------------------------------------------------

def _key_with(monkeypatch, *, headers, sub="user-1", validated_client_id=SHARED_COGNITO_CLIENT_ID):
    import types

    token = types.SimpleNamespace(
        claims={"sub": sub, "client_id": validated_client_id}, client_id=validated_client_id
    )
    monkeypatch.setattr(usage_analytics, "get_access_token", lambda: token)
    monkeypatch.setattr(usage_analytics, "get_http_headers", lambda include_all=False: headers)
    return UsageAnalyticsMiddleware._connection_key()


def _bearer(registration, sub="user-1"):
    return {"authorization": f"Bearer {_reference_jwt(registration, sub)}"}


def test_key_distinguishes_registrations_and_users(monkeypatch):
    a = _key_with(monkeypatch, headers=_bearer("dcr-a"))
    b = _key_with(monkeypatch, headers=_bearer("dcr-b"))
    a2 = _key_with(monkeypatch, headers=_bearer("dcr-a"), sub="user-2")
    assert a and b and a2 and len({a, b, a2}) == 3
    assert a == _key_with(monkeypatch, headers=_bearer("dcr-a"))  # stable


def test_key_holds_neither_identifier(monkeypatch):
    key = _key_with(monkeypatch, headers=_bearer("dcr-a"), sub="user-1")
    assert "dcr-a" not in key and "user-1" not in key


@pytest.mark.parametrize("headers", [
    {},                                                    # no bearer (dev mode / probes)
    {"authorization": "Basic abc"},
    {"authorization": "Bearer not-a-jwt"},
    {"authorization": "Bearer a.%%%.c"},                    # undecodable payload
    {"authorization": "Bearer " + _reference_jwt("dcr-a", "u") + "x" * 9000},  # oversized
])
def test_no_usable_bearer_means_no_key(monkeypatch, headers):
    assert _key_with(monkeypatch, headers=headers) == ""


def test_bearer_with_the_shared_cognito_id_is_no_key(monkeypatch):
    assert _key_with(monkeypatch, headers=_bearer(SHARED_COGNITO_CLIENT_ID)) == ""


def test_configured_cognito_client_id_is_the_shared_id(monkeypatch):
    """In prod the shared id is configured; honour it even if the validated token
    ever carried a different client_id (the #32 reference-token fallback)."""
    monkeypatch.setenv("COGNITO_CLIENT_ID", "configured-app-client")
    assert _key_with(monkeypatch, headers=_bearer("configured-app-client"),
                     validated_client_id="dcr-other") == ""
