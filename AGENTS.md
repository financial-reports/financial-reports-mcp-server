# AGENTS.md

Agent-facing guide for the **FinancialReports MCP server** repo. This file is the cross-harness standard ([agents.md](https://agents.md)) — read by Codex, Cursor, Kilo Code, Gemini CLI, opencode, Zed, Aider, and others. Claude Code reads it too (via `CLAUDE.md`, which imports this file).

## What this repo is

The official remote [Model Context Protocol](https://modelcontextprotocol.io) server for the [FinancialReports](https://financialreports.eu) API. It exposes **42 LLM-callable tools** (regulatory filings, financials, company data, ISIC industry classification, watchlists, webhooks), auto-generated from the live OpenAPI schema. It runs as a FastAPI host that mounts a FastMCP server behind an AWS Cognito OAuth proxy. Production: `https://mcp.financialfilings.com/mcp`.

## The one rule that matters: `src/` is generated

**`src/financial_reports_mcp.py` is auto-generated and git-ignored. Never edit it — your changes are overwritten on the next build.**

To change tool behavior, descriptions, or the server itself:

1. Edit **`scripts/generate_mcp_tools.py`** (server scaffolding, the `FILE_HEADER_TEMPLATE`, tool template, landing-page HTML) and/or **`scripts/tool_overrides.yaml`** (per-tool `when_to_use` / `when_not_to_use` / `examples` that improve LLM ergonomics).
2. Regenerate: `make regen` (or `python scripts/generate_mcp_tools.py`).
3. Run tests, then commit.

The tool catalog in `README.md` (between the `AUTO-GENERATED TOOL LIST` markers) is also produced by the generator — don't hand-edit it.

## Build / test / run

```bash
make dev          # one-shot: venv -> install -> check-env -> regen -> serve on :8000
make check-env    # verify required Cognito env vars are set
make install      # install runtime + test deps
make regen        # regenerate src/financial_reports_mcp.py from the live OpenAPI schema
pytest tests/test_*.py    # fast unit tests (no docker)
make e2e          # docker-compose end-to-end suite (Redis); slow, needs docker
```

Required env vars (see `.env.example`, full setup in `docs/SELF-HOSTING.md`): `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`. Generation reads the public schema at `https://financialreports.eu/api/schema/` and needs no secrets; *running* the server needs the Cognito values.

## Code style

Python 3.11+. Format with `black` + `isort`, lint with `ruff` before committing (see `CONTRIBUTING.md`). Keep changes minimal and additive.

## Connecting a client to the running server

End users don't build anything — they point their harness at the hosted endpoint and sign in via OAuth. Per-harness connect snippets (Claude, Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, generic) are in the [README "Connect your client"](README.md#connect-your-client) section.

## Using the analyst workflows on any harness

The repo ships a Claude Agent Skill at `skills/financial-filings-research/`. Its underlying guidance — how to compose the 42 tools into real research workflows (company lookup, filing retrieval/summarization, multi-company comparison, ISIC screening, monitoring) — is harness-agnostic and lives in **[`docs/WORKFLOWS.md`](docs/WORKFLOWS.md)**. If you're an agent on any harness with this MCP connected, read that file to use the tools well.

## Security

This server handles OAuth flows and bearer tokens. Bearer tokens are proxied per-request, never logged or persisted. **Do not open public issues for vulnerabilities** — see `SECURITY.md` for responsible disclosure. Never commit secrets; `.env` is git-ignored, `.env.example` carries placeholders only.

## What gets rejected in review

- Hand-edits to `src/financial_reports_mcp.py` (it's generated).
- New tools invented in docs/skills that aren't in the served OpenAPI surface — the tool list must match what the generator emits from the live schema.
- Secrets, internal hostnames, or machine-specific paths in committed files.
