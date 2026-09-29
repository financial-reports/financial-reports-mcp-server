"""Mcp-Session-Id issuance under the stateless transport.

Before this, every `mcp_session` correlation id in prod telemetry grouped exactly
one call (claude-code 1,886 ids / 1,886 calls over 7 days), because a stateless
server never issues an id and FastMCP then mints a fresh one per request. See
src/session_id.py for the full rationale.

The end-to-end tests run the middleware in front of a REAL `stateless_http=True`
FastMCP app, so they pin the property that matters: an id issued on `initialize`,
echoed by the client, is what a tool's `Context.session_id` sees on later calls.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Context, FastMCP

from src.session_id import (
    MAX_PEEK_BYTES,
    SESSION_PREFIX,
    McpSessionIdMiddleware,
    new_session_id,
)

ACCEPT = "application/json, text/event-stream"
PROTO = "2025-06-18"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": PROTO,
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}


def _build_app():
    mcp = FastMCP("session-id-test")

    @mcp.tool
    def whoami(ctx: Context) -> str:
        return ctx.session_id

    inner = mcp.http_app(path="/mcp", stateless_http=True)
    return inner, McpSessionIdMiddleware(inner)


async def _client(app, inner):
    # The inner app's lifespan starts the session manager's task group.
    lifespan = inner.router.lifespan_context(inner)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return client, lifespan


def _json_rpc_result(resp: httpx.Response) -> dict:
    text = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        return json.loads(data[-1])
    return resp.json()


@pytest.mark.asyncio
async def test_initialize_issues_session_id_and_tool_sees_the_echoed_id():
    inner, app = _build_app()
    client, lifespan = await _client(app, inner)
    try:
        r = await client.post("/mcp", json=INIT, headers={"accept": ACCEPT})
        assert r.status_code == 200, r.text
        sid = r.headers.get("mcp-session-id")
        assert sid and sid.startswith(SESSION_PREFIX)

        headers = {"accept": ACCEPT, "mcp-session-id": sid, "mcp-protocol-version": PROTO}
        await client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers
        )
        seen = []
        for i in (2, 3):
            call = {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": "whoami", "arguments": {}}}
            r = await client.post("/mcp", json=call, headers=headers)
            assert r.status_code == 200, r.text
            # No new id is issued once the client presents one.
            assert "mcp-session-id" not in {k.lower() for k in r.headers.keys()} or \
                r.headers.get("mcp-session-id") == sid
            seen.append(_json_rpc_result(r)["result"]["content"][0]["text"])
        # Both calls carry the same id, and it is the one we issued: groupable.
        assert seen == [sid, sid]
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_negative_control_without_the_middleware_ids_differ_per_call():
    """The defect this fixes: without an issued id, each call gets a fresh one."""
    inner, _ = _build_app()
    client, lifespan = await _client(inner, inner)
    try:
        r = await client.post("/mcp", json=INIT, headers={"accept": ACCEPT})
        assert "mcp-session-id" not in {k.lower() for k in r.headers.keys()}
        headers = {"accept": ACCEPT, "mcp-protocol-version": PROTO}
        seen = []
        for i in (2, 3):
            call = {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": "whoami", "arguments": {}}}
            r = await client.post("/mcp", json=call, headers=headers)
            seen.append(_json_rpc_result(r)["result"]["content"][0]["text"])
        assert seen[0] != seen[1]
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


# ---- unit-level behaviour against a stub app -------------------------------

class _Stub:
    """Records the body the wrapped app received; answers with a fixed status."""

    def __init__(self, status=200, headers=None):
        self.status, self.headers, self.bodies, self.calls = status, headers or [], [], 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        body, more = b"", True
        while more:
            m = await receive()
            body += m.get("body", b"")
            more = m.get("more_body", False)
        self.bodies.append(body)
        await send({"type": "http.response.start", "status": self.status, "headers": self.headers})
        await send({"type": "http.response.body", "body": b"{}"})


async def _post(app, body: bytes, path="/mcp", headers=None, method="POST"):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    async with client:
        return await client.request(method, path, content=body, headers=headers or {})


@pytest.mark.asyncio
async def test_non_initialize_post_gets_no_id_and_body_is_replayed_intact():
    stub = _Stub()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    r = await _post(McpSessionIdMiddleware(stub), body)
    assert "mcp-session-id" not in r.headers
    assert stub.bodies == [body]


@pytest.mark.asyncio
async def test_batch_containing_initialize_gets_an_id():
    stub = _Stub()
    body = json.dumps([INIT]).encode()
    r = await _post(McpSessionIdMiddleware(stub), body)
    assert r.headers["mcp-session-id"].startswith(SESSION_PREFIX)
    assert stub.bodies == [body]


@pytest.mark.asyncio
async def test_error_response_to_initialize_gets_no_id():
    stub = _Stub(status=401)
    r = await _post(McpSessionIdMiddleware(stub), json.dumps(INIT).encode())
    assert r.status_code == 401
    assert "mcp-session-id" not in r.headers


@pytest.mark.asyncio
async def test_client_supplied_id_is_left_alone():
    """ChatGPT mints its own per call; we neither replace it nor add a second."""
    stub = _Stub()
    r = await _post(McpSessionIdMiddleware(stub), json.dumps(INIT).encode(),
                    headers={"mcp-session-id": "theirs"})
    assert "mcp-session-id" not in r.headers


@pytest.mark.asyncio
async def test_oversized_body_passes_through_uninspected():
    stub = _Stub()
    body = json.dumps({**INIT, "pad": "x" * (MAX_PEEK_BYTES + 1)}).encode()
    r = await _post(McpSessionIdMiddleware(stub), body)
    assert "mcp-session-id" not in r.headers
    assert stub.bodies == [body]


@pytest.mark.asyncio
async def test_non_mcp_paths_untouched():
    stub = _Stub()
    r = await _post(McpSessionIdMiddleware(stub), json.dumps(INIT).encode(), path="/register")
    assert "mcp-session-id" not in r.headers


@pytest.mark.asyncio
async def test_get_with_our_id_is_405_and_never_reaches_the_app():
    stub = _Stub()
    r = await _post(McpSessionIdMiddleware(stub), b"", method="GET",
                    headers={"mcp-session-id": new_session_id(), "accept": "text/event-stream"})
    assert r.status_code == 405
    assert r.headers["allow"] == "POST, DELETE"
    assert stub.calls == 0


@pytest.mark.asyncio
async def test_get_with_a_foreign_id_is_unchanged():
    stub = _Stub()
    r = await _post(McpSessionIdMiddleware(stub), b"", method="GET",
                    headers={"mcp-session-id": "theirs"})
    assert r.status_code == 200
    assert stub.calls == 1


def test_session_id_shape():
    ids = {new_session_id() for _ in range(200)}
    assert len(ids) == 200
    for sid in ids:
        assert sid.startswith(SESSION_PREFIX) and len(sid) <= 64
        assert all(0x21 <= ord(c) <= 0x7E for c in sid)  # spec: visible ASCII only
