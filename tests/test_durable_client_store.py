"""Durable DCR client registrations — survive an OAuth-cache wipe.

Why this exists: on 2026-07-14 Azure wiped the (non-persistent, Standard-SKU)
OAuth Redis out from under the server — 2,846 keys -> 20 — and every DCR client
registration was lost permanently. Tokens are recoverable (the user signs in
again); a *client registration* is NOT: hosted connectors cache the client_id on
their own servers and replay it forever, so `get_client()` misses and the client
is bricked with no self-heal path. One real client replayed a dead id 185 times
over three days.

The fix mirrors registrations into a durable tier (Postgres, via the main app's
internal endpoint) while leaving Redis as the hot path:

  - `CollectionRoutingStore` — only `mcp-oauth-proxy-clients` is mirrored; the
    five short-lived collections (codes, transactions, jti, upstream/refresh
    tokens) keep hitting Redis untouched.
  - `DurableMirrorStore`     — put writes both tiers; get reads Redis and, on a
    MISS, restores from the durable tier and RE-HYDRATES Redis.

The re-hydrate is the whole point: it turns a cache wipe from "every client
permanently dead" into "one slow lookup, then normal".

Durability must never cost availability: if the durable tier is down, put still
succeeds (WARN) and get still serves Redis. A degraded mirror must not take auth
down — that would turn a durability fix into an outage.
"""

from __future__ import annotations

import pytest

CLIENTS = "mcp-oauth-proxy-clients"
CODES = "mcp-authorization-codes"

CLIENT_ID = "9e8cf8fa-f8f2-4cfc-9378-d7b8ff9ba47e"
REGISTRATION = {
    "client_id": CLIENT_ID,
    "client_name": "Example Connector",
    "redirect_uris": ["https://example.test/connector/oauth/abc123"],
}


class FakeKV:
    """Minimal AsyncKeyValue double: dict keyed by (collection, key)."""

    def __init__(self) -> None:
        self.data: dict[tuple[str | None, str], dict] = {}
        self.gets: list[tuple[str | None, str]] = []
        self.puts: list[tuple[str | None, str]] = []

    async def get(self, key, *, collection=None):
        self.gets.append((collection, key))
        return self.data.get((collection, key))

    async def put(self, key, value, *, collection=None, ttl=None):
        self.puts.append((collection, key))
        self.data[(collection, key)] = dict(value)

    async def delete(self, key, *, collection=None):
        return self.data.pop((collection, key), None) is not None

    async def ttl(self, key, *, collection=None):
        return self.data.get((collection, key)), None


class FakeBacking:
    """Double for the durable (Postgres-over-HTTP) tier."""

    def __init__(self, *, fail: bool = False) -> None:
        self.data: dict[str, dict] = {}
        self.fail = fail
        self.gets: list[str] = []
        self.puts: list[str] = []

    async def get(self, client_id):
        self.gets.append(client_id)
        if self.fail:
            raise RuntimeError("durable tier unreachable")
        return self.data.get(client_id)

    async def put(self, client_id, payload):
        self.puts.append(client_id)
        if self.fail:
            raise RuntimeError("durable tier unreachable")
        self.data[client_id] = dict(payload)

    async def delete(self, client_id):
        if self.fail:
            raise RuntimeError("durable tier unreachable")
        return self.data.pop(client_id, None) is not None


@pytest.fixture()
def redis_kv():
    return FakeKV()


@pytest.fixture()
def backing():
    return FakeBacking()


@pytest.fixture()
def mirror(mcp_module, redis_kv, backing):
    return mcp_module.DurableMirrorStore(cache=redis_kv, backing=backing)


@pytest.fixture()
def routed(mcp_module, redis_kv, backing):
    return mcp_module.CollectionRoutingStore(
        cache=redis_kv,
        durable=mcp_module.DurableMirrorStore(cache=redis_kv, backing=backing),
        durable_collections=frozenset({CLIENTS}),
    )


class TestDurableMirrorStore:
    async def test_put_writes_both_tiers(self, mirror, redis_kv, backing):
        await mirror.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        assert redis_kv.data[(CLIENTS, CLIENT_ID)] == REGISTRATION
        assert backing.data[CLIENT_ID] == REGISTRATION

    async def test_get_hits_cache_without_touching_backing(
        self, mirror, redis_kv, backing
    ):
        await mirror.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)
        backing.gets.clear()

        assert await mirror.get(CLIENT_ID, collection=CLIENTS) == REGISTRATION
        assert backing.gets == []  # hot path must not call the durable tier

    async def test_cache_miss_restores_from_backing(self, mirror, redis_kv, backing):
        # The wipe: durable tier still has it, Redis does not.
        backing.data[CLIENT_ID] = dict(REGISTRATION)

        assert await mirror.get(CLIENT_ID, collection=CLIENTS) == REGISTRATION

    async def test_cache_miss_rehydrates_the_cache(self, mirror, redis_kv, backing):
        backing.data[CLIENT_ID] = dict(REGISTRATION)

        await mirror.get(CLIENT_ID, collection=CLIENTS)

        # Restored into Redis, so the NEXT lookup is a plain cache hit.
        assert redis_kv.data[(CLIENTS, CLIENT_ID)] == REGISTRATION
        backing.gets.clear()
        await mirror.get(CLIENT_ID, collection=CLIENTS)
        assert backing.gets == []

    async def test_unknown_client_is_none(self, mirror):
        assert await mirror.get("never-registered", collection=CLIENTS) is None

    async def test_delete_clears_both_tiers(self, mirror, redis_kv, backing):
        await mirror.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        await mirror.delete(CLIENT_ID, collection=CLIENTS)

        assert (CLIENTS, CLIENT_ID) not in redis_kv.data
        assert CLIENT_ID not in backing.data


