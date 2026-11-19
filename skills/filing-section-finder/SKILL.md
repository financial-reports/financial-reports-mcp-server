---
name: filing-section-finder
description: Use when the user wants a specific named part of one company's filing rather than a summary of the whole thing: risk factors, the segment note, guidance or outlook, the auditor's report or opinion, related-party transactions, subsequent events, going concern, revenue recognition policy, remuneration, dividend policy, or "where does the filing say", "find the section on", "what does the 20-F say about", "quote the passage". Searches inside the document and returns the passage with its character offset and a source link, instead of downloading the whole report.
---

# Find a section in a filing

The highest-volume job on this connector, and the one most often done the
expensive way. The wrong way is to fetch the whole document and read it; the
right way is to search inside it and fetch only the part you need.

## When to use this rather than the base skill

Use this when the user names a **part** of a filing. If they want the whole
document summarised, or a figure that lives in the financial statements, that is
the company-brief skill or `companies_financials_retrieve` instead.

## The sequence

1. **Resolve the company.** `companies_list?search=<name>` then take the `id`.
   If several match, ask rather than guess. Companies dual-list.
2. **Find the filing.**
   `filings_list?company=<id>&types=<codes>&ordering=-release_datetime&page_size=5`.

   ⚠ **Filter the types BEFORE the page limit, including when the user named no
   report.** `filings_list` returns every type, so an unfiltered `page_size=5`
   can be five price-sensitive notices and hide the report entirely. **The
   sections this skill finds live in REPORTS, not in notices**: there is no risk
   factors section in a two-paragraph announcement, so filter to the annual and
   interim codes by default. "Find X's risk factors" names no type and still
   wants a report.

   ⚠ **The auditor's report is the exception that cuts the other way.** It is often
   filed as its own document under the `AR` code, which is AUDIT REPORT in this
   taxonomy, not annual report. For an auditor's report or audit opinion, include
   `AR` alongside the annual codes, and check the row you pick is the report
   itself before quoting it.

   The other exception is a user who asks about an announcement or a press release.
   Then pass those codes instead, or drop the filter, because a report filter
   would hide exactly what they asked for.

   **`type` takes a FinancialFilings code, not a form name.** `20-F`, `10-Q` and
   `S-1` are source form names and are rejected with a 400. Call
   `get_fr_filing_type_taxonomy` to translate what the user said, then filter on
   the code it gives you, and confirm `source_filing_type` on the row you pick,
   because one code covers several national annual-report forms.

   ⚠ **The list row does NOT carry `period_ending_date`.** The default summary has
   `release_datetime`, `filing_type`, `processing_status` and `source_filing_type`,
   and nothing else about the period. To state the period end, call
   `filings_retrieve` on the filing you chose, which is one call and worth it
   because the period end is the figure a reader uses to judge the vintage.
3. **Search inside it.** `filings_markdown_search?filing_id=<id>&query=<phrase>`.
   This returns matching passages with a character `offset` and the exact total
   number of matches in the document.
4. **Widen only if needed.** `filings_markdown_retrieve` with the `offset` from
   step 3 reads the surrounding window. Use it to quote in context, not to read
   the report.

Across several filings of the same company, use
`filings_markdown_search_batch` with up to 50 filing ids in one call. It is the
same matcher and it bills only filings that actually match.

## Choosing the search phrase

**Quote the phrase as the filing reads, not as the page is laid out.** A phrase
of two or more words also matches where the document conversion split it across
lines, table cells or pages, or ran its words together, so you do not need to
guess the typography.

Section headings are the strongest queries, because filings are formulaic:

| User asks for | Try these phrases, in order |
|---|---|
| Risk factors | `Risk Factors`, `Principal Risks`, `Risk Management` |
| Segment note | `Segment Information`, `Operating Segments`, `Segment Reporting` |
| Guidance / outlook | `Outlook`, `Guidance`, `Expectations for`, `Financial Targets` |
| Auditor's report | `Independent Auditor`, `Basis for Opinion`, `Key Audit Matters` |
| Related parties | `Related Party`, `Related Parties` |
| Subsequent events | `Subsequent Events`, `Events After the Reporting Period` |
| Going concern | `Going Concern` |
| Remuneration | `Remuneration Report`, `Directors' Remuneration`, `Compensation` |
| Dividend policy | `Dividend Policy`, `Proposed Dividend`, `Distribution` |

If the first phrase returns nothing, try the next synonym before concluding the
section is absent. Different jurisdictions title the same section differently.

## Reading the result honestly

**A no-match result is a real absence, and the other outcomes are not.** The
search reads the whole document, so "no match" means the phrase is not in it.
But a filing can also come back unavailable (we could not read it) or not
searched (it was dropped from the request). Those two mean unknown. Never report
them as "the filing does not discuss this".

With the batch tool, each filing carries its own outcome. Report per filing, and
retry the ones marked not searched rather than treating them as empty.

## What to return

- The passage, quoted, long enough to stand on its own.
- `release_datetime` and `period_ending_date`, so the vintage is explicit.
- The character offset, so the user or a later call can go back to it.
- The filing's source link when one is available.
- How many matches exist in total, when more than one. The count is exact, so
  say "7 matches, here are the first 3", never "several".

Do not paraphrase a risk factor or an audit opinion. Quote it. These are
documents whose wording is the substance.

⛔ **Do not guess at what the unshown matches say.** When the search reports more
matches than it returned, say how many there are and offer to read them, by
offset or with a narrower phrase. Do not fill the gap with categories the section
"probably" covers, such as market, regulatory, currency or cyber risk. Those are the risks most
filings have, which is exactly why naming them sounds right and attributes to
this company something nobody has read. Same rule as anywhere else in these
skills: a fact the tools have not supplied is not yours to supply.

## Pitfalls

- **Do not fetch the document first.** A large annual report is megabytes, and
  the search endpoint returns the same passage for a fraction of the cost.
- **Do not search the corpus when the user named one company.** `filings_search`
  searches every filing; it answers "which filings mention X", not "where in
  this filing".
- **Section numbers are not note numbers.** There are no stable note numbers
  across filers, so cite the heading text, not "Note 14".
- **A nil return from one phrasing is not an absence.** See the synonym table.
