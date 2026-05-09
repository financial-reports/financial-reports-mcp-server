# Self-hosting the FinancialReports MCP Server

This guide is for engineers who want to run their own instance of this server — typically to fork and adapt it to a different upstream API, run a development copy, or operate a private deployment.

For most use cases the **hosted server at `https://mcp.financialfilings.com/mcp`** is the supported path. If you're an end user wanting to use FinancialReports through Claude, you don't need this document.

---

## Prerequisites

- Docker (recommended) or Python 3.11+
- An **AWS Cognito user pool** with an app client configured
- Access to the FinancialReports API (or a fork-modified upstream)
- A public URL where this server will be reachable (must be added as an allowed redirect URI on your Cognito app client)
- Optional: a Redis instance (Azure Cache, Upstash, AWS ElastiCache) for OAuth-state persistence across restarts

---

## Configuration

Copy `.env.example` to `.env` and populate:

| Variable | Required | Description |
|---|---|---|
| `COGNITO_USER_POOL_ID` | ✅ | e.g. `eu-central-1_AbCdEfGhI` |
| `COGNITO_CLIENT_ID` | ✅ | App client ID issued by Cognito |
| `COGNITO_CLIENT_SECRET` | ✅ | App client secret |
| `COGNITO_REGION` | optional | AWS region (default `eu-central-1`) |
| `MCP_BASE_URL` | ✅ | Public URL of this server (`https://mcp.example.com`); must match a Cognito redirect URI |
| `API_BASE_URL` | ✅ | Upstream API base (default `https://api.financialreports.eu`) |
| `VERIFY_URL` | ✅ | Subscription-tier verification endpoint (default `<API_BASE_URL>/api/mcp/verify/`) |
| `MCP_VERSION` | optional | Version label exposed at `/health` |
| `MCP_REDIS_URL` | optional | `rediss://:<token>@host:6380/0` for persistent OAuth state. Without it, FastMCP's per-replica DiskStore is used (refresh tokens are lost on deploy/restart) |
| `GOOGLE_SITE_VERIFICATION` | optional | If set, the landing page emits `<meta name="google-site-verification" content="...">` for Search Console verification |

The full list with sensible defaults lives in [`.env.example`](../.env.example).

---

## Run with Docker

```bash
docker build -t financial-reports-mcp .
docker run --rm \
  -p 8000:8000 \
  --env-file .env \
  -e MCP_VERSION=local \
  financial-reports-mcp
```

The server listens on `:8000`. Verify:

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"financial-reports-mcp","version":"local"}
```

MCP transport (Streamable HTTP): `POST http://localhost:8000/mcp`.

---

## Run with Python (development)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

cp .env.example .env  # edit with your Cognito values
python scripts/generate_mcp_tools.py    # bake src/financial_reports_mcp.py
python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000
```

Hot reload during development:

```bash
uvicorn src.financial_reports_mcp:app --reload --reload-dir src
```

Note that `--reload` does NOT pick up changes in the OpenAPI schema or generator script — re-run `python scripts/generate_mcp_tools.py` to regenerate the tool surface.

---

## Cognito setup notes

The Cognito app client must:

1. Have your `MCP_BASE_URL` (and `MCP_BASE_URL/auth/callback`, depending on how your client probes) added to **Allowed callback URLs**.
2. Permit the **Authorization Code grant** with PKCE.
3. Allow the OAuth scopes used: `openid email profile` (and any custom scopes your fork requires).
4. If you want Dynamic Client Registration to work, the FastMCP OAuth proxy generates per-installation client IDs — the upstream Cognito client is used to mint child credentials, so the upstream client should support DCR's expected token-exchange flow.

If users hit `invalid_target` or `invalid_client` during OAuth, the most common cause is a `MCP_BASE_URL` value that doesn't exactly match the Cognito-allowed redirect URI (trailing slash, http vs https, www vs apex).

---

## Persistence (Redis)

Without `MCP_REDIS_URL`, FastMCP falls back to a per-replica DiskStore. Refresh tokens written there are not visible to other replicas and are lost on container restart, which means:

- After a deploy, all currently-signed-in users are silently logged out.
- In a multi-replica setup, OAuth flows started on replica A may fail if the redirect lands on replica B.

For production, set `MCP_REDIS_URL` to a TLS Redis (`rediss://`). The server logs `"Using Redis store for OAuth state"` on boot when persistence is active and `"using FastMCP default DiskStore"` when not.

---

## CDN and icons

The server serves the connector icons (`/favicon.ico`, `/icon.png`, `/icon-32.png`, `/icon-192.png`, `/icon-512.png`, `/apple-touch-icon.png`) by proxying them from the CDN constants defined at the top of `scripts/generate_mcp_tools.py`. To rebrand for a fork:

1. Edit `_CDN_BASE` and the `*_URL` constants in `scripts/generate_mcp_tools.py`.
2. Re-run the generator: `python scripts/generate_mcp_tools.py`.
3. Rebuild the Docker image.

The advertised `Icon` URLs in the MCP `initialize` response always point at this server's own origin (`MCP_BASE_URL/icon-*.png`), not the CDN directly. This is intentional — connector UIs (and FastMCP's auto-generated `/consent` page) load icons same-origin so they pass the server's CSP without needing to whitelist the CDN.

---

## Health, monitoring, observability

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness probe — returns `{status, service, version}` |
| `GET /robots.txt` | Crawl directives + sitemap pointer |
| `GET /sitemap.xml` | Single-URL sitemap (the landing page only) |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 metadata (bare path) |
| `GET /.well-known/oauth-protected-resource/mcp` | RFC 9728 metadata (path-scoped) |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 metadata |

There's no built-in metrics endpoint. For production, wrap the FastAPI app with the Prometheus middleware of your choice or hook Azure Container Apps' built-in scaling metrics.

---

## Production checklist (if you actually deploy this)

- [ ] `MCP_REDIS_URL` set (TLS, persistent storage)
- [ ] `MCP_BASE_URL` matches Cognito callback URL exactly
- [ ] HTTPS-only at the edge (HTTP → HTTPS redirect)
- [ ] CSP headers preserved (don't strip via reverse proxy)
- [ ] Health check wired to your orchestrator's readiness probe
- [ ] Logs shipped somewhere durable (the server uses `logging`, not stdout-only)
- [ ] Cognito app client secret rotated regularly
- [ ] Container image pinned to a specific tag, not `:latest`
- [ ] Test account credentials kept off Git history

---

## Troubleshooting

**`OIDC discovery failed` on startup**: Cognito user pool ID or region is wrong. The server makes an HTTP call to `https://cognito-idp.<region>.amazonaws.com/<pool_id>/.well-known/openid-configuration` at module load — if that 404s, the values are misconfigured.

**`invalid_target` during OAuth**: The MCP client (Claude.ai, Cursor, etc.) is sending an RFC 8707 `resource` parameter that doesn't match `MCP_BASE_URL/mcp`. Verify the connector dialog uses the exact same URL as `MCP_BASE_URL`.

**`401 invalid_token` on tool calls after a deploy**: refresh tokens were lost. Set `MCP_REDIS_URL` for persistence, or accept the re-auth UX cost. Users can recover by clicking "Reconnect" in their MCP client.

**`403 origin not allowed`**: the request's `Origin` header isn't on the allow-list. Edit the origin-validation logic in `scripts/generate_mcp_tools.py` and regenerate.

**Icons aren't loading on the connector card**: same-origin icon URLs work better than cross-origin CDN URLs for many connector UIs (the FastMCP `/consent` page loads icons same-origin under a strict CSP). The advertised `Icon` URLs in `initialize` should resolve to this server's own host.
