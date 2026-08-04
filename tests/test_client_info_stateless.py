"""clientInfo must survive the stateless transport.

`clientInfo` is sent once, in the MCP `initialize` handshake. Under
`stateless_http=True` (#63) a fresh transport is built per request, so
`session.client_params` is gone by the time a tool call arrives and every
analytics event logged a blank host — 100% blank in prod from 2026-07-16.

These tests pin the carry-over: capture at initialize, key by OAuth client_id
(which rides the access token, not the session), resolve on the way into an
event, and never let any of it touch a real tool call.
"""
import json

import pytest

from src.usage_analytics import (
    CLIENT_INFO_TTL_SECONDS,
    UsageAnalyticsEmitter,
    UsageAnalyticsMiddleware,
    _client_info,
    _client_info_local,
)

CLIENT_ID = "client-abc"


class FakeRedis:
    def __init__(self):
        self.kv, self.gets, self.sets, self.last_ttl = {}, 0, 0, None

    async def set(self, key, value, ex=None):
        self.kv[key] = value
        self.sets += 1
        self.last_ttl = ex

    async def get(self, key):
        self.gets += 1
        return self.kv.get(key)


class ExplodingRedis:
    async def set(self, key, value, ex=None):
        raise RuntimeError("redis down")

    async def get(self, key):
        raise RuntimeError("redis down")


class _Ctx:
    """A context with no usable session — i.e. what stateless mode delivers."""
    fastmcp_context = None


def _mw(store, monkeypatch):
    monkeypatch.setattr(
        UsageAnalyticsMiddleware, "_token_client_id", staticmethod(lambda: CLIENT_ID)
    )
    return UsageAnalyticsMiddleware(
        UsageAnalyticsEmitter("http://ingest.invalid/", "secret"),
        server_version="test",
        client_info_store=store,
    )


@pytest.fixture(autouse=True)
def _clean():
    _client_info_local.clear()
    _client_info.set(None)
    yield
    _client_info_local.clear()
    _client_info.set(None)


@pytest.mark.asyncio
async def test_resolves_cross_replica_via_shared_store(monkeypatch):
    """Initialize on replica A, tool call on replica B with a cold process."""
    store = FakeRedis()
    mw = _mw(store, monkeypatch)
    await mw._remember_client_info(CLIENT_ID, ("Anthropic/ClaudeAI", "2.1"))

    _client_info_local.clear()  # replica B has never seen this client
    await mw._resolve_client_info(_Ctx())

    assert _client_info.get() == ("Anthropic/ClaudeAI", "2.1")
    assert store.gets == 1
    assert store.last_ttl == CLIENT_INFO_TTL_SECONDS


@pytest.mark.asyncio
async def test_second_call_is_memoised(monkeypatch):
    """The shared store is read once per client per process, not per call."""
    store = FakeRedis()
    mw = _mw(store, monkeypatch)
    await mw._remember_client_info(CLIENT_ID, ("claude-code", "1.0"))
    _client_info_local.clear()

    await mw._resolve_client_info(_Ctx())
    reads_after_first = store.gets
    _client_info.set(None)
    await mw._resolve_client_info(_Ctx())

    assert store.gets == reads_after_first  # no extra round-trip
    assert _client_info.get() == ("claude-code", "1.0")


@pytest.mark.asyncio
async def test_degrades_without_a_store(monkeypatch):
    """Disk mode (dev/tests): no store, cold cache — resolve to nothing, quietly."""
    mw = _mw(None, monkeypatch)
    await mw._resolve_client_info(_Ctx())
    assert _client_info.get() is None


@pytest.mark.asyncio
async def test_store_failure_never_propagates(monkeypatch):
    """A dead Redis must not raise into a tool call — capture is best-effort."""
    mw = _mw(ExplodingRedis(), monkeypatch)
    await mw._remember_client_info(CLIENT_ID, ("openai-mcp", "0.9"))
    await mw._resolve_client_info(_Ctx())
    # The local tier still answered even though the durable write blew up.
    assert _client_info.get() == ("openai-mcp", "0.9")


@pytest.mark.asyncio
async def test_identity_falls_back_to_carried_value(monkeypatch):
    """_identity() is what builds the event — it must use the carried value."""
    mw = _mw(FakeRedis(), monkeypatch)
    await mw._remember_client_info(CLIENT_ID, ("Anthropic/ClaudeAI", "2.1"))
    await mw._resolve_client_info(_Ctx())

    _sub, _client_id, host_name, host_version = mw._identity(_Ctx())
    assert (host_name, host_version) == ("Anthropic/ClaudeAI", "2.1")


@pytest.mark.asyncio
async def test_local_cache_is_bounded(monkeypatch):
    """A hostile client cannot grow the process cache without limit."""
    from src.usage_analytics import _CLIENT_INFO_LOCAL_MAX

    mw = _mw(None, monkeypatch)
    for i in range(_CLIENT_INFO_LOCAL_MAX + 25):
        await mw._remember_client_info(f"client-{i}", (f"host-{i}", "1"))
    assert len(_client_info_local) <= _CLIENT_INFO_LOCAL_MAX


@pytest.mark.asyncio
async def test_durable_payload_is_json_round_trippable(monkeypatch):
    store = FakeRedis()
    mw = _mw(store, monkeypatch)
    await mw._remember_client_info(CLIENT_ID, ("Anthropic/ClaudeAI", "2.1"))
    raw = store.kv[f"mcp-client-info::{CLIENT_ID}"]
    assert json.loads(raw) == {"name": "Anthropic/ClaudeAI", "version": "2.1"}
