---
name: industry-screen
description: Does the agent apply the listing filter, state the ISIC class it screened on, and report the true count instead of presenting one page as the industry?
tags: [skills, screen]
runs: 3
max_turns: 14
allowed_tools: [Skill, mcp__plugin_financialfilings_financialfilings__companies_list, mcp__plugin_financialfilings_financialfilings__get_fr_industry_classification_isic, mcp__plugin_financialfilings_financialfilings__companies_financials_retrieve]
---

Which listed companies are in the same industry as Nordwind Energi? Give me the European ones.
