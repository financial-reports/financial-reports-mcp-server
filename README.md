# FinancialReports MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP Spec](https://img.shields.io/badge/MCP-2025--11--25-green)](https://modelcontextprotocol.io)
[![Status](https://img.shields.io/badge/status-production-green)](https://mcp.financialfilings.com/health)

> **Official Model Context Protocol (MCP) server for the [FinancialReports](https://financialreports.eu) API.**
> Direct access from Claude (and any MCP-compatible client) to regulatory filings, financial data, and corporate information from listed companies worldwide. **15 curated tools by default** (set `MCP_FULL_SURFACE=1` for the full 42-tool surface). **Free for any FinancialReports account.** Sourced from official regulators.

---

## Quick start

If you're an analyst, researcher, or anyone who wants to ask Claude about public-company filings:

1. **Create a free account** at [financialreports.eu](https://financialreports.eu/) — the MCP connector is free for any FinancialReports user. No paid plan required.
2. **Add the connector** in your MCP client — pick yours under [Connect your client](#connect-your-client) below. The two most common:
   - **Claude.ai / Claude Desktop**: Settings → Connectors → Add custom connector → URL: `https://mcp.financialfilings.com/mcp`
   - **Claude Code**: `claude mcp add --transport http financialreports https://mcp.financialfilings.com/mcp`
3. **Sign in** with your FinancialReports account when prompted. That's it.

Full setup walkthrough with screenshots: [financialreports.eu/integrations/claude/](https://financialreports.eu/integrations/claude/).

---

## Connect your client

This is a **remote** MCP server — Streamable HTTP with OAuth (PKCE + Dynamic Client Registration). There is **no API key to copy and no secret to store**: connecting opens a browser sign-in with your FinancialReports account.

**Endpoint:** `https://mcp.financialfilings.com/mcp`

Find your client below. If it isn't listed, use the [**Generic**](#generic-any-mcp-client) block at the end — the endpoint and OAuth flow are identical everywhere; only the config file differs.

### Claude.ai / Claude Desktop

Settings → Connectors → **Add custom connector** → URL: `https://mcp.financialfilings.com/mcp`. Sign in when prompted.

### Claude Code

```bash
claude mcp add --transport http financialreports https://mcp.financialfilings.com/mcp
```

Run `/mcp` in-session to complete the browser sign-in.

### Codex (OpenAI)

Codex uses TOML. Add to `~/.codex/config.toml` (or a project `.codex/config.toml`):

```toml
[mcp_servers.financialreports]
url = "https://mcp.financialfilings.com/mcp"
```

Then authenticate — Codex runs the OAuth browser flow for servers that support it:

```bash
codex mcp login financialreports
```

### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per project):

```json
{
  "mcpServers": {
    "financialreports": { "url": "https://mcp.financialfilings.com/mcp" }
  }
}
```

OAuth runs in the browser on first use.

### Kilo Code

Project `.kilocode/mcp.json` (or the global MCP settings file):

```json
{
  "mcpServers": {
    "financialreports": {
      "type": "remote",
      "url": "https://mcp.financialfilings.com/mcp"
    }
  }
}
```

### opencode

`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "financialreports": {
      "type": "remote",
      "url": "https://mcp.financialfilings.com/mcp",
      "enabled": true
    }
  }
}
```

### Gemini CLI

`~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "financialreports": { "httpUrl": "https://mcp.financialfilings.com/mcp" }
  }
}
```

### Hermes

`mcp_servers` in your Hermes config (YAML):

```yaml
mcp_servers:
  financialreports:
    url: "https://mcp.financialfilings.com/mcp"
    auth: oauth
```

### Generic (any MCP client)

Most MCP-aware harnesses accept a `mcpServers` object. Point it at the endpoint over Streamable HTTP:

```json
{
  "mcpServers": {
    "financialreports": {
      "type": "streamable-http",
      "url": "https://mcp.financialfilings.com/mcp"
    }
  }
}
```

Clients with native remote-MCP OAuth (Claude, Cursor, Windsurf, VS Code, opencode, Codex via `codex mcp login`) run the sign-in in a browser automatically. For **OpenClaw** and other MCP-aware harnesses, use this block with the connector URL and complete OAuth when prompted — see your client's own MCP configuration docs for the exact file location.

---

## What you get

**15 LLM-callable tools by default** — the curated surface analysts actually use:

| Domain | Tools | Use cases |
|---|---|---|
| Companies | 4 | Search by name/ticker/ISIN, retrieve full company profiles, get normalized financials, predict next annual report |
| Filings | 4 | List, retrieve, fetch markdown content (capped at 150K chars), keyword-search inside a single filing |
| ISINs | 2 | Lookup by ISIN, list dual-listings |
| Reference taxonomy | 2 | Filing categories and filing types |
| Guides | 3 | Filing-type taxonomy, ISIC industry classification, and markdown-fetch strategy — callable references for tool-only clients that can't read MCP resources |

Set `MCP_FULL_SURFACE=1` to restore the full **42-tool** surface: the ISIC section/division/group/class hierarchy, the rest of the reference data (countries, languages, sources, line-item definitions, filing history), per-user watchlists, and webhook subscriptions.

The shipped surface is generated from a committed, reviewed snapshot of the [FinancialReports OpenAPI schema](https://financialreports.eu/api/schema/) (`scripts/openapi.snapshot.json`, pinned via `FR_PIN_SCHEMA=1` in CI and the Docker build), so it's deterministic and never drifts silently on a rebuild.

### Companion skill

The repository ships an [Agent Skill](skills/financial-filings-research/) — `financial-filings-research` — that teaches Claude how to compose these tools into the workflows analysts actually run: company lookup, filing summarization, multi-company financial comparison, ISIC industry screening, and filings monitoring. It activates automatically when the user mentions a company name, ticker, ISIN, filing type, or financial metric.

---

## Architecture

```
┌──────────────────┐     OAuth (PKCE + DCR)      ┌──────────────────┐
│  Claude / MCP    │  ───────────────────────►   │  AWS Cognito     │
│  client          │                              │  (user pool)     │
└────────┬─────────┘                              └────────┬─────────┘
         │  Streamable HTTP /mcp                           │
         │  + bearer token                                 │
         ▼                                                 │
┌──────────────────┐     verify subscription tier          │
│  This server     │  ───────────────────────────────────► │
│  (FastAPI +      │                                       ▼
│   FastMCP)       │     proxy bearer token         ┌──────────────────┐
│                  │  ─────────────────────────►    │  api.            │
│  15 tools        │                                │  financial-      │
│  generated from  │                                │  reports.eu      │
│  OpenAPI schema  │                                │  (first-party)   │
└──────────────────┘                                └──────────────────┘
```

**Key design decisions:**

- **Tools are generated, not hand-written.** `scripts/generate_mcp_tools.py` reads the OpenAPI schema — pinned to a committed snapshot via `FR_PIN_SCHEMA=1` in CI and the Docker build — and emits `src/financial_reports_mcp.py`. The default surface is curated to a focused 15-tool set; `MCP_FULL_SURFACE=1` emits the full surface.
- **Bearer-token proxy, not session storage.** The user's Cognito access token is forwarded to the upstream API on every call. No conversation data, no API responses cached server-side.
- **Subscription gating in-process.** A 15-second LRU cache holds Cognito `sub` → tier mappings to avoid hammering the FR API on every tool call.
- **Same-origin asset proxy.** `/favicon.ico`, `/icon.png`, `/icon-{32,192,512}.png` are served from this origin (proxied + cached from CDN) so connector UIs and the `/consent` page render without cross-origin CSP friction.

---

## MCP spec compliance

Compliant with the [MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25):

- ✅ **Streamable HTTP transport** — `POST /mcp` with `MCP-Protocol-Version` echo, 400 on unsupported versions
- ✅ **OAuth 2.0** — RFC 7591 dynamic client registration + PKCE S256
- ✅ **RFC 9728 protected-resource metadata** — both at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/mcp`
- ✅ **Tool annotations** — every tool has `title` plus `readOnlyHint` or `destructiveHint`
- ✅ **`outputSchema`** — six structured-content tools (`companies_list`, `companies_retrieve`, `companies_financials_retrieve`, `filings_list`, `filings_retrieve`, `isins_list`)
- ✅ **Origin validation** — 403 on unrecognized origins, 401 with proper `WWW-Authenticate` header for unauthenticated requests
- ✅ **Multi-size connector icons** — 32×32, 192×192, 512×512 PNG advertised in `initialize` response

CI verifies all of the above on every PR.

---

## Tool catalog

The list below is regenerated by `scripts/generate_mcp_tools.py` on every build. Do not hand-edit between the markers.

<!-- BEGIN AUTO-GENERATED TOOL LIST -->
<!-- DO NOT EDIT BY HAND. Re-run scripts/generate_mcp_tools.py. -->

### Companies
* `companies_financials_retrieve` — Retrieve Company Financials
* `companies_list` — List Companies
* `companies_next_annual_report_retrieve` — Predict Next Annual Report
* `companies_retrieve` — Retrieve Company Details

### Filing Categories
* `filing_categories_list` — List Filing Categories

### Filing Types
* `filing_types_list` — List Filing Types

### Filings
* `filings_list` — List Filings
* `filings_markdown_retrieve` — Retrieve Filing Markdown
* `filings_retrieve` — Retrieve Filing Details

### ISINs
* `isins_list` — List ISINs
* `isins_retrieve` — Retrieve ISIN

<!-- END AUTO-GENERATED TOOL LIST -->

---

## Example prompts

Once connected, try:

- *"Find Apple's most recent 10-K and summarize the risk factors that changed year-over-year."*
- *"Get full company details for ASML."*
- *"Compare net debt for Iberdrola, Engie, Enel, RWE for the latest fiscal year."*
- *"List EU airlines that filed annual reports in the last 6 months."*
- *"Show me insider-transaction filings at Tesla in the last 30 days."*
- *"Alert me when any company in my watchlist files an 8-K."*
- *"What's the LEI for Volkswagen AG?"*

---

## Self-hosting

Self-hosting requires standing up your own AWS Cognito user pool and is primarily useful for forking + adapting to a different upstream API. For the FinancialReports API specifically, the hosted server at `mcp.financialfilings.com` is the supported path.

Detailed self-hosting docs (Docker, Cognito setup, env vars, CDN/icon configuration): **[docs/SELF-HOSTING.md](docs/SELF-HOSTING.md)**.

---

## Development

One-shot bootstrap (venv → deps → env check → generate → run):

```bash
cp .env.example .env   # fill in Cognito values first; see docs/SELF-HOSTING.md
make dev               # creates .venv, installs, validates env, regenerates, serves on :8000
# MCP endpoint: http://localhost:8000/mcp
```

Or step by step:

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# 2. Configure
cp .env.example .env  # then fill in Cognito values; see docs/SELF-HOSTING.md

# 3. Generate the MCP module from the OpenAPI schema
python scripts/generate_mcp_tools.py

# 4. Run tests
pytest

# 5. Run locally
python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000
# MCP endpoint: http://localhost:8000/mcp
```

CI runs the full unit suite plus a Docker-Compose end-to-end test (with Redis) on every PR. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

### Local development with a personal API key

For iterating on the generator, tools, or prompts against a real backend **without** going through the Cognito OAuth dance every restart, the server supports a dev-only `DEV_MODE_API_KEY` env var. When set, JWT validation is skipped on the existing `/mcp` endpoint (both the `subscription_required` and `_authorize_or_raise` paths) and the key is forwarded as `X-API-Key` to `API_BASE_URL`.

**This is a maintainer convenience, not a production auth path.** The module refuses to import if `MCP_BASE_URL` contains a production hostname (`mcp.financialfilings.com`).

1. Add your personal FinancialReports API key to `.env`:
   ```
   DEV_MODE_API_KEY=fr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   MCP_BASE_URL=http://localhost:8000
   ```
2. Regenerate and start the server (Cognito vars must still be set — the OAuth proxy module loads even when the bypass is active):
   ```bash
   make regen
   python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Point Claude Code at the local instance:
   ```bash
   claude mcp add --transport http financialreports-local http://localhost:8000/mcp
   ```

Production headless / API-key auth (parallel `/mcp/apikey` endpoint with per-request `X-API-Key`) is tracked in [#28](https://github.com/financial-reports/financial-reports-mcp-server/issues/28) and is a separate feature from this dev-mode shortcut.

### Common tasks

```bash
# Regenerate tools after the OpenAPI schema changes
python scripts/generate_mcp_tools.py

# Run only fast unit tests
pytest tests/test_*.py

# Run end-to-end tests with Redis (requires Docker)
make e2e
```

---

## Evaluating changes

This server is benchmarked by [`financial-reports/mcp-evals`](https://github.com/financial-reports/mcp-evals) (private). Cross-model scorecards (task success, tool-selection accuracy, path consistency, tokens/turns/latency) live there, not here. Before merging changes to tool descriptions, Prompts, or the generator, run the harness against either prod or a local dev MCP and compare the scorecard.

What lives in **this** repo: deterministic prompt-registration tests at `tests/eval/` — fast, no API keys, run on every PR. See [`tests/eval/README.md`](tests/eval/README.md) for the cross-repo workflow.

---

## Security

This server handles OAuth flows and bearer tokens. **Found a vulnerability? Please don't open a public issue.** See [SECURITY.md](SECURITY.md) for the responsible-disclosure process.

Server-side guarantees:

- Bearer tokens are proxied per-request, never logged or persisted.
- HTTPS is enforced (HTTP redirects to HTTPS at the edge).
- CSP is applied to HTML responses (`default-src 'none'`, only same-origin assets allowed).
- Origin validation rejects requests from unrecognized origins.
- All cryptographic operations rely on standard library + AWS SDKs; no custom crypto.

---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the regenerate→test→PR workflow, and what kinds of changes are welcome (tests, docs, generator improvements, hand-tuned tool descriptions in `scripts/generate_mcp_tools.py`) versus what gets rejected (hand-edited `src/financial_reports_mcp.py` — it's auto-generated and overwritten on every build).

---

## Project status

- **Production**: live at `https://mcp.financialfilings.com/mcp`
- **MCP Directory**: submitted for inclusion (May 2026)
- **Spec compliance**: MCP 2025-11-25
- **Tested with**: Claude.ai, Claude Code, Claude Desktop, Cursor, Windsurf. Config snippets also provided for Codex, Kilo Code, opencode, Gemini CLI, and Hermes (see [Connect your client](#connect-your-client)).

---

## License

[MIT](LICENSE) — © FinancialReports.

---

## Acknowledgments

Special thanks to [@itisaevalex](https://github.com/itisaevalex) for the [original community-built MCP server](https://github.com/itisaevalex/financial-reports-mcp-server), which served as the proof-of-concept that motivated this official version.

Built on [FastMCP](https://github.com/jlowin/fastmcp), [FastAPI](https://fastapi.tiangolo.com/), and the [Model Context Protocol](https://modelcontextprotocol.io).
