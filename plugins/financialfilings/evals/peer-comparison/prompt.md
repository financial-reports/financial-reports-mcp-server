---
name: peer-comparison
description: Does the agent batch-resolve, surface the company it could NOT resolve, and put currency and period end in the table rather than hiding them?
tags: [skills, peers]
runs: 3
max_turns: 16
allowed_tools: [Skill, mcp__plugin_financialfilings_financialfilings__companies_resolve_create, mcp__plugin_financialfilings_financialfilings__companies_list, mcp__plugin_financialfilings_financialfilings__companies_financials_retrieve]
---

Compare Nordwind Energi, Helios Turbinen and Brightwater Marine on revenue and operating profit for their latest full year. A table is fine.
