# AGENTS.md

Agent-facing guide for the **FinancialReports MCP server** repo. This file is the cross-harness standard ([agents.md](https://agents.md)) — read by Codex, Cursor, Kilo Code, Gemini CLI, opencode, Zed, Aider, and others. Claude Code reads it too (via `CLAUDE.md`, which imports this file).

## What this repo is

The official remote [Model Context Protocol](https://modelcontextprotocol.io) server for the [FinancialReports](https://financialreports.eu) API. It exposes **15 LLM-callable tools by default** (regulatory filings, financials, company data, in-filing search, plus guide tools); set `MCP_FULL_SURFACE=1` to restore the full **42-tool** surface (adds ISIC industry classification, watchlists, webhooks, and the rest of the reference data). The OpenAPI-derived tools are generated from a committed, reviewed schema snapshot (`scripts/openapi.snapshot.json`, pinned via `FR_PIN_SCHEMA=1` in CI and the Docker build). It runs as a FastAPI host that mounts a FastMCP server behind an AWS Cognito OAuth proxy. Production: `https://mcp.financialfilings.com/mcp`.

## The one rule that matters: `src/` is generated

**`src/financial_reports_mcp.py` is auto-generated and git-ignored. Never edit it — your changes are overwritten on the next build.**

To change tool behavior, descriptions, or the server itself:

1. Edit **`scripts/generate_mcp_tools.py`** (server scaffolding, the `FILE_HEADER_TEMPLATE`, tool template, landing-page HTML) and/or **`scripts/tool_overrides.yaml`** (per-tool `when_to_use` / `when_not_to_use` / `examples` that improve LLM ergonomics).
2. Regenerate: `make regen` (or `python scripts/generate_mcp_tools.py`).
3. Run tests, then commit.

The tool catalog in `README.md` (between the `AUTO-GENERATED TOOL LIST` markers) is also produced by the generator — don't hand-edit it.

### Accepted exception: synthetic (non-schema) emitted code

Most tools are generated from the OpenAPI schema, but some emitted code is **not** schema-derived and lives as inline `*_BLOCK` string templates inside `scripts/generate_mcp_tools.py`: the MCP resources (`RESOURCES_BLOCK`), prompts (`PROMPTS_BLOCK`), the guide tools (`GUIDE_TOOLS_BLOCK`), and the in-filing search tool (`MARKDOWN_SEARCH_TOOL_BLOCK`). These are still **emitted into `src/` by the generator** like everything else — they are NOT hand-edits to `src/`, and the "never edit `src/`" rule applies to them unchanged. Edit them in the generator. Trade-off worth knowing: an inline-string body isn't seen by `ruff`/`black`/`mypy` in source form (it is import/type-checked when the generated module loads in the test suite). Extracting all `*_BLOCK` bodies into separate lintable template files the generator reads is a reasonable future cleanup — do it for **all** of them or none, to keep a single pattern.

## Build / test / run

```bash
make dev          # one-shot: venv -> install -> check-env -> regen -> serve on :8000
make check-env    # verify required Cognito env vars are set
make install      # install runtime + test deps
make regen        # regenerate src/ (live schema; CI/Docker set FR_PIN_SCHEMA=1 -> committed snapshot)
pytest tests/test_*.py    # fast unit tests (no docker)
make e2e          # docker-compose end-to-end suite (Redis); slow, needs docker
```

Required env vars (see `.env.example`, full setup in `docs/SELF-HOSTING.md`): `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`. Generation reads the public schema at `https://financialreports.eu/api/schema/` — or the committed `scripts/openapi.snapshot.json` when `FR_PIN_SCHEMA=1` (as CI and the Docker build do) — and needs no secrets; *running* the server needs the Cognito values.

## Code style

Python 3.11+. Format with `black` + `isort`, lint with `ruff` before committing (see `CONTRIBUTING.md`). Keep changes minimal and additive.

## Connecting a client to the running server

End users don't build anything — they point their harness at the hosted endpoint and sign in via OAuth. Per-harness connect snippets (Claude, Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, generic) are in the [README "Connect your client"](README.md#connect-your-client) section.

## Using the analyst workflows on any harness

The repo ships a Claude Agent Skill at `skills/financial-filings-research/`. Its underlying guidance — how to compose these tools into real research workflows (company lookup, filing retrieval/summarization, multi-company comparison, ISIC screening, monitoring) — is harness-agnostic and lives in **[`docs/WORKFLOWS.md`](docs/WORKFLOWS.md)**. If you're an agent on any harness with this MCP connected, read that file to use the tools well.

## Security

This server handles OAuth flows and bearer tokens. Bearer tokens are proxied per-request, never logged or persisted. **Do not open public issues for vulnerabilities** — see `SECURITY.md` for responsible disclosure. Never commit secrets; `.env` is git-ignored, `.env.example` carries placeholders only.

## What gets rejected in review

- Hand-edits to `src/financial_reports_mcp.py` (it's generated).
- New tools invented in docs/skills that aren't actually served — the tool list must match what the generator emits (the schema-derived tools plus the documented synthetic `*_BLOCK` tools), not an aspirational set.
- Secrets, internal hostnames, or machine-specific paths in committed files.
