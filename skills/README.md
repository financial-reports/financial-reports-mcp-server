# Skills for the FinancialReports MCP

Agent Skills that pair with the [FinancialReports MCP server](https://github.com/financial-reports/financial-reports-mcp-server). The hosted connector exposes **16** tools for regulatory-filings research (46 exist in the full schema; the rest are behind `MCP_FULL_SURFACE=1` and are not enabled on the hosted server); these skills teach Claude how to compose those tools into the workflows analysts actually run.

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
   - **Claude.ai** — upload the folder as a zip, or install from the Anthropic Skills Directory.

Verify it registered by asking Claude `what skills do you have?` — `financial-filings-research` should be listed.

## How invocation actually works — read this before you judge the skill

Skills use **progressive disclosure**: the frontmatter `description` sits in the
model's context, but the SKILL.md **body loads only when the model invokes the
skill**. It is not injected into every conversation.

**Measured behaviour** (18 Claude Code runs, sonnet-4-6, tasks squarely inside
this skill's stated scope, with the MCP connector enabled):

| condition | skill invoked |
|---|---|
| ordinary phrasing, e.g. *"what was VW's FY2024 revenue?"* | **0/12** |
| description rewritten as an explicit trigger | **0/6** |
| user names it — *"use the financial-filings-research skill"* | **1/1** |

A model that already has the connector's 16 tools in context simply uses them;
it does not reach for the skill on its own. Rewording the description did not
change this.

**So, practically:**

- **To guarantee the skill is used, name it**: *"Using the financial-filings-research skill, compare net debt for Iberdrola and Engie."* Or add a line to your project's `CLAUDE.md`: `For any FinancialReports question, first load the financial-filings-research skill.`
- **Do not expect it to fire on its own.** If you install it and see no change, that is the documented behaviour, not a broken install.
- Guidance that must apply to *every* answer belongs in your `CLAUDE.md` or in the tool descriptions — not in a skill body.

## Using the workflows on other harnesses

The skill's *content* — tool-sequencing, comparison/screening workflows, and pitfalls — is harness-agnostic guidance, not Claude-specific. Harnesses that don't consume the `SKILL.md` format (Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, OpenClaw, …) can use the same guidance via [`docs/WORKFLOWS.md`](../docs/WORKFLOWS.md), which is the single plain-Markdown source the skill is built around. The root [`AGENTS.md`](../AGENTS.md) points agents at it automatically.

## Connector

- **MCP server URL**: `https://mcp.financialfilings.com/mcp`
- **Documentation**: https://financialreports.eu/integrations/claude/
- **Source**: this repository (server code lives in `src/`, tool generation in `scripts/`)
