"""OAuth client-lookup observability — logging-only, zero behaviour change.

These cover the DCR "invalid_client" diagnosis additions:

  - `_instance_id()`            -> replica id for multi-replica misrouting visibility
  - `_redis_db_number()`        -> DB segment of the Redis URL (no secret)
  - `_disk_store_path()`        -> ephemeral DiskStore location for the startup line
  - `_ClientLookupLoggingMixin` -> per-lookup HIT/MISS log around get_client()

The mixin must (a) return EXACTLY what super().get_client() returns, (b) log the
client_id + a boolean found + the instance id, and (c) NEVER log the resolved
client object, a secret, a token, an auth code, or a PKCE verifier.
"""
from __future__ import annotations

import logging

import pytest


def test_instance_id_prefers_container_app_replica_name(mcp_module, monkeypatch):
    monkeypatch.setenv("CONTAINER_APP_REPLICA_NAME", "mcp--abc123-xyz")
    assert mcp_module._instance_id() == "mcp--abc123-xyz"


def test_instance_id_falls_back_to_hostname(mcp_module, monkeypatch):
    monkeypatch.delenv("CONTAINER_APP_REPLICA_NAME", raising=False)
    # Falls back to a non-empty hostname; never raises, never empty.
    assert mcp_module._instance_id()


def test_redis_db_number_parses_path_segment(mcp_module):
    assert mcp_module._redis_db_number("rediss://:tok@host:6380/3") == "3"


def test_redis_db_number_unknown_when_absent(mcp_module):
    assert mcp_module._redis_db_number("rediss://:tok@host:6380") == "?"


def test_redis_db_number_unparseable_is_unknown(mcp_module):
    # Non-numeric path segment -> "?", never a throw.
    assert mcp_module._redis_db_number("rediss://host/not-a-number") == "?"


def test_disk_store_path_is_a_string(mcp_module):
    # Resolves to the FastMCP data dir / oauth-proxy, or a descriptive fallback.
    path = mcp_module._disk_store_path()
    assert isinstance(path, str) and path


def test_both_logging_provider_subclasses_inherit_real_providers(mcp_module):
    from fastmcp.server.auth.oauth_proxy import OAuthProxy
    from fastmcp.server.auth.providers.aws import AWSCognitoProvider

    # isinstance must still hold so downstream FastMCP/SDK behaviour is unchanged.
    assert issubclass(mcp_module._LoggingOAuthProxy, OAuthProxy)
    assert issubclass(mcp_module._LoggingAWSCognitoProvider, AWSCognitoProvider)


class _FakeClient:
    """Stand-in for an OAuthClientInformationFull with a sensitive attr that must
    NOT be logged. If the mixin ever logged the object, this value would leak."""

    client_id = "client-abc"
    client_secret = "SENSITIVE-SHOULD-NEVER-APPEAR"


def _make_probe(mcp_module, return_value):
    """A class using the mixin whose super().get_client() returns return_value."""

    class _Base:
        async def get_client(self, client_id):
            return return_value

    class _Probe(mcp_module._ClientLookupLoggingMixin, _Base):
        pass

    return _Probe()


@pytest.mark.asyncio
async def test_lookup_hit_returns_client_and_logs_found_true(mcp_module, caplog):
    client = _FakeClient()
    probe = _make_probe(mcp_module, client)

    with caplog.at_level(logging.INFO, logger="financial-reports-mcp"):
        result = await probe.get_client("client-abc")

    # Behaviour preserved: returns exactly what super() returned.
    assert result is client

    text = caplog.text
    assert "client_id=client-abc" in text
    assert "found=True" in text
    # No secret/object leakage.
    assert "SENSITIVE-SHOULD-NEVER-APPEAR" not in text


@pytest.mark.asyncio
async def test_lookup_miss_returns_none_and_logs_warning(mcp_module, caplog):
    probe = _make_probe(mcp_module, None)

    with caplog.at_level(logging.INFO, logger="financial-reports-mcp"):
        result = await probe.get_client("ghost-client")

    # Behaviour preserved: None stays None (the invalid_client path).
    assert result is None

    records = [r for r in caplog.records if r.name == "financial-reports-mcp"]
    assert any("found=False" in r.getMessage() for r in records)
    # The MISS is escalated to WARNING so it stands out in prod logs.
    assert any(
        r.levelno == logging.WARNING and "MISS" in r.getMessage() for r in records
    )


@pytest.mark.asyncio
async def test_lookup_log_contains_instance_id(mcp_module, caplog, monkeypatch):
    # The replica id must appear so cross-replica misrouting is visible. The
    # mixin reads the module-level INSTANCE_ID resolved at import.
    probe = _make_probe(mcp_module, None)
    with caplog.at_level(logging.INFO, logger="financial-reports-mcp"):
        await probe.get_client("any-client")
    assert f"instance={mcp_module.INSTANCE_ID}" in caplog.text
