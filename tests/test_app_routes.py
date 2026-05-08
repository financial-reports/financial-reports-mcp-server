"""HTTP-level smoke tests for the FastAPI host routes added in this PR."""
from __future__ import annotations

import httpx
from starlette.testclient import TestClient


def test_health_returns_version(mcp_module) -> None:
    with TestClient(mcp_module.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "financial-reports-mcp"
    assert body["version"] == "test"


def test_security_headers_applied(mcp_module) -> None:
    with TestClient(mcp_module.app) as client:
        resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "permissions-policy" in resp.headers
    # JSON responses don't carry CSP — only HTML does.
    assert "content-security-policy" not in resp.headers


def test_landing_html_carries_csp(mcp_module) -> None:
    with TestClient(mcp_module.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "default-src 'none'" in resp.headers["content-security-policy"]


def test_well_known_oauth_protected_resource_root(mcp_module) -> None:
    """Bare path mirrors the path-scoped doc for clients that probe / instead of /mcp."""
    with TestClient(mcp_module.app) as client:
        resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource"].endswith("/mcp")
    assert "openid" in body["scopes_supported"]


def test_icon_png_proxies_cdn_and_caches(mcp_module, respx_router) -> None:
    """/icon.png pulls bytes from the CDN once, then serves from cache."""
    route = respx_router.get(mcp_module.ICON_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"\x89PNG_FAKE_BYTES",
            headers={"content-type": "image/png"},
        )
    )

    with TestClient(mcp_module.app) as client:
        r1 = client.get("/icon.png")
        r2 = client.get("/icon.png")

    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("image/png")
    assert r1.headers.get("cache-control") == "public, max-age=86400"
    assert r1.content == b"\x89PNG_FAKE_BYTES"
    assert r2.content == r1.content
    assert route.call_count == 1, (
        "asset cache should serve the second request without an "
        "outbound CDN fetch"
    )


def test_apple_touch_icon_aliases_icon_png(mcp_module, respx_router) -> None:
    respx_router.get(mcp_module.ICON_URL).mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG_FAKE", headers={"content-type": "image/png"}
        )
    )
    with TestClient(mcp_module.app) as client:
        resp = client.get("/apple-touch-icon.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG_FAKE"


def test_favicon_serves_stale_on_cdn_failure(mcp_module, respx_router) -> None:
    """When the CDN errors, /favicon.ico must still serve cached bytes.

    FastMCP's StreamableHTTPSessionManager forbids re-running the lifespan
    on the same instance, so we keep a single TestClient open and swap the
    respx route between calls instead of recycling the client.
    """
    fav_route = respx_router.get(mcp_module.FAVICON_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"FAVICONOK",
            headers={"content-type": "image/x-icon"},
        )
    )

    with TestClient(mcp_module.app) as client:
        ok = client.get("/favicon.ico")
        assert ok.status_code == 200
        assert ok.content == b"FAVICONOK"

        # Make the CDN unavailable; cached bytes must still serve.
        fav_route.mock(side_effect=httpx.ConnectError("cdn down"))
        stale = client.get("/favicon.ico")
        assert stale.status_code == 200
        assert stale.content == b"FAVICONOK"


def test_cors_allow_headers_tightened(mcp_module) -> None:
    """A pre-flight requesting an exotic header must NOT be reflected back."""
    with TestClient(mcp_module.app) as client:
        resp = client.options(
            "/health",
            headers={
                "origin": "https://anywhere.example",
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-evil-header",
            },
        )
    allowed = resp.headers.get("access-control-allow-headers", "")
    assert "x-evil-header" not in allowed.lower()
