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


def test_dcr_without_scope_gets_the_connector_scope_set(reload_with_oauth_env) -> None:
    """A client that omits `scope` at registration must still be able to authorize.

    RFC 7591 §2 makes `scope` optional. Cursor, Perplexity, Google Antigravity,
    Lovable and LiteLLM bridges all omit it. Before the `default_scopes` wiring the
    proxy stored scope="" for them and every /authorize died with
    `invalid_scope: Client was not registered with scope openid` — forever, because
    JIT re-registration only heals a MISSING record, not an empty one.
    """
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu",
        MCP_OAUTH_CLIENT_ID="fr-mcp-connector",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    opts = mod.auth_provider.client_registration_options

    # The registration default must be non-empty and must match what the server
    # advertises. `required_scopes` staying empty is load-bearing, not an oversight:
    # Cognito access tokens carry aws.cognito.signin.user.admin, so requiring
    # openid/email/profile at validation time would 403 every tool call.
    assert opts.default_scopes == ["openid", "email", "profile"]
    assert opts.valid_scopes == ["openid", "email", "profile"]
    assert mod.auth_provider.required_scopes == []


async def test_cursor_shaped_dcr_survives_the_authorize_scope_check(
    reload_with_oauth_env,
) -> None:
    """Drive the REAL SDK registration handler with a real Cursor DCR body.

    Deliberately does not re-implement the default_scopes lookup: the handler is
    invoked as an HTTP endpoint, and the assertion is made against the record the
    proxy actually stored plus the exact `validate_scope` call that raised
    InvalidScopeError in production.
    """
    import json

    from mcp.server.auth.handlers.register import RegistrationHandler
    from starlette.requests import Request

    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu",
        MCP_OAUTH_CLIENT_ID="fr-mcp-connector",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    handler = RegistrationHandler(
        provider=mod.auth_provider,
        options=mod.auth_provider.client_registration_options,
    )

    # Copied from a real stranded registration in prod: note the absent `scope`.
    body = json.dumps(
        {
            "client_name": "Cursor",
            "redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
    ).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/register",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        receive,
    )
    response = await handler.handle(request)
    assert response.status_code == 201, response.body

    registered = json.loads(response.body)
    assert registered["scope"] == "openid email profile"

    # And the record the proxy persisted — the one /authorize reads — must pass the
    # check that produced `invalid_scope: Client was not registered with scope openid`.
    stored = await mod.auth_provider.get_client(registered["client_id"])
    assert stored is not None
    assert stored.validate_scope("openid email profile") == [
        "openid",
        "email",
        "profile",
    ]


def test_advertised_scopes_match_the_registration_default(reload_with_oauth_env) -> None:
    """The outage was a DIVERGENCE: we advertised three scopes and registered zero.

    Pin the invariant rather than the values, so a future edit to one surface that
    misses another fails here instead of in production.
    """
    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_OAUTH_CLIENT_ID="cid",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    advertised = mod._OAUTH_SCOPES
    assert mod.auth_provider.client_registration_options.default_scopes == advertised
    assert mod.auth_provider.client_registration_options.valid_scopes == advertised
    assert mod._OAUTH_SCOPE_STR == " ".join(advertised)


# Blank `scope` at DCR must behave exactly like an absent one. The SDK's
# `default_scopes` hook only fires on `scope is None`, so an explicit "" or a
# whitespace-only value slipped past it and stranded the client forever. These
# drive the REAL mounted /register route (not a hand-built handler), so a future
# FastMCP change that copies the registration options at route-build time — which
# would silently turn the fix into a no-op — fails here.
@pytest.mark.parametrize(
    "scope_field",
    [
        pytest.param({}, id="absent"),
        pytest.param({"scope": None}, id="null"),
        pytest.param({"scope": ""}, id="empty-string"),
        pytest.param({"scope": "   "}, id="whitespace-only"),
    ],
)
def test_blank_scope_at_registration_is_treated_as_absent(
    reload_with_oauth_env, scope_field
) -> None:
    from starlette.testclient import TestClient

    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_UPSTREAM_TOKEN_BASE="https://api.financialreports.eu",
        MCP_OAUTH_CLIENT_ID="fr-mcp-connector",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    body = {
        "client_name": "blank-scope-probe",
        "redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        **scope_field,
    }
    with TestClient(mod.app) as client:
        resp = client.post("/register", json=body)
    assert resp.status_code == 201, resp.text
    client_id = resp.json()["client_id"]

    # The PERSISTED record is what /authorize validates against, and it is the
    # only thing that matters — assert on it, not on the response echo.
    import anyio

    stored = anyio.run(mod.auth_provider.get_client, client_id)
    assert stored is not None
    assert (stored.scope or "").strip(), (
        f"stored scope is blank ({stored.scope!r}) — this client is stranded: "
        "every /authorize will raise invalid_scope forever"
    )
    assert stored.validate_scope("openid email profile") == [
        "openid",
        "email",
        "profile",
    ]


def test_explicit_valid_scope_at_registration_is_preserved(reload_with_oauth_env) -> None:
    """The normalisation must not clobber a client that asked for a real subset."""
    from starlette.testclient import TestClient

    mod = reload_with_oauth_env(
        MCP_UPSTREAM_AUTH_BASE="https://financialfilings.com",
        MCP_OAUTH_CLIENT_ID="cid",
        MCP_OAUTH_CLIENT_SECRET=_FAKE_VALUE,
    )
    with TestClient(mod.app) as client:
        resp = client.post(
            "/register",
            json={
                "client_name": "explicit-scope-probe",
                "redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "openid",
            },
        )
    assert resp.status_code == 201, resp.text
    import anyio

    stored = anyio.run(mod.auth_provider.get_client, resp.json()["client_id"])
    assert stored.scope == "openid"
