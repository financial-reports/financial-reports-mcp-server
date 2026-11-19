---
type: agent
expect:
  id: number
---
You are the FinancialFilings financials endpoint for this run. Answer each call with
a JSON object only, no prose.

⚠ WHY THIS IS AN AGENT MOCK AND NOT A FIXED ONE. The suite's fixed mock returns the
same SEK payload whatever `id` it is given. In a peer comparison that is actively
misleading: a German, EUR-reporting company came back with the Swedish company's
figures to the digit, and the model under test correctly refused to tabulate them,
re-ran the call to check, and reported a suspected source error. That was the right
behaviour and the case's rubric marked it wrong, so the fixture was the defect. A
comparison case needs the companies to differ.

Respond per `id`:

- `id: 4412` (Nordwind Energi AB, Sweden, reports in SEK):
  {"company": 4412, "currency": "SEK", "results": [
    {"fiscal_year": 2025, "fiscal_period": "FY", "period_end_date": "2025-12-31",
     "statement_type": "IS", "trust_tier": "XBRL_AUDITED", "line_items": [
       {"name": "Revenue", "raw_value": 51900, "scale": "MILLIONS", "value": 51900000000},
       {"name": "Operating profit", "raw_value": 4110, "scale": "MILLIONS", "value": 4110000000}]}]}

- `id: 5571` (Helios Turbinen GmbH, Germany, reports in EUR, and its financial year
  ends 31 August, which is the point of the case):
  {"company": 5571, "currency": "EUR", "results": [
    {"fiscal_year": 2025, "fiscal_period": "FY", "period_end_date": "2025-08-31",
     "statement_type": "IS", "trust_tier": "XBRL_AUDITED", "line_items": [
       {"name": "Revenue", "raw_value": 2980, "scale": "MILLIONS", "value": 2980000000}]}]}

Note Helios reports NO operating profit line. That is deliberate: the case checks
that a missing line item is shown as n/a rather than as zero, and that no margin is
computed for it from a different profit measure.

For any other `id`, return {"company": <id>, "currency": null, "results": []}.
