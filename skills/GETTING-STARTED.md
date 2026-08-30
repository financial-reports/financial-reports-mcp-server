# Getting started

A ten-minute path from nothing to your first answer, using the FinancialReports
MCP connector plus the `financial-filings-research` skill.

The connector gives Claude the data. The skill gives it the analyst workflows —
which tool to reach for, how to compare companies safely, and what to check
before reporting a figure.

---

## 1. Enable the connector

`https://mcp.financialfilings.com/mcp`

- **Claude.ai / Claude Desktop** — Settings → Connectors → Add custom connector
- **Claude Code** — add it to `.mcp.json`:
  ```json
  { "mcpServers": { "fr": { "type": "http", "url": "https://mcp.financialfilings.com/mcp" } } }
  ```

You'll be asked to sign in to FinancialReports the first time. The connector
exposes 16 tools covering companies, filings, filing content and normalised
financial statements.

## 2. Install the skill

**Claude Code**

```bash
git clone https://github.com/financial-reports/financial-reports-mcp-server
cp -R financial-reports-mcp-server/skills/financial-filings-research ~/.claude/skills/
```

Use `~/.claude/skills/` for every project, or `<project>/.claude/skills/` for one.

**Claude.ai / Claude Desktop** — Settings → Capabilities → Skills → Upload skill,
and select the zipped folder.

Confirm it registered: ask Claude `what skills do you have?`

## 3. Use it

In Claude Code, type the slash command:

```
/financial-filings-research
```

Claude confirms the skill is loaded, then you ask your question normally.

You can also just name it — *"Using the financial-filings-research skill,
compare …"* — or, to apply it to every question in a project, add one line to
that project's `CLAUDE.md`:

```
For any FinancialReports question, load the financial-filings-research skill first.
```

---

## Examples

Real prompts and real (abridged) answers.

### Find a company's latest annual report

> **Which annual report did Roche most recently file, and when?**

| Field | Value |
|---|---|
| Filing type | Annual Report (`10-K`) |
| Release date | 2026-02-02 |
| Filing ID | 32916850 |

Title: *Jahresabschluss zum Geschäftsjahr vom 01.01.2024 bis zum 31.12.2024*

Claude resolves the company, filters filings by type, and sorts newest-first —
three tool calls, no guesswork about parameter names.

### Pull financial line items

> **What were Apple's revenue and net income for FY2025?**

| Metric | Value | Currency | Fiscal period | Period end |
|---|---|---|---|---|
| Revenue | $416,161M | USD | FY2025 | 2025-09-27 |
| Net income | $112,010M | USD | FY2025 | 2025-09-27 |

Note the answer states the fiscal period and currency rather than a bare number
— the skill requires it, because "FY2025" means different things at different
companies (see the next example).

### Compare companies

> **Compare FY2025 revenue for Apple, Microsoft and Alphabet in one table.**

| Company | FY2025 period end | Revenue (USD) |
|---|---|---|
| Apple Inc. | 2025-09-27 | $416,161M |
| Alphabet Inc. | 2025-12-31 | $402,836M |
| Microsoft Corp | 2025-06-30 | $281,724M |

The period-end column is the point: these three "FY2025" figures cover three
different twelve-month windows. The skill makes Claude surface that instead of
lining up numbers that look comparable and are not.

### Read a section out of a filing

> **Find the section of Roche's most recent annual report that discusses risk
> management, and quote a short excerpt.**

> *Zur sorgfältigen Prüfung des Geschäftsumfeldes hinsichtlich möglicher
> Risikoszenarien … hält Roche konzernweit ein Risikomanagement-System vor.*
>
> **Translation:** To carefully examine the business environment for possible
> risk scenarios, Roche maintains a group-wide risk management system.

Claude searched inside the filing rather than downloading all of it, found the
German-language section (there is no literal "Risk Factors" heading in a German
annual report), and flagged the language.

---

## What the skill adds beyond the raw tools

- **Right tool, right parameters.** Several parameter names are not what you would
  guess — the bundled `references/tool-cheatsheet.md` has the real ones.
- **Comparisons that hold up.** Currency and fiscal period travel with every
  figure, so a table is actually comparable.
- **Search inside filings** instead of pulling a 500,000-character document.
- **Checks before reporting a number** — whether a figure is as-reported or
  derived, whether its source filing can be cited, and whether a period looks
  like it came from a different reporting entity.

## Where to go next

- `skills/financial-filings-research/SKILL.md` — the full workflows
- `skills/financial-filings-research/references/tool-cheatsheet.md` — every tool, its real parameters and response shape
- `docs/WORKFLOWS.md` — the same guidance in plain Markdown, for tools that do not read the `SKILL.md` format (Codex, Cursor, Gemini CLI, …)
