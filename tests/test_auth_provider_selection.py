"""auth_provider selection — the flag-gated WAF-fix OAuth-proxy repoint.

Three construction paths the deploy depends on:

  1. nothing set (current prod)        -> AWSCognitoProvider  (zero regression)
  2. MCP_UPSTREAM_AUTH_BASE + creds    -> OAuthProxy with SPLIT upstream endpoints
                                          (authorize on the browser host, token on
                                           the WAF-free api.* gateway)
  3. MCP_UPSTREAM_AUTH_BASE, no creds  -> RuntimeError at import (fail loud)

The provider is constructed at module import, so each path is exercised by
reloading the generated module under a different environment. ``respx_router``
mocks Cognito OIDC + JWKS so AWSCognitoProvider / AWSCognitoTokenVerifier
construction stays offline.
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.aws import AWSCognitoProvider

# Innocuous placeholder for the dummy connector secret. Passed as a *variable*
# (not a string literal at the call site) so the test stays free of fake-secret
# literals; the name is deliberately non-secret-y.
_FAKE_VALUE = "unit-test-value"

_OAUTH_ENV_KEYS = (
    "MCP_UPSTREAM_AUTH_BASE",
    "MCP_UPSTREAM_TOKEN_BASE",
    "MCP_OAUTH_CLIENT_ID",
    "MCP_OAUTH_CLIENT_SECRET",
    "MCP_OAUTH_REDIRECT_PATH",
)
# Cleared before EVERY reload so an ambient DEV_MODE_API_KEY (which short-circuits
# the auth branch to None) or a partial MCP_UPSTREAM_* in the runner env can't
# flip the branch under us — each reload sees exactly the env the test passes.
_CLEARED_KEYS = _OAUTH_ENV_KEYS + ("DEV_MODE_API_KEY",)
# Also save/restore COGNITO_CLIENT_SECRET so a test can unset it (to prove the
# OAuth path doesn't require it) without leaking that into sibling tests.
_RESTORE_KEYS = _CLEARED_KEYS + ("COGNITO_CLIENT_SECRET",)


@pytest.fixture()
def reload_with_oauth_env(respx_router):
    """Return a callable that reloads the generated module under the given OAuth
    env, then restores the baseline env + module state on teardown.

    Pass an env var as ``None`` to UNSET it for that reload. respx is active for
    the whole fixture lifetime (this fixture depends on ``respx_router``),
    including the teardown reload, so the baseline AWSCognitoProvider's OIDC
    discovery call is mocked there too.
    """
    import src.financial_reports_mcp as mod

    saved = {k: os.environ.get(k) for k in _RESTORE_KEYS}

    def _reload(**env):
        for k in _CLEARED_KEYS:
            os.environ.pop(k, None)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(mod)
        return mod

    yield _reload

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(mod)


def test_default_path_uses_aws_cognito_provider(mcp_module) -> None:
    # No MCP_UPSTREAM_AUTH_BASE, no DEV_MODE — the current prod path. The
    # OAuth-proxy repoint must be invisible until the flag is set.
    assert isinstance(mcp_module.auth_provider, AWSCognitoProvider)
    assert mcp_module.MCP_UPSTREAM_AUTH_BASE == ""


def test_upstream_base_uses_oauth_proxy_with_split_endpoints(
    reload_with_oauth_env,
) -> None:
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu",
        MCP_OAUTH_CLIENT_ID="fr-mcp-connector",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )

    assert isinstance(mod.auth_provider, OAuthProxy)
    # The split is the whole point: authorize stays on the WAF-fronted browser
    # host, the server-to-server token exchange goes to the WAF-free api host.
    assert (
        mod.auth_provider._upstream_authorization_endpoint
        == "https://financialfilings.com/oauth/authorize"
    )
    assert (
        mod.auth_provider._upstream_token_endpoint
        == "https://api.financialreports.eu/oauth/token"
    )


def test_token_base_defaults_to_auth_base_when_unset(reload_with_oauth_env) -> None:
    # Single-host deploys: omit TOKEN_BASE and token rides AUTH_BASE.
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://example.test",
        MCP_OAUTH_CLIENT_ID="cid",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )

    assert mod.MCP_UPSTREAM_TOKEN_BASE == "https://example.test"
    assert (
        mod.auth_provider._upstream_token_endpoint == "https://example.test/oauth/token"
    )


def test_trailing_slash_on_bases_is_normalised(reload_with_oauth_env) -> None:
    # rstrip("/") must prevent a double slash in the constructed endpoints.
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com/",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu/",
        MCP_OAUTH_CLIENT_ID="cid",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )

    assert (
        mod.auth_provider._upstream_authorization_endpoint
        == "https://financialfilings.com/oauth/authorize"
    )
    assert (
        mod.auth_provider._upstream_token_endpoint
        == "https://api.financialreports.eu/oauth/token"
    )


def test_upstream_base_without_creds_raises(reload_with_oauth_env) -> None:
    # Fail loud — a half-configured deploy must NOT silently fall back to Cognito.
    with pytest.raises(RuntimeError, match=r"MCP_OAUTH_CLIENT_ID"):
        reload_with_oauth_env(MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com")


def test_partial_creds_only_id_raises(reload_with_oauth_env) -> None:
    with pytest.raises(
        RuntimeError, match=r"MCP_OAUTH_CLIENT_SECRET|MCP_OAUTH_CLIENT_ID"
    ):
        reload_with_oauth_env(
            MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
            MCP_OAUTH_CLIENT_ID="cid-only",
        )


def test_oauth_path_does_not_require_cognito_client_secret(
    reload_with_oauth_env,
) -> None:
    # The OAuth-proxy path uses MCP_OAUTH_CLIENT_SECRET, not the Cognito secret.
    # With COGNITO_CLIENT_SECRET unset it must still boot (no SystemExit from the
    # _REQUIRED_ENV guard) — matches the "never the Cognito app-client secret"
    # design and avoids forcing operators to provision an unused secret.
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu",
        MCP_OAUTH_CLIENT_ID="fr-mcp-connector",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
        COGNITO_CLIENT_SECRET=None,
    )
    assert isinstance(mod.auth_provider, OAuthProxy)


def test_default_path_still_requires_cognito_client_secret(
    reload_with_oauth_env,
) -> None:
    # The Cognito path genuinely needs the secret — unsetting it (no OAuth env)
    # must fail loud at import via the _REQUIRED_ENV guard.
    with pytest.raises(SystemExit, match=r"COGNITO_CLIENT_SECRET"):
        reload_with_oauth_env(COGNITO_CLIENT_SECRET=None)


def test_plaintext_http_upstream_to_remote_host_raises(reload_with_oauth_env) -> None:
    # A typo'd http:// to a real host would leak client_secret + auth code over
    # plaintext — refuse to boot.
    with pytest.raises(RuntimeError, match=r"https"):
        reload_with_oauth_env(
            MCP_UPSTREAM_AUTH_BASE="http://financialfilings.com",
            MCP_OAUTH_CLIENT_ID="cid",
            MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
        )


def test_plaintext_http_token_base_to_remote_host_raises(reload_with_oauth_env) -> None:
    # The guard covers the token base independently of the (https) authorize base.
    with pytest.raises(RuntimeError, match=r"https"):
        reload_with_oauth_env(
            MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
            MCP_UPSTREAM_TOKEN_BASE="http://api.financialreports.eu",
            MCP_OAUTH_CLIENT_ID="cid",
            MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
        )


def test_http_upstream_to_localhost_is_allowed(reload_with_oauth_env) -> None:
    # Local-dev / lab-tunnel flow: http:// to a local host is permitted.
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="http://localhost:8080",
        MCP_OAUTH_CLIENT_ID="cid",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    assert isinstance(mod.auth_provider, OAuthProxy)
    assert (
        mod.auth_provider._upstream_authorization_endpoint
        == "http://localhost:8080/oauth/authorize"
    )
