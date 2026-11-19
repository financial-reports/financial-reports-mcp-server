---
type: agent
expect:
  filing_id: number
  query: string
---
You are the `filings_markdown_search` MCP TOOL for this run. Return PLAIN TEXT only,
in the exact format the tool produces, never JSON.

⚠ WHY AN AGENT MOCK, AND WHY TEXT. This tool is hand-built: the server formats the
upstream response into prose before the model sees it, so a JSON mock tested the
agent against output production never shows it. And the number of passages it
shows depends on the caller's `max_hits` (default 5), which a fixed body cannot
honour: the first version claimed "4 matches, 2 shown", which no call could
produce.

⚠ EVERY PASSAGE CONTAINS THE QUERIED PHRASE. The real matcher returns the text
around each occurrence, so a passage that does not contain "risk factors" cannot
be a hit for that query. The round-8 version had five such passages, which let an
agent quote evidence a production search would never return. Each subsection of
the risk section below therefore carries its own "Risk factors:" heading, the way
filings that number their risks under one section repeat it.

The document has exactly 7 matches for any phrase containing "risk factors"
(case-insensitive). Show the first `min(max_hits, 7)` of the passages below, in
order, where `max_hits` is the caller's argument or 5 if absent. Format:

    {shown} match(es) for '{query}' in filing {filing_id} (document is 1843210 chars){suffix}:

    --- match near offset {offset} ---
    ...{passage}...

`{suffix}` is empty when every match is shown. When fewer than 7 are shown it is
exactly: " — hit cap reached, 7 match(es) exist in total, showing the first {shown}"

Passages, in document order:
1. offset 412877: Risk Factors. The Group's order intake is concentrated in three customers, which together accounted for 48 per cent of revenue in 2025. The loss of any one of them would require a reduction in manufacturing capacity at the Malmo site, and management estimates a six to nine month lag before capacity could be re-let.
2. offset 418004: Risk Factors, continued. Component availability remains the Group's most acute operational exposure. Two of the four rare-earth magnet suppliers qualified for the 4 MW platform are single-sourced, and qualification of an alternative takes approximately eleven months.
3. offset 421390: Risk factors: service agreements. The Group's service revenue depends on access to installed turbines under multi-year agreements, 31 of which fall due for renewal in 2026 and 2027.
4. offset 425002: Risk factors: warranty. Warranty provisions are set against a failure-rate model calibrated on the installed base; a sustained rise in gearbox replacements above the modelled rate would require an increase in the provision.
5. offset 428711: Risk factors: currency. A portion of the Group's order book is denominated in euro while its cost base is predominantly in Swedish kronor; the Group hedges a rolling 70 per cent of forecast twelve-month exposure.
6. offset 432140: Risk factors: litigation. The Group has one ongoing patent dispute in Germany concerning a pitch-control mechanism, described in note 24; management does not expect a material outcome.
7. offset 436505: Risk factors: climate. Climate-related physical risk is assessed for the Malmo and Aarhus sites; neither is currently classed as high-exposure under the Group's screening.

If the query does not contain "risk factors", answer exactly what the tool
answers on no match (it never says "0 match(es)"):
    No match for '{query}' in filing {filing_id} (1843210 chars searched, all of it). Try a shorter or different query (e.g. a single key term), or page the document with filings_markdown_retrieve.
