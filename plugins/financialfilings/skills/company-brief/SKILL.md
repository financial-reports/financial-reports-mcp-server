---
name: company-brief
description: Use when the user wants one company summarised from its own filings: a tear sheet, company brief, profile or overview, "summarise the latest annual report", "how did they do last year", "what are their numbers", or a results recap of the most recent interim or full-year report against the prior period and the prior year. Builds the brief from the newest filing plus standardised financials, with currency and period end on every figure, and the source filing named whenever provenance is exposed.
---

# Company brief

One company, summarised from what it filed. Also covers the results recap: the
same pipeline with a period filter, which is why there is no separate skill for
it.

## When to use this rather than another skill

- One company, general summary or latest results: **here**.
- Two or more companies side by side: **peer-comparison**.
- A specific named section of one filing: **filing-section-finder**.
- "Which companies in this industry": **industry-screen**.

## The sequence

1. **Resolve.** `companies_list?search=<name>` then `companies_retrieve` for
   metadata (country, ISIN, sub-industry, listing status).
2. **Find the newest relevant filing, by RELEASE DATE across both kinds.**

   ⚠ **Filter the types BEFORE the page limit.** `filings_list` returns every
   filing type, so an unfiltered `page_size=5` can be five price-sensitive
   notices and hide the report you want. Pass the annual and interim codes
   together:
   `filings_list?company=<id>&types=<annual>,<interim>&ordering=-release_datetime&page_size=5`.
   Get the codes from `get_fr_filing_type_taxonomy`; they are FinancialFilings
   codes, not form names.

   For a full-year brief, filter to the annual report type. **For a results
   recap, take the most recently released annual OR interim report, whichever is
   newer** — not the newest interim. Just after an annual release those differ,
   and taking the newest interim would recap Q3 when the full year has been
   published. Do not assume the first row is annual.

   ⚠ **Then call `filings_retrieve` on the one you picked.** The list row does NOT
   carry `period_ending_date`: the default summary has `release_datetime`,
   `filing_type` and `source_filing_type` and nothing else about the period. The
   Source block below asks for the period end, and taking it from the structured
   financials instead risks attributing a restated period to this filing.
3. **Get the numbers from the structured path first.**
   `companies_financials_retrieve?id=<company id>` with the `line_items` you need.
   ⚠ **Pin the period, or interim figures leak into a full-year brief.** The call
   returns every period it holds, so pass `fiscal_period=FY` for a full-year
   brief and match the returned `period_end_date` to the filing you selected in
   step 2. For a recap, pass the period you are recapping.
   ⚠ **`line_items` takes exact lower-case snake_case codes and an unknown one is
   a 400 naming it.** The two most often guessed wrong are `net_income`, which is
   `net_income_loss`, and `operating_income`, which is `operating_income_loss`.
   **If you are unsure of a code, omit `line_items` entirely** and take every line
   item rather than guessing.
   This is cheaper and more consistent than reading them out of the document.
4. **Read the document only for what the numbers cannot say:** strategy, segment
   commentary, guidance, the auditor's view. Use `filings_markdown_search` for
   the specific passage rather than retrieving the whole report.
5. **For a recap, pull the comparatives** in the same call shape: the prior
   period and the same period a year earlier, so the three sit in one table.

## The structured path answers a different question from the document

`companies_financials_retrieve` selects one statement per fiscal year, period and
statement type when several filings report it. **So it may return a later
restatement rather than the figure the filing you are reading printed.**

- "What did this filing report" is a document question. Read the filing.
- "What were revenues in FY2024" is a period question. Use the structured path.

Say which one you answered. A restated figure attributed to the original filing
is a wrong citation, which is worse than a missing one.

If the structured call comes back empty, refused for the plan, or without the
line item, fall back to the document. Unavailable there is not absent.

## What a brief contains

| Block | Content |
|---|---|
| Identity | Legal name, country, ISIN, listing status, sub-industry |
| Source | The filing used: type, `release_datetime`, `period_ending_date`. ⚠ For figures from the structured path, cite `source_filing.id`, or the `sources` entry whose `is_selected` is `true`. `sources[]` can list several filings for one period when more than one reported it, so an arbitrary `filing_id` from that array can attribute a restated figure to the wrong report. When the response carries `sources_masked: true` the provenance is withheld, so say the source is not exposed rather than naming a filing you inferred |
| Headline numbers | Revenue, operating profit, net income, total assets, equity, net debt where available |
| Period comparison | Current period, prior period, same period last year |
| Narrative | Two or three sentences of segment or strategy commentary, quoted or closely paraphrased, with the passage offset |
| Gaps | Line items that are not available, named as n/a |

## Rules that make the brief trustworthy

**Every figure carries its currency and its period end.** "FY2025" spans
different twelve-month windows at different companies, and a table that hides
the period end is wrong even when every number in it is right.

**Never collapse currencies** without showing the user the rate and date you
used. Prefer reporting in the filer's own currency and saying which it is.

**As-reported figures need both `raw_value` and `scale`.** A value of 1,234 with
a thousands scale is 1.234 million. Reading one without the other is the single
easiest way to be wrong by three orders of magnitude.

**Missing is n/a, never zero.** A zero is a reported fact; absence is not.

**State the vintage up front.** A brief built on a filing from eighteen months
ago is a different artifact from one built on last week's, and the user cannot
tell from the numbers.

## Pitfalls

- **Do not fetch the whole annual report to get five numbers.** Steps 3 and 4
  exist in that order for a reason.
- **Do not present a recap without the comparatives.** "Revenue was 4.2bn" is
  not a result; "4.2bn, up from 3.9bn, against 3.6bn a year earlier" is.
- **Check `processing_status` before quoting document content.** If it is
  present and not `COMPLETED`, the text may be partial. A null value means
  unknown, so do not gate on it.
- **One filing is not the company.** If the newest filing is an interim report,
  say so rather than presenting it as the annual picture.
