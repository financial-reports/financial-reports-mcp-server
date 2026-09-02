# Skills for the FinancialReports MCP

Agent Skills that pair with the [FinancialReports MCP server](https://github.com/financial-reports/financial-reports-mcp-server). The hosted connector exposes **16** tools for regulatory-filings research — administrative, reference and webhook-management endpoints are not part of the research surface; these skills teach Claude how to compose those tools into the workflows analysts actually run.

**New here? Start with [GETTING-STARTED.md](./GETTING-STARTED.md)** — connector setup, install, and four worked examples with real output.

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

The frontmatter `description` is what Claude scans to decide whether to activate the skill. Note the measured caveat in "How invocation actually works" below: scanning it is not the same as acting on it.

## Installing a skill

You need two things:

1. **The FinancialReports MCP connector enabled** — `https://mcp.financialfilings.com/mcp`
2. **The skill registered:**
   - **Claude Code** — copy the skill folder into `~/.claude/skills/` (all projects) or `<project>/.claude/skills/` (one project):
     ```bash
     git clone https://github.com/financial-reports/financial-reports-mcp-server
     cp -R financial-reports-mcp-server/skills/financial-filings-research ~/.claude/skills/
     ```
   - **Claude.ai / Claude Desktop** — Settings → Capabilities → Skills → Upload skill, and select the folder zipped.

Confirm it registered by asking Claude `what skills do you have?`.

## Using a skill

Skills use progressive disclosure: the frontmatter `description` stays in
context, and the body loads when the skill is invoked.

In Claude Code, invoke it with the slash command:

```
/financial-filings-research
```

Or name it in the request — *"Using the financial-filings-research skill, compare
net debt for Iberdrola and Engie for the latest fiscal year."*

To apply it to every FinancialReports question in a project, add a line to that
project's `CLAUDE.md`:

```
For any FinancialReports question, load the financial-filings-research skill first.
```

That last form is the one to give a team: set once, and every session picks it up.

## Using the workflows on other harnesses

The skill's *content* — tool-sequencing, comparison/screening workflows, and pitfalls — is harness-agnostic guidance, not Claude-specific. Harnesses that don't consume the `SKILL.md` format (Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, OpenClaw, …) can use the same guidance via [`docs/WORKFLOWS.md`](../docs/WORKFLOWS.md), which is the single plain-Markdown source the skill is built around. The root [`AGENTS.md`](../AGENTS.md) points agents at it automatically.

## Connector

- **MCP server URL**: `https://mcp.financialfilings.com/mcp`
- **Documentation**: https://financialfilings.com/integrations/claude/
- **Source**: this repository (server code lives in `src/`, tool generation in `scripts/`)
