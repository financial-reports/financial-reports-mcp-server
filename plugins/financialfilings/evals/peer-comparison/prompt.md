---
name: peer-comparison
description: Four companies, four resolve statuses. Does the agent batch-resolve, surface the AMBIGUOUS one instead of picking, say which one is not covered, and keep the two currencies and differing period ends out of one column?
tags: [skills, peers]
runs: 3
max_turns: 18
allowed_tools: [Skill, mcp__plugin_financialfilings_financialfilings__companies_resolve_create, mcp__plugin_financialfilings_financialfilings__companies_list, mcp__plugin_financialfilings_financialfilings__companies_financials_retrieve]
---

Compare Nordwind Energi, Helios Turbinen, Atlas Rotor and Brightwater Marine on revenue and operating profit for their latest full year. A table is fine.
