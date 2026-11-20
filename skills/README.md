# Skills for the FinancialFilings MCP

Agent Skills that pair with the [FinancialFilings MCP server](https://github.com/financial-reports/financial-reports-mcp-server). The hosted connector exposes **17** tools for regulatory-filings research, administrative, reference and webhook-management endpoints are not part of the research surface; these skills teach Claude how to compose those tools into the workflows analysts actually run.

**New here? Start with [GETTING-STARTED.md](./GETTING-STARTED.md)**, connector setup, install, and four worked examples with real output.

## Available skills

`financial-filings-research` is the base: company resolution, tool order, and the
data-quality checks the tool schemas do not express. The other four are job-shaped
and build on it, so install the base plus whichever jobs you do. Skills load
progressively, so several focused ones cost little: until one triggers, Claude sees
only its name and description.

| Name | What it does |
|---|---|
| [`financial-filings-research`](./financial-filings-research/SKILL.md) | **The base.** Research public companies' official filings, financial statements, and industry context. Company lookup, filings retrieval and summarization, multi-company comparison, ISIC screening, plus the provenance, as-reported and currency checks that catch a wrong source document. |
| [`filing-section-finder`](./filing-section-finder/SKILL.md) | Find one named part of a filing: risk factors, segment note, guidance, auditor's report, related parties. Searches inside the document and returns the passage with its offset, instead of downloading the whole report. |
| [`company-brief`](./company-brief/SKILL.md) | One company summarised from its own filings: a tear sheet, or a results recap of the latest period against the prior period and prior year. Carries currency, period end and source filing on every figure. |
| [`peer-comparison`](./peer-comparison/SKILL.md) | Two or more named companies side by side on the same line items for the same fiscal period, with currency and period end as columns rather than assumptions. |
| [`industry-screen`](./industry-screen/SKILL.md) | A list of companies rather than facts about one: ISIC sub-industry and country screening, with the listing filter that keeps dead registrations out. |

Each job-shaped skill names which of the others to use instead when the request is
really a different job, so they do not compete for the same question.

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

1. **The FinancialFilings MCP connector enabled**: `https://mcp.financialfilings.com/mcp`
2. **The skill registered:**
   - **Claude Code**. Copy the skill folder into `~/.claude/skills/` (all projects) or `<project>/.claude/skills/` (one project):
     ```bash
     git clone https://github.com/financial-reports/financial-reports-mcp-server
     cp -R financial-reports-mcp-server/skills/financial-filings-research ~/.claude/skills/
     ```
   - **Claude.ai / Claude Desktop**: Settings → Capabilities → Skills → Upload skill, and select the folder zipped.

Confirm it registered by asking Claude `what skills do you have?`.

## Using a skill

Skills use progressive disclosure: the frontmatter `description` stays in
context, and the body loads when the skill is invoked.

In Claude Code, invoke it with the slash command:

```
/financial-filings-research
```

Or name it in the request, *"Using the financial-filings-research skill, compare
net debt for Iberdrola and Engie for the latest fiscal year."*

To apply it to every FinancialFilings question in a project, add a line to that
project's `CLAUDE.md`:

```
For any FinancialFilings question, load the financial-filings-research skill first.
```

That last form is the one to give a team: set once, and every session picks it up.

## Using the workflows on other harnesses

The skill's *content*, tool-sequencing, comparison/screening workflows, and pitfalls, is harness-agnostic guidance, not Claude-specific. Harnesses that don't consume the `SKILL.md` format (Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, OpenClaw, …) can use the same guidance via [`docs/WORKFLOWS.md`](../docs/WORKFLOWS.md), which is the single plain-Markdown source the skill is built around. The root [`AGENTS.md`](../AGENTS.md) points agents at it automatically.

## Connector

- **MCP server URL**: `https://mcp.financialfilings.com/mcp`
- **Documentation**: https://financialfilings.com/integrations/claude/
- **Source**: this repository (server code lives in `src/`, tool generation in `scripts/`)
