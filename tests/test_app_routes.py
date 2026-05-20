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


def test_robots_txt_allows_crawl_and_points_at_sitemap(mcp_module) -> None:
    """Google needs to be able to crawl `/` so its favicon API picks up
    our brand mark. robots.txt must allow root, block JSON-RPC/OAuth
    paths (no human content there, just 401s), and advertise the
    sitemap so crawlers don't have to guess.
    """
    with TestClient(mcp_module.app) as client:
        resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /mcp" in body
    assert "Disallow: /authorize" in body
    assert "Disallow: /token" in body
    base = mcp_module.MCP_BASE_URL.rstrip("/")
    assert f"Sitemap: {base}/sitemap.xml" in body


def test_sitemap_xml_lists_landing_page(mcp_module) -> None:
    """Single-URL sitemap so Search Console has something to index."""
    with TestClient(mcp_module.app) as client:
        resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    base = mcp_module.MCP_BASE_URL.rstrip("/")
    assert "<urlset" in body
    assert f"<loc>{base}/</loc>" in body
    assert "<changefreq>weekly</changefreq>" in body


def test_landing_head_has_seo_and_og_tags(mcp_module) -> None:
    """REGRESSION: the favicon submitted to Anthropic resolves via
    Google's favicon API, which uses Google Search's index. For the
    MCP subdomain to be indexed, the landing page needs a real
    description, canonical URL, og:image, and absolute-URL favicon
    links — otherwise Google's signal strength is too weak to bother
    crawling and indexing the favicon.
    """
    with TestClient(mcp_module.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    base = mcp_module.MCP_BASE_URL.rstrip("/")

    assert '<meta name="description"' in html
    assert '<meta name="robots" content="index, follow">' in html
    assert f'<link rel="canonical" href="{base}/">' in html

    assert f'<link rel="icon" type="image/x-icon" href="{base}/favicon.ico">' in html
    assert f'href="{base}/icon-32.png"' in html
    assert f'href="{base}/icon-192.png"' in html
    assert f'<link rel="apple-touch-icon" sizes="180x180" href="{base}/apple-touch-icon.png">' in html

    assert '<meta property="og:type" content="website">' in html
    assert f'<meta property="og:image" content="{base}/icon-512.png">' in html
    assert f'<meta property="og:url" content="{base}/">' in html
    assert '<meta name="twitter:card" content="summary">' in html

    assert "__MCP_BASE_URL__" not in html, (
        "Placeholder leaked into rendered HTML — substitution missed a token"
    )


def test_landing_omits_gsv_tag_when_env_unset(mcp_module) -> None:
    """Default test env has no GOOGLE_SITE_VERIFICATION — landing must NOT
    emit the tag (would force-leak an empty content="" attribute, which
    Search Console rejects as invalid)."""
    with TestClient(mcp_module.app) as client:
        resp = client.get("/")
    assert "google-site-verification" not in resp.text


def test_landing_emits_gsv_tag_when_env_set(monkeypatch, respx_router) -> None:
    """When GOOGLE_SITE_VERIFICATION is set, the landing page renders the
    tag with the configured token. Module is reloaded inside the test so
    the rendered template picks up the new env value. We depend on
    respx_router so the OIDC discovery call (triggered by module reload)
    stays mocked instead of hitting the real Cognito endpoint.
    """
    import importlib

    import src.financial_reports_mcp as m  # type: ignore

    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "TestToken_AbCdEf123456")
    importlib.reload(m)
    with TestClient(m.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert (
        '<meta name="google-site-verification" content="TestToken_AbCdEf123456">'
        in resp.text
    )
    # monkeypatch undoes the env override on test teardown; subsequent tests
    # using the mcp_module fixture get a fresh reload with the cleared env.


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


def test_apple_touch_icon_proxies_dedicated_cdn_asset(
    mcp_module, respx_router
) -> None:
    """Apple-touch-icon is served from the dedicated CDN asset (180×180 PNG),
    distinct from /icon.png (which serves the 32×32 favicon-derived PNG)."""
    respx_router.get(mcp_module.APPLE_TOUCH_URL).mock(
        return_value=httpx.Response(
            200, content=b"\x89APPLE_PNG", headers={"content-type": "image/png"}
        )
    )
    with TestClient(mcp_module.app) as client:
        resp = client.get("/apple-touch-icon.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89APPLE_PNG"
    assert resp.headers["content-type"].startswith("image/png")


def test_icon_png_192_serves(mcp_module, respx_router) -> None:
    respx_router.get(mcp_module.ICON_URL_192).mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG_192", headers={"content-type": "image/png"}
        )
    )
    with TestClient(mcp_module.app) as client:
        resp = client.get("/icon-192.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG_192"


def test_icon_png_512_serves(mcp_module, respx_router) -> None:
    respx_router.get(mcp_module.ICON_URL_512).mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG_512", headers={"content-type": "image/png"}
        )
    )
    with TestClient(mcp_module.app) as client:
        resp = client.get("/icon-512.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG_512"


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


# ---------------------------------------------------------------------------
# MCP 2025-11-25 spec MUSTs added in this PR
# ---------------------------------------------------------------------------


def test_mcp_rejects_foreign_origin_with_403(mcp_module) -> None:
    """Spec: 'Servers MUST validate the Origin header on all incoming
    connections to prevent DNS rebinding attacks. If the Origin header is
    present and invalid, servers MUST respond with HTTP 403 Forbidden.'"""
    with TestClient(mcp_module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "Origin": "https://evil.example",
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden_origin"


def test_mcp_accepts_claude_origin(mcp_module) -> None:
    """Trusted MCP-host origins must be allowed through to the auth check."""
    with TestClient(mcp_module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "Origin": "https://claude.ai",
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    # We expect 401 (no bearer) — the point is we got *past* the Origin
    # gate and into the auth check.
    assert resp.status_code == 401, "Origin allowlist must let claude.ai through"


def test_mcp_origin_check_skips_static_routes(mcp_module) -> None:
    """The Origin check is scoped to /mcp; /health from a foreign origin
    must still 200 (it serves no protected data)."""
    with TestClient(mcp_module.app) as client:
        resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200


def test_mcp_rejects_unsupported_protocol_version_with_400(mcp_module) -> None:
    """Spec: 'If the server receives a request with an invalid or unsupported
    MCP-Protocol-Version, it MUST respond with 400 Bad Request.'"""
    with TestClient(mcp_module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
                "MCP-Protocol-Version": "1999-01-01",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "unsupported_protocol_version"
    assert "supported_versions" in body
    assert mcp_module.DEFAULT_MCP_PROTOCOL_VERSION in body["supported_versions"]


def test_mcp_echoes_protocol_version_header(mcp_module) -> None:
    """Server should echo MCP-Protocol-Version on /mcp responses so clients
    can detect downgrades."""
    with TestClient(mcp_module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    # Header must be present regardless of auth outcome.
    assert resp.headers.get("mcp-protocol-version") == "2025-11-25"


def test_www_authenticate_includes_scope_param(mcp_module) -> None:
    """Spec SHOULD: 'MCP servers SHOULD include a `scope` parameter in the
    WWW-Authenticate header.' Advertised scopes MUST match what the AS
    accepts on /register — Claude reads this hint and uses it as the
    `scope` value on dynamic client registration.

    Originally set to "mcp:read"; that broke production because Cognito
    has no such scope and DCR rejected every Claude attempt with
    `invalid_client_metadata`. The user-visible symptom was "Couldn't
    reach the MCP server". The fix is to advertise the same scopes
    `scopes_supported` lists (openid email profile)."""
    with TestClient(mcp_module.app) as client:
        resp = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    assert resp.status_code == 401
    www = resp.headers["www-authenticate"]
    assert 'scope="openid email profile"' in www
    # Existing fields must still be there — we augment, not replace.
    assert "resource_metadata=" in www
    assert 'error="invalid_token"' in www


def test_www_authenticate_scope_is_actually_registerable(mcp_module) -> None:
    """REGRESSION: prevent advertising a scope on /mcp 401 that /register
    will reject. Earlier we shipped `scope="mcp:read"` which Cognito
    didn't recognize; Claude faithfully echoed it on DCR and every
    registration 400'd. This test ties the WWW-Authenticate hint to the
    scopes_supported list in /.well-known/oauth-authorization-server."""
    with TestClient(mcp_module.app) as client:
        # Pull the WWW-Authenticate scope value from a 401.
        r = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json,text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
    www = r.headers["www-authenticate"]
    import re as _re

    m = _re.search(r'scope="([^"]+)"', www)
    assert m, f"no scope= in WWW-Authenticate: {www!r}"
    advertised = set(m.group(1).split())

    # All advertised scopes MUST be a subset of the AS's scopes_supported,
    # because Claude will replay them on /register and the MCP shared
    # register handler rejects anything not in the AS's allowlist.
    assert advertised.issubset({"openid", "email", "profile"}), (
        f"WWW-Authenticate advertises {advertised!r} which Cognito doesn't "
        f"register; DCR will reject it. Either expand Cognito's scopes or "
        f"narrow the WWW-Authenticate hint."
    )


def test_initialize_advertises_multi_size_icons(mcp_module) -> None:
    """Server icons must be a multi-size array so connector renderers can
    pick the right resolution. Spec: `icons: [{src, mimeType, sizes}]`."""
    icons = mcp_module.mcp._mcp_server.icons
    assert icons is not None and len(icons) >= 3
    sizes_advertised = {tuple(icon.sizes) for icon in icons}
    assert ("32x32",) in sizes_advertised
    assert ("192x192",) in sizes_advertised
    assert ("512x512",) in sizes_advertised


def test_advertised_icons_are_same_origin(mcp_module) -> None:
    """REGRESSION: previously we advertised CDN URLs in MCP `Icon` metadata.
    FastMCP's auto-generated /consent OAuth page renders that URL as the
    page logo and our own CSP (img-src 'self' data:) blocks any
    cross-origin image — so the consent page lost its branding. Some host
    UIs also prefer same-origin connector icons.

    The /icon-*.png server-relative routes proxy + cache the same CDN
    bytes, so there's no asset cost in pointing at our own origin.
    """
    icons = mcp_module.mcp._mcp_server.icons or []
    base = mcp_module.MCP_BASE_URL.rstrip("/")
    for icon in icons:
        src = str(icon.src)
        assert src.startswith(base), (
            f"icon {src!r} is cross-origin; advertise from {base}/icon-*.png "
            f"so the FastMCP consent page can render it under our own CSP "
            f"(img-src 'self' data:)"
        )


def test_serverinfo_exposes_website_url(mcp_module) -> None:
    """Reviewers see this in connector listings (`Implementation.websiteUrl`)."""
    assert mcp_module.mcp._mcp_server.website_url == mcp_module.WEBSITE_URL


def test_markdown_clamp_is_150k(mcp_module) -> None:
    """Claude.ai's documented tool-result ceiling is ~150k chars. Generator
    template now clamps to that — looser caps risk silent truncation."""
    src = (
        mcp_module.__file__
    )
    with open(src) as f:
        body = f.read()
    assert "min(int(limit), 150000)" in body
    assert "min(int(limit), 200000)" not in body
