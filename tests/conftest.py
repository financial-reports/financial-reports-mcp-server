"""Shared fixtures.

The generated module imports `AWSCognitoProvider`, which performs a synchronous
OIDC-discovery HTTP call inside its constructor at module load time. We intercept
that single request via respx so tests don't need network access — and don't
depend on the live AWS Cognito endpoint being reachable from the test runner.

respx contexts do NOT stack, so tests share one router (with OIDC pre-registered)
exposed via the `respx_router` fixture.
"""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Synthetic Cognito values — never used to sign or validate real tokens.
TEST_POOL_ID = "eu-central-1_TESTPOOL1"
TEST_CLIENT_ID = "test_client_id"
TEST_CLIENT_SECRET = "test_client_secret"
TEST_REGION = "eu-central-1"
TEST_ISSUER = f"https://cognito-idp.{TEST_REGION}.amazonaws.com/{TEST_POOL_ID}"
TEST_BASE_URL = "https://mcp.test.invalid"
TEST_API_BASE = "https://api.test.invalid"
TEST_VERIFY_URL = f"{TEST_API_BASE}/api/mcp/verify/"


_OIDC_DOCUMENT = {
    "issuer": TEST_ISSUER,
    "authorization_endpoint": f"{TEST_ISSUER}/oauth2/authorize",
    "token_endpoint": f"{TEST_ISSUER}/oauth2/token",
    "userinfo_endpoint": f"{TEST_ISSUER}/oauth2/userInfo",
    "jwks_uri": f"{TEST_ISSUER}/.well-known/jwks.json",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
    "scopes_supported": ["openid", "email", "profile"],
    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
}


@pytest.fixture(scope="session", autouse=True)
def _env() -> Iterator[None]:
    """Make module-import side effects deterministic."""
    overrides = {
        "COGNITO_USER_POOL_ID": TEST_POOL_ID,
        "COGNITO_CLIENT_ID": TEST_CLIENT_ID,
        "COGNITO_CLIENT_SECRET": TEST_CLIENT_SECRET,
        "COGNITO_REGION": TEST_REGION,
        "MCP_BASE_URL": TEST_BASE_URL,
        "API_BASE_URL": TEST_API_BASE,
        "VERIFY_URL": TEST_VERIFY_URL,
        "MCP_VERSION": "test",
    }
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    os.environ.pop("MCP_REDIS_URL", None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _register_oidc_routes(router: respx.MockRouter) -> None:
    router.get(f"{TEST_ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=_OIDC_DOCUMENT)
    )
    router.get(f"{TEST_ISSUER}/.well-known/jwks.json").mock(
        return_value=httpx.Response(200, json={"keys": []})
    )


@pytest.fixture()
def respx_router() -> Iterator[respx.MockRouter]:
    """One respx context per test, with OIDC + JWKS already mocked.

    `assert_all_called=False` so tests don't have to use every pre-registered
    route. `assert_all_mocked=False` so a request to an unmocked URL doesn't
    fail the test — it just passes through (and would fail at the network
    level, which is loud enough).
    """
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        _register_oidc_routes(router)
        yield router


@pytest.fixture()
def mcp_module(respx_router: respx.MockRouter):
    """Lazy import of the generated module so the respx context is active first.

    Reloads the module per test so the subscription cache and asset cache
    are reset between tests without leaking state.
    """
    import src.financial_reports_mcp as m  # type: ignore

    importlib.reload(m)
    return m


@pytest.fixture()
def fake_access_token(mcp_module):
    """Stub for FastMCP's access-token object (`get_access_token()` return)."""

    class _AT:
        def __init__(
            self,
            sub: str = "test-sub-12345678",
            client_id: str | None = TEST_CLIENT_ID,
            token: str = "real-access-token",
        ) -> None:
            self.token = token
            self.client_id = client_id
            self.claims = {"sub": sub, "client_id": client_id}

    return _AT


__all__ = [
    "TEST_API_BASE",
    "TEST_BASE_URL",
    "TEST_CLIENT_ID",
    "TEST_ISSUER",
    "TEST_POOL_ID",
    "TEST_VERIFY_URL",
    "fake_access_token",
    "mcp_module",
    "respx_router",
]
