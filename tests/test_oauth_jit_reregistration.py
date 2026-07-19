"""JIT re-registration heals orphaned hosted connectors instead of dead-ending.

A registration lost from the OAuth-state store (the 2026-07-14 wipe, an eviction,
or a client older than the durable mirror) makes get_client() return None -> the
"reconnect" page. A hosted connector (ChatGPT, Claude.ai) caches its client_id on
the vendor's servers and never re-registers, so that dead end is permanent.

`_JitReregistrationMixin` closes the hole: on a miss it reconstructs a *public*
ProxyDCRClient bounded by the proxy's trusted redirect allowlist. A connector
presenting a trusted redirect self-heals; an unknown client_id with an untrusted
redirect is still rejected. It grants no new capability and never widens trust.
"""
from __future__ import annotations

import pytest
from fastmcp.server.auth.oauth_proxy import ProxyDCRClient
from pydantic import AnyUrl

ALLOWLIST = [
    "https://chatgpt.com/*",
    "https://claude.ai/api/mcp/auth_callback",
    "http://localhost:*",
]


def _jit_probe(mcp_module, super_returns, *, allowlist=ALLOWLIST, scope="openid email profile"):
    """A class composing the JIT mixin whose super().get_client() returns super_returns.

    Mirrors the probe pattern in test_oauth_lookup_logging.py: the fake base carries
    the two OAuthProxy attributes the reconstruction reads.
    """

    class _Base:
        _allowed_client_redirect_uris = allowlist
        _default_scope_str = scope

        async def get_client(self, client_id):
            return super_returns

    class _Probe(mcp_module._JitReregistrationMixin, _Base):
        pass

    return _Probe()


@pytest.mark.asyncio
async def test_miss_with_allowlist_reconstructs_public_client(mcp_module):
    client = await _jit_probe(mcp_module, None).get_client("9e8cf8fa-orphan")

    assert isinstance(client, ProxyDCRClient)
    assert str(client.client_id) == "9e8cf8fa-orphan"
    # A *public* client is minted — never a secret, never confidential auth.
    assert client.client_secret is None
    assert client.token_endpoint_auth_method == "none"
    # Bounded by exactly the proxy's trusted allowlist — trust is not widened.
    assert client.allowed_redirect_uri_patterns == ALLOWLIST


@pytest.mark.asyncio
async def test_reconstructed_client_accepts_trusted_rejects_untrusted(mcp_module):
    client = await _jit_probe(mcp_module, None).get_client("orphan")

    # A real ChatGPT connector redirect (matches https://chatgpt.com/*) is accepted.
    accepted = client.validate_redirect_uri(
        AnyUrl("https://chatgpt.com/connector/oauth/gtv66NzA9wze")
    )
    assert str(accepted).startswith("https://chatgpt.com/")

    # An attacker-controlled redirect is rejected — JIT never widens trust.
    with pytest.raises(Exception):
        client.validate_redirect_uri(AnyUrl("https://evil.example.com/steal"))


@pytest.mark.asyncio
async def test_reconstructed_client_falls_back_to_connector_scope(mcp_module):
    # The real proxy has no required_scopes, so _default_scope_str == "". The
    # reconstructed client must still carry a usable scope, or the connector's own
    # "openid email profile" request is rejected as invalid_scope (the prod bug
    # this guards against — a healed connector must be able to sign in).
    client = await _jit_probe(mcp_module, None, scope="").get_client("orphan")
    assert client.scope == "openid email profile"


@pytest.mark.asyncio
async def test_reconstructed_client_keeps_configured_default_scope(mcp_module):
    # When the proxy DOES advertise a default scope, reconstruction uses it verbatim.
    client = await _jit_probe(mcp_module, None, scope="openid custom:thing").get_client("x")
    assert client.scope == "openid custom:thing"


@pytest.mark.asyncio
async def test_known_client_is_passed_through_untouched(mcp_module):
    sentinel = object()
    result = await _jit_probe(mcp_module, sentinel).get_client("known-client")
    assert result is sentinel  # a HIT is never reconstructed


@pytest.mark.asyncio
async def test_no_allowlist_preserves_old_dead_end(mcp_module):
    # With no trusted allowlist there is nothing to bound a reconstruction against,
    # so the mixin returns None exactly as before. It never invents trust.
    probe = _jit_probe(mcp_module, None, allowlist=None)
    assert await probe.get_client("orphan") is None


def test_provider_subclasses_compose_the_jit_mixin(mcp_module):
    from fastmcp.server.auth.oauth_proxy import OAuthProxy

    assert issubclass(mcp_module._LoggingOAuthProxy, mcp_module._JitReregistrationMixin)
    assert issubclass(
        mcp_module._LoggingAWSCognitoProvider, mcp_module._JitReregistrationMixin
    )
    # Still the real provider, so downstream FastMCP/SDK behaviour is intact.
    assert issubclass(mcp_module._LoggingOAuthProxy, OAuthProxy)