class TestDegradedDurableTier:
    """A broken mirror must never break auth."""

    @pytest.fixture()
    def broken(self, mcp_module, redis_kv):
        return mcp_module.DurableMirrorStore(
            cache=redis_kv, backing=FakeBacking(fail=True)
        )

    async def test_put_still_succeeds_when_backing_fails(self, broken, redis_kv):
        await broken.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        # Registration must still work — just without durability.
        assert redis_kv.data[(CLIENTS, CLIENT_ID)] == REGISTRATION

    async def test_put_warns_when_backing_fails(self, broken, caplog):
        with caplog.at_level("WARNING"):
            await broken.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        assert any("durab" in r.message.lower() for r in caplog.records)

    async def test_cache_hit_unaffected_by_broken_backing(self, broken, redis_kv):
        redis_kv.data[(CLIENTS, CLIENT_ID)] = dict(REGISTRATION)

        assert await broken.get(CLIENT_ID, collection=CLIENTS) == REGISTRATION

    async def test_miss_with_broken_backing_returns_none(self, broken):
        assert await broken.get(CLIENT_ID, collection=CLIENTS) is None

    async def test_backing_never_logs_the_payload(self, broken, caplog):
        """Registrations can carry secrets — never log the object."""
        with caplog.at_level("WARNING"):
            await broken.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        blob = " ".join(r.getMessage() for r in caplog.records)
        assert "Example Connector" not in blob
        assert "example.test" not in blob


class TestWireUp:
    """`_build_oauth_storage` decides whether the mirror is active at all.

    It must be INERT unless fully configured, so the change can ship dark and
    roll back by unsetting one env var.
    """

    def test_returns_cache_unchanged_when_url_unset(self, mcp_module, redis_kv):
        got = mcp_module._build_oauth_storage(redis_kv, "", "secret")
        assert got is redis_kv

    def test_returns_cache_unchanged_when_secret_unset(self, mcp_module, redis_kv):
        got = mcp_module._build_oauth_storage(redis_kv, "https://api.test/x/", "")
        assert got is redis_kv

    def test_disk_mode_is_left_alone(self, mcp_module):
        """No Redis (dev/tests) -> don't wrap None."""
        got = mcp_module._build_oauth_storage(None, "https://api.test/x/", "secret")
        assert got is None

    def test_wraps_when_fully_configured(self, mcp_module, redis_kv):
        got = mcp_module._build_oauth_storage(redis_kv, "https://api.test/x/", "secret")
        assert isinstance(got, mcp_module.CollectionRoutingStore)

    async def test_wrapped_store_mirrors_only_registrations(self, mcp_module, redis_kv):
        got = mcp_module._build_oauth_storage(redis_kv, "https://api.test/x/", "secret")

        # Codes still land in the plain cache, untouched by the durable path.
        await got.put("code-1", {"code": "x"}, collection=CODES)
        assert redis_kv.data[(CODES, "code-1")] == {"code": "x"}

    def test_only_the_client_collection_is_durable(self, mcp_module, redis_kv):
        got = mcp_module._build_oauth_storage(redis_kv, "https://api.test/x/", "secret")
        assert got._durable_collections == frozenset(
            {mcp_module.OAUTH_CLIENTS_COLLECTION}
        )


class TestCollectionRouting:
    async def test_client_collection_is_mirrored(self, routed, backing):
        await routed.put(CLIENT_ID, REGISTRATION, collection=CLIENTS)

        assert backing.puts == [CLIENT_ID]

    async def test_short_lived_collections_stay_on_redis(
        self, routed, redis_kv, backing
    ):
        await routed.put("code-1", {"code": "x"}, collection=CODES)

        assert backing.puts == []  # auth codes must never hit Postgres
        assert redis_kv.data[(CODES, "code-1")] == {"code": "x"}

    async def test_default_collection_is_not_mirrored(self, routed, backing):
        await routed.put("k", {"v": 1}, collection=None)

        assert backing.puts == []

    async def test_routed_get_reads_through_for_clients(self, routed, backing):
        backing.data[CLIENT_ID] = dict(REGISTRATION)

        assert await routed.get(CLIENT_ID, collection=CLIENTS) == REGISTRATION

    async def test_routed_get_does_not_read_through_for_codes(self, routed, backing):
        assert await routed.get("code-1", collection=CODES) is None
        assert backing.gets == []
