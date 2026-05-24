# Skills for the FinancialReports MCP

Agent Skills that pair with the [FinancialReports MCP server](https://github.com/financial-reports/financial-reports-mcp-server). The MCP exposes 42 tools for regulatory-filings research; these skills teach Claude how to compose those tools into the workflows analysts actually run.

## Available skills

| Name | What it does |
|---|---|
| [`financial-filings-research`](./financial-filings-research/SKILL.md) | Research public companies' regulatory filings, financial statements, and industry context. Workflows for company lookup, filings retrieval and summarization, multi-company financial comparison, ISIC industry screening, and filings-monitoring setup with watchlists + webhooks. |

## Format

Each skill follows the standard Claude Skills layout:

```
skills/
  <skill-name>/
    SKILL.md             # Frontmatter (name, description) + body
    references/          # Optional ancillary docs Claude loads on demand
      tool-cheatsheet.md
```

The frontmatter `description` is what Claude scans to decide whether to activate the skill — it's deliberately specific about triggering keywords ("10-K", "ISIN", "compare companies", etc.).

## Using a skill

These skills are designed to activate automatically once Claude has both:
1. The FinancialReports MCP connector enabled, and
2. The skill registered (Claude.ai users: via the Anthropic Skills Directory; Claude Code users: copy the skill folder into `~/.claude/skills/` or your project's `.claude/skills/`).

No manual invocation needed — Claude picks the skill up when the user's prompt matches the description's trigger keywords.

## Using the workflows on other harnesses

The skill's *content* — tool-sequencing, comparison/screening workflows, and pitfalls — is harness-agnostic guidance, not Claude-specific. Harnesses that don't consume the `SKILL.md` format (Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, OpenClaw, …) can use the same guidance via [`docs/WORKFLOWS.md`](../docs/WORKFLOWS.md), which is the single plain-Markdown source the skill is built around. The root [`AGENTS.md`](../AGENTS.md) points agents at it automatically.

## Connector

- **MCP server URL**: `https://mcp.financialfilings.com/mcp`
- **Documentation**: https://financialreports.eu/integrations/claude/
- **Source**: this repository (server code lives in `src/`, tool generation in `scripts/`)
