# FinancialFilings for Claude Code

The official FinancialFilings plugin. It connects Claude Code to the FinancialFilings MCP server, so Claude can find listed companies worldwide, read their regulatory filings as Markdown, and pull standardised financial statements, all from inside your terminal session.

FinancialFilings collects annual and quarterly reports, ad-hoc disclosures, insider transactions and XBRL/ESEF financials as companies publish them with their securities regulators. A free FinancialFilings account is enough; no API key and no paid plan.

## What the plugin adds

- **The FinancialFilings MCP server**: a remote server at `https://mcp.financialfilings.com/mcp`, which Claude calls to search companies, list and read filings, and fetch financials.
- **The `financial-filings-research` skill**: instructions and a tool cheat-sheet that show Claude how to combine those tools for company lookup, filing summaries, multi-company comparisons, industry screening and filings monitoring.

## Install

```
/plugin install financialfilings --marketplace financial-reports/financial-reports-mcp-server
```

Then run `/mcp` and sign in with your FinancialFilings account (or create one for free at [financialfilings.com](https://financialfilings.com/)). Ask Claude something like "summarise the latest annual report of Siemens" to try it.

## What it runs and what it sends

- The plugin runs nothing on your machine. It has no hooks, no scripts and no local server. The skill is text only.
- Claude connects to one destination: `mcp.financialfilings.com`. Sign-in is OAuth in your browser. The server receives your account identity and the tool calls Claude makes (for example a company name or a filing ID). It returns public filings data.
- See our [privacy policy](https://financialfilings.com/data-privacy/) and [terms](https://financialfilings.com/terms/).

## Help

- Setup guide: [financialfilings.com/integrations/claude-code/](https://financialfilings.com/integrations/claude-code/)
- Support: [support@financialfilings.com](mailto:support@financialfilings.com)
- Source and issues: [github.com/financial-reports/financial-reports-mcp-server](https://github.com/financial-reports/financial-reports-mcp-server)

MIT licensed.
