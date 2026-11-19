---
name: peer-comparison
description: Use when the user wants two or more named companies compared on financials: "compare", "versus", "vs", "side by side", "benchmark against", "how does X stack up against Y", "which of these has higher margins", or a peer table across a named set. Resolves every company, pulls the same line items for the same fiscal period, and renders a table in which currency and period end are columns rather than assumptions.
---

# Peer comparison

Several named companies, the same metrics, one table. The whole difficulty is
that the companies do not share a currency, a period end, or an accounting
convention, and a table that hides those differences is confidently wrong.

## When to use this rather than another skill

- The user names the companies, or a set you already hold: **here**.
- The user asks which companies are in an industry, then wants them compared:
  **industry-screen** first, then this.
- One company only: **company-brief**.

## The sequence

1. **Resolve, and the route depends on what the user gave you.**

   ⛔ **`companies_resolve_create` is for IDENTIFIERS, not names.** Its own
   description is explicit: *a name alone never returns `matched`; a name-only row
   is at best `ambiguous`, with candidates to choose from.* So batching a list of
   plain names through it guarantees every row comes back `ambiguous`, and a
   workflow that stops to ask on `ambiguous` would stall on the ordinary request
   this skill exists for.

   - **ISINs, LEIs, CIKs or tickers:** `companies_resolve_create`, one call for
     the whole list. This is what it is good at, and it beats a loop.
   - **Plain names, which is the common case:** `companies_list?search=<name>`
     per company. One call each, and the hits come back ranked.

2. **Check what you got, per company.** With identifiers, read the `status` on
   each row: `matched` and `matched_via_alias` are usable, `ambiguous` carries
   `candidates` instead of a company, and `not_covered` means we hold nothing.
   With names, a single clear hit is usable; several plausible hits mean you ask.

   Ask only when the ambiguity is real. **Do not stall a three-company comparison
   to confirm three names that each have one obvious hit**, and do not quietly
   drop a company either: resolution is the step that most often misses, every
   later step inherits the miss, and a silently two-company answer to a
   three-company question changes the result. Say which companies you could not
   pin down, and compare the ones you could.
3. **Pull the same line items for every company.**
   `companies_financials_retrieve` per company, with identical `line_items` and
   `fiscal_period`. Same arguments, every company, or the table is not a
   comparison.

   ⚠ **`line_items` takes exact snake_case codes; an unknown one is a 400.**
   `net_income_loss` and `operating_income_loss`, not `net_income` and
   `operating_profit`. Omit `line_items` if unsure, and never let one company's
   call differ from another's.
4. **Render the table with the caveats as columns**, not as a footnote.

## The table

Required columns: company, currency, `period_end_date`, then one column per
metric. Period end and currency are not optional and not a footnote.

```
| Company   | Currency | Period end  | Revenue | Operating profit | Net income |
|-----------|----------|-------------|---------|------------------|------------|
| Company A | EUR      | 2025-12-31  | 4,210   | 512              | 388        |
| Company B | SEK      | 2025-08-31  | 51,900  | 4,110            | 3,002      |
| Company C | EUR      | 2025-12-31  | 2,980   | n/a              | 221        |
```

Three things that table does right: the currencies are not mixed into one
number, the differing period ends are visible, and the missing operating profit
is `n/a` rather than `0`.

## Rules

**Never convert currencies silently.** If the user wants one currency, show the
rate and the date you used, and keep the original column. A single-currency
table with no rate shown cannot be audited and should not be produced.

**Different period ends are a finding, not a nuisance.** When one company closes
in August and another in December, a twelve-month comparison spans different
economic weather. Say it in one line above the table.

**Ratios need the same numerator and denominator everywhere.** If operating
profit is missing for one company, leave the margin blank for that company
rather than substituting a different profit measure. A column where one cell
means something else is worse than a gap.

**Missing is n/a.** Never zero, never an em-value, never silently dropped.

**Say how many you compared.** "3 of the 5 requested" with the two named is a
usable answer. A table of three with no note is not.

## Scale and provenance

Standardised line items are comparable by design, but check two things before
trusting a cross-company number:

- **As-reported values need `raw_value` together with `scale`.** Mixing a
  thousands-scaled value with a millions-scaled one produces a table that is
  wrong by a factor of a thousand and looks fine.
- **Provenance may be masked.** Where the source of a figure is not exposed, do
  not assert which filing it came from. Say the figure is standardised and leave
  the attribution out rather than inventing it.

## Pitfalls

- **Match the resolver to the input.** `companies_resolve_create` is one call and
  is the right tool for a list of ISINs, LEIs, CIKs or tickers. It is the WRONG
  tool for a list of plain names, which it can only ever return as `ambiguous`:
  loop `companies_list?search=` for those. ⚠ This pitfall used to say flatly not
  to loop `companies_list`, which contradicted step 1 and would have left an
  ordinary name-only comparison unresolved.
- **Do not compare across fiscal periods.** Same `fiscal_period` argument for
  everyone, or the table is not a comparison.
- **Do not fetch filings for figures the structured path has.** Reading five
  annual reports to build a five-company table is the expensive way to a worse
  answer.
- **Do not rank on a metric that is missing for some rows.** Rank on what every
  row has, and say what you ranked on.
