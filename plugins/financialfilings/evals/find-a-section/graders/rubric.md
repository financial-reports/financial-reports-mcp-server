---
type: llm
weight: 2
focus: last_message
---
The user asked what a company's latest annual report says about its risk factors, and asked for a quote.

What the tools returned: filing 998101, released 2026-03-12, period end 2025-12-31, with 4 total matches for the phrase and 2 passages shown. One passage is about customer concentration (three customers, 48 per cent of revenue). The other is about component availability and single-sourced magnet suppliers.

PASS only if ALL of these hold:
- It quotes or closely reproduces at least one of those two passages, rather than only describing them in the abstract.
- It gives the filing's vintage somewhere: the release date, the period end, or the fiscal year.

Judge the SUBSTANCE, not the layout. Blockquote, inline quotation marks and indented text all pass equally. Mentioning the character offsets, the source link, or the exact match count is GOOD but NOT required, and an answer must not be failed for leaving any of them out. Saying that more matches exist than were shown is also good and not required.

FAIL only if one of these holds:
- It attributes risk factors to the company that are not in the two passages, for example currency hedging, litigation, climate or cyber risk. Inventing content is the one thing that must fail.
- It says the filing has no risk-factor section, or that it could not find one.
- It presents the two passages as definitively the company's complete set of risks while the tool reported more matches than it showed.
