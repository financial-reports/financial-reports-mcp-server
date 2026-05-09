# FinancialReports MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP Spec](https://img.shields.io/badge/MCP-2025--11--25-green)](https://modelcontextprotocol.io)
[![Status](https://img.shields.io/badge/status-production-green)](https://mcp.financialfilings.com/health)

> **Official Model Context Protocol (MCP) server for the [FinancialReports](https://financialreports.eu) API.**
> Direct access from Claude (and any MCP-compatible client) to regulatory filings, financial data, and corporate information from listed companies worldwide. **23,683 filings · 44 markets · 9,140 companies · 21 languages.** Sourced from official regulators worldwide.

---

## Quick start

If you're an analyst, researcher, or anyone who wants to ask Claude about public-company filings:

1. **Create a free account** at [financialreports.eu](https://financialreports.eu/) — the MCP connector is free for any FinancialReports user. No paid plan required.
2. **Add the connector** in your MCP client:
   - **Claude.ai / Claude Desktop**: Settings → Connectors → Add custom connector → URL: `https://mcp.financialfilings.com/mcp`
   - **Claude Code**: `claude mcp add --transport http financialreports https://mcp.financialfilings.com/mcp`
   - **Cursor / Windsurf / other**: same URL, OAuth flow runs in the browser.
3. **Sign in** with your FinancialReports account when prompted. That's it.

Full setup walkthrough with screenshots: [financialreports.eu/integrations/claude/](https://financialreports.eu/integrations/claude/).

---

## What you get

**43 LLM-callable tools** across nine domains:

| Domain | Tools | Use cases |
|---|---|---|
| Companies | 4 | Search by name/ticker/ISIN, retrieve full company profiles, get normalized financials, predict next annual report |
| Filings | 5 | List, retrieve, fetch markdown content (capped at 150K chars), audit trail, "live pulse" of recent filings across all issuers |
| ISINs | 2 | Lookup by ISIN, list dual-listings |
| ISIC industry classifications | 8 | Section/division/group/class hierarchy for industry screening |
| Reference data | 8 | Countries, languages, sources (regulators), filing categories, filing types |
| Financial data | 2 | Normalized line-item definitions across regulators |
| Watchlist | 4 | Per-user company watchlist (single + bulk operations) |
| Webhooks | 8 | Filing-event subscriptions, delivery logs, replay, secret rotation |

All tools are auto-generated from the [FinancialReports OpenAPI schema](https://financialreports.eu/api/schema/) so the MCP surface never drifts from the underlying API.

### Companion skill

The repository ships an [Agent Skill](skills/financial-filings-research/) — `financial-filings-research` — that teaches Claude how to compose these 43 tools into the workflows analysts actually run: company lookup, filing summarization, multi-company financial comparison, ISIC industry screening, and filings monitoring. It activates automatically when the user mentions a company name, ticker, ISIN, filing type, or financial metric.

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
│  43 tools        │                                │  financial-      │
│  generated from  │                                │  reports.eu      │
│  OpenAPI schema  │                                │  (first-party)   │
└──────────────────┘                                └──────────────────┘
```

**Key design decisions:**

- **Tools are generated, not hand-written.** `scripts/generate_mcp_tools.py` reads the live OpenAPI schema and emits `src/financial_reports_mcp.py`. Adding an endpoint to the API automatically gives Claude a new tool on the next regen.
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

### Countries
* `countries_list` — List Countries
* `countries_retrieve` — Retrieve Country

### Filing Categories
* `filing_categories_list` — List Filing Categories
* `filing_categories_retrieve` — Retrieve Filing Category

### Filing Types
* `filing_types_list` — List Filing Types
* `filing_types_retrieve` — Retrieve Filing Type

### Filings
* `filings_history_retrieve` — Retrieve Filing History (Audit Trail)
* `filings_list` — List Filings
* `filings_markdown_retrieve` — Retrieve Filing Markdown
* `filings_retrieve` — Retrieve Filing Details

### Financial Data
* `line_item_definitions_list` — List Line Item Definitions
* `line_item_definitions_retrieve` — Retrieve Line Item Definition

### ISIC Classifications
* `isic_classes_list` — List ISIC Classes
* `isic_classes_retrieve` — Retrieve ISIC Class
* `isic_divisions_list` — List ISIC Divisions
* `isic_divisions_retrieve` — Retrieve ISIC Division
* `isic_groups_list` — List ISIC Groups
* `isic_groups_retrieve` — Retrieve ISIC Group
* `isic_sections_list` — List ISIC Sections
* `isic_sections_retrieve` — Retrieve ISIC Section

### ISINs
* `isins_list` — List ISINs
* `isins_retrieve` — Retrieve ISIN

### Languages
* `languages_list` — List Languages
* `languages_retrieve` — Retrieve Language

### Sources
* `sources_list` — List Data Sources
* `sources_retrieve` — Retrieve Data Source

### Watchlist
* `watchlist_companies_bulk_add_create` — Bulk Add Companies to Watchlist
* `watchlist_companies_bulk_remove_create` — Bulk Remove Companies from Watchlist
* `watchlist_companies_create` — Add Company to Watchlist
* `watchlist_retrieve` — Get User's Watchlist

### Webhooks (Management)
* `webhooks_create` — Create Webhook
* `webhooks_deliveries_replay_create` — Replay Delivery
* `webhooks_deliveries_retrieve` — List Delivery Logs
* `webhooks_delivery_detail_retrieve` — Retrieve Delivery Detail
* `webhooks_list` — List Webhooks
* `webhooks_regenerate_secret_create` — Regenerate Secret Key
* `webhooks_retrieve` — Retrieve Webhook
* `webhooks_test_create` — Test Webhook

### filings
* `filings_live_pulse_retrieve` — Filings Live Pulse Retrieve

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
- **Tested with**: Claude.ai, Claude Code, Claude Desktop, Cursor, Windsurf

---

## License

[MIT](LICENSE) — © FinancialReports.

---

## Acknowledgments

Special thanks to [@itisaevalex](https://github.com/itisaevalex) for the [original community-built MCP server](https://github.com/itisaevalex/financial-reports-mcp-server), which served as the proof-of-concept that motivated this official version.

Built on [FastMCP](https://github.com/jlowin/fastmcp), [FastAPI](https://fastapi.tiangolo.com/), and the [Model Context Protocol](https://modelcontextprotocol.io).
