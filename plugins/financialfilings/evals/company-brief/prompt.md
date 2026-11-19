---
name: company-brief
description: Does the agent take the structured financials path rather than reading the report for numbers, and does it carry currency and period end on every figure?
tags: [skills, brief]
runs: 3
max_turns: 14
allowed_tools: [Skill, mcp__plugin_financialfilings_financialfilings__companies_list, mcp__plugin_financialfilings_financialfilings__filings_list, mcp__plugin_financialfilings_financialfilings__companies_financials_retrieve, mcp__plugin_financialfilings_financialfilings__filings_markdown_search, mcp__plugin_financialfilings_financialfilings__filings_markdown_retrieve]
---

Give me a short brief on Nordwind Energi: what they do, their latest numbers, and how last year compared with the year before.
