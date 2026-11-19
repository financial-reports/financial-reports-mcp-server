---
type: agent
expect:
  id: number
---
You are the FinancialFilings financials endpoint for this run. Answer each call with
a JSON object only, no prose, in the SERVED response shape. ⚠ Types matter: `currency` is an OBJECT
`{"code": "SEK", "name": "Swedish krona", "symbol": "kr"}`, never a bare
string; `value` and `raw_value` are exact decimal STRINGS such as "51900";
`scale` is lower-case (`millions`); `trust_tier` is one of `xbrl`,
`xbrl-derived`, `verified`, `accepted`, `review`, `derived`. The shape: top-level `company_id`,
`currency`, `sources_masked`, `period_count` and `periods[]`, each period carrying
`statements[]`, each statement carrying `currency` and `line_items[]` with `code`,
`name`, `value`, `raw_value`, `scale` and `currency`. ⚠ Use the SERVED codes:
`operating_income_loss`, not `operating_profit`; `net_income_loss`, not
`net_income`. The live API returns a 400 naming an unknown code, and a fixture
that accepts invented codes lets an eval pass on a call that would really fail.

⚠ WHY THIS IS AN AGENT MOCK. A fixed mock returns one body whatever `id` it is
given, which a comparison case cannot survive: the first version handed a German,
EUR-reporting company the Swedish company's figures to the digit, the model under
test correctly refused to tabulate them, and the rubric marked it wrong. The
companies have to differ.

For `id: 4412` (Nordwind Energi AB, Sweden, SEK, December year end) return
`period_end_date` 2025-12-31 with a `revenue` line item raw_value "51900" scale millions and an
`operating_income_loss` line item raw_value "4110" scale millions.

For `id: 5571` (Helios Turbinen GmbH, Germany, EUR, AUGUST year end) return
`period_end_date` 2025-08-31 with a `revenue` line item raw_value "2980" scale millions and NO
`operating_income_loss` line item at all. Both of those are deliberate: the differing
period end is a real comparison hazard, and the absent line item checks that it
is shown as n/a rather than as zero and that no margin is computed for it.

Set `sources_masked` false and give each statement a `sources` array with one
`filing_id`. For any other `id`, return `period_count` 0 and an empty `periods`
array.
