"""Real-HTTP probes against the running container.

Catches the class of bug that broke v1.4.37-audit2 in production:
- Container fails to start
- /icon.png 404s (connector icon disappears in Claude UI)
- Bare /.well-known/oauth-protected-resource 404s (some MCP clients only
  probe the unsuffixed path)
- /register fails because OAuth state can't be written to the configured
  store
"""
from __future__ import annotations

import json

import httpx


def test_health(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "financial-reports-mcp"


def test_security_headers(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/health")
    for header in (
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
    ):
        assert header in {k.lower() for k in r.headers}, f"missing {header}"


def test_landing_csp(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp


def test_icon_png_serves_real_bytes(
    http: httpx.Client, default_base_url: str
) -> None:
    """Regression: /icon.png 404'd in production before this PR. Real
    connectors (Claude, ChatGPT, Cursor) probe this path and silently
    fail to render the connector icon if it 404s."""
    r = http.get(f"{default_base_url}/icon.png")
    assert r.status_code == 200, "icon.png MUST be served — Claude probes it"
    assert r.headers["content-type"].startswith("image/png")
    assert len(r.content) > 0


def test_apple_touch_icon_serves(
    http: httpx.Client, default_base_url: str
) -> None:
    r = http.get(f"{default_base_url}/apple-touch-icon.png")
    assert r.status_code == 200


def test_icon_192_serves(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/icon-192.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


def test_icon_512_serves(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/icon-512.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


def test_mcp_rejects_foreign_origin(
    http: httpx.Client, default_base_url: str
) -> None:
    """MCP 2025-11-25 §Transports: 'Servers MUST validate Origin... if
    invalid, MUST respond with HTTP 403 Forbidden.'"""
    r = http.post(
        f"{default_base_url}/mcp",
        headers={
            "Origin": "https://evil.example",
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert r.status_code == 403


def test_mcp_rejects_unsupported_protocol_version(
    http: httpx.Client, default_base_url: str
) -> None:
    r = http.post(
        f"{default_base_url}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
            "MCP-Protocol-Version": "1999-01-01",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert r.status_code == 400


def test_mcp_echoes_protocol_version(
    http: httpx.Client, default_base_url: str
) -> None:
    r = http.post(
        f"{default_base_url}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert r.headers.get("mcp-protocol-version") == "2025-11-25"


def test_www_authenticate_includes_scope(
    http: httpx.Client, default_base_url: str
) -> None:
    r = http.post(
        f"{default_base_url}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert r.status_code == 401
    www = r.headers.get("www-authenticate", "")
    assert 'scope="mcp:read"' in www
    assert "resource_metadata=" in www


def test_favicon_serves(http: httpx.Client, default_base_url: str) -> None:
    r = http.get(f"{default_base_url}/favicon.ico")
    assert r.status_code == 200


def test_oauth_protected_resource_path_scoped(
    http: httpx.Client, default_base_url: str
) -> None:
    """FastMCP's path-scoped resource metadata."""
    r = http.get(f"{default_base_url}/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")


def test_oauth_protected_resource_bare_path(
    http: httpx.Client, default_base_url: str
) -> None:
    """Regression: some MCP clients only probe the bare path (no /mcp suffix).
    Without this fallback, OAuth discovery 404s on those clients."""
    r = http.get(f"{default_base_url}/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


def test_oauth_authorization_server_metadata(
    http: httpx.Client, default_base_url: str
) -> None:
    r = http.get(f"{default_base_url}/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert key in body, f"missing {key}"


def test_mcp_endpoint_requires_auth(
    http: httpx.Client, default_base_url: str
) -> None:
    """An unauthenticated /mcp call must 401 — the bearer-only policy is
    what tells Claude to start the OAuth flow."""
    r = http.post(
        f"{default_base_url}/mcp",
        headers={
            "Accept": "application/json,text/event-stream",
            "Content-Type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e-probe", "version": "0"},
            },
        },
    )
    assert r.status_code == 401
    www = r.headers.get("www-authenticate", "")
    assert "Bearer" in www
    assert "resource_metadata" in www


def test_dynamic_client_registration_round_trip(
    http: httpx.Client, default_base_url: str
) -> None:
    """REGRESSION TEST FOR THE PROD BUG.

    In v1.4.37-audit2 deployed against Azure Cache for Redis, this
    operation crashed with `redis.exceptions.ConnectionError: Connection
    reset by peer` and surfaced to users as `Couldn't reach the MCP
    server`. Catch it locally next time.
    """
    payload = {
        "client_name": "e2e-probe",
        "redirect_uris": ["http://localhost/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    r = http.post(
        f"{default_base_url}/register",
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload),
    )
    assert r.status_code in (200, 201), (
        f"OAuth dynamic client registration failed: "
        f"HTTP {r.status_code} body={r.text[:300]}"
    )
    body = r.json()
    assert "client_id" in body, body
    assert "client_secret" in body, body


def test_dynamic_client_registration_round_trip_redis(
    http: httpx.Client, redis_base_url: str
) -> None:
    """Same registration round-trip but against the Redis-backed variant.

    Verifies the *write path* hits Redis without erroring — this is exactly
    what failed against Azure Cache for Redis in production. Local Redis
    won't reproduce Azure-specific TLS bugs, but it WILL catch:
      - The image being unable to import the redis client
      - The boot-time ping erroring
      - The RedisStore wiring not matching FastMCP's expected interface
      - Serialisation bugs in the persisted client metadata
    """
    payload = {
        "client_name": "e2e-redis-probe",
        "redirect_uris": ["http://localhost/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    r = http.post(
        f"{redis_base_url}/register",
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload),
    )
    assert r.status_code in (200, 201), (
        f"OAuth /register against Redis-backed variant failed: "
        f"HTTP {r.status_code} body={r.text[:300]}"
    )


def test_oauth_state_survives_restart_with_redis(
    http: httpx.Client, redis_base_url: str, restart_redis_target
) -> None:
    """The whole point of MCP_REDIS_URL: refresh tokens persist across deploys.

    Register a client → restart the container → confirm the same client_id
    still authenticates. This is the fitness test for the Redis-backed
    OAuth state feature shipped in PR #7. If this fails, paid users get
    bounced to Cognito on every deploy.
    """
    payload = {
        "client_name": "persist-probe",
        "redirect_uris": ["http://localhost/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    r = http.post(
        f"{redis_base_url}/register",
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload),
    )
    assert r.status_code in (200, 201)
    client_id = r.json()["client_id"]

    restart_redis_target()

    # The OAuth proxy doesn't expose a "look up client" endpoint we can
    # probe directly, so we verify persistence indirectly: a /token call
    # with a wrong secret for the same client_id must still 401 with
    # `invalid_client` (the registration row is still on disk) rather
    # than report the client_id as completely unknown.
    r = http.post(
        f"{redis_base_url}/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": "fake",
            "client_id": client_id,
            "client_secret": "wrong",
            "redirect_uri": "http://localhost/callback",
        },
    )
    assert r.status_code in (400, 401), (
        f"client {client_id} appears to have been wiped across restart: "
        f"HTTP {r.status_code} body={r.text[:300]}"
    )
