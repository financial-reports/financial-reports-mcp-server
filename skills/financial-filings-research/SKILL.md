---
name: financial-filings-research
description: Use for questions about a public company's regulatory filings or financials — revenue, EBITDA, net income, debt, cash flow, 10-K/20-F/annual reports, insider transactions, peer or industry screening, or resolving a company by name, ticker, ISIN or LEI via the FinancialReports MCP connector. Carries the workflows plus the data-quality checks that the tool schemas do not express: masked provenance, as-reported vs computed figures, and the currency and magnitude checks that catch a wrong source document.
---

# Financial Filings Research

Workflows for the FinancialReports MCP connector: company lookup, filings
retrieval, financial comparison, industry screening.

The connector is the data layer. This skill is the workflow layer.

## When to use

A named public company, a filing (10-K, 20-F, annual/quarterly report, insider
transaction, ESG), a financial line item, or industry/peer screening.

Not for market data — prices, quotes, volumes are a different domain.

## Tools

The connector exposes **16 research tools**. Administrative, reference and
webhook-management endpoints are not part of the research surface — if you need
one, say so rather than substituting a tool that answers a different question.
Full parameters in `references/tool-cheatsheet.md`.

| Goal | Sequence |
|---|---|
| Find a company | `companies_list` (search) → `companies_retrieve` for detail |
| Resolve many identifiers | `companies_resolve_create` (batch; beats a loop) |
| ISIN → company | `isins_retrieve`; `isins_list` for dual listings |
| Get filings | `filings_list` → `filings_retrieve` → `filings_markdown_retrieve` |
| Search inside a filing | `filings_markdown_search` |
| Financials | `companies_financials_retrieve` |
| Next report due | `companies_next_annual_report_retrieve` |
| Filing types / ISIC / fetch strategy | `get_fr_filing_type_taxonomy`, `get_fr_industry_classification_isic`, `get_fr_markdown_fetch_strategy` |
| Industry screening | resolve a known peer → read its `sub_industry_code` → `companies_list?sub_industry=…` |

ISIC note: there is no `isic_class` parameter. Filter with
`companies_list?sub_industry=<4-digit class code>`.

## Workflows

### 1. Resolve a company

ISIN → `isins_retrieve`. Name or ticker → `companies_list?search=`. If several
match, ask the user rather than picking — companies dual-list under different
ISINs. Then `companies_retrieve` for full metadata.

Don't paginate past page 2 hunting for a match; refine the search instead.

### 2. Retrieve and summarise a filing

`companies_list?search=` → `filings_list?company=<id>&type=10-K&ordering=-release_datetime&page_size=5`
→ `filings_markdown_retrieve`.

Summarise against the actual question; don't dump the document. Always cite
`release_datetime` and `period_ending_date` so the vintage is explicit.

### 3. Compare financials across companies

Resolve each company, then call `companies_financials_retrieve` for each with the
same `fiscal_period` and `line_items`.

Render a table with company, currency and `period_end_date` as columns. **Period
end is not optional** — "FY2025" covers different twelve-month windows at
different companies, and a table that hides that is wrong. Mark missing data
"n/a", never zero. Never collapse currencies without conversion the user can audit.

### 4. Industry screening

1. Get the 4-digit ISIC class: resolve a known peer, read its `sub_industry_code`.
2. `companies_list?sub_industry=<code>&countries=<ISO2>&listing_status=LISTED`

**`listing_status=LISTED` is required, not optional.** Without it the result is
dominated by long-dead registrations — US ISIC 2619 returns 392 companies
unfiltered and 81 with the filter, and the unfiltered list sorts alphabetically
into companies delisted in the 1990s.

3. `companies_financials_retrieve` per result to filter by metric.
4. When pulling filing content, prefer rows whose `processing_status` is
   `COMPLETED`.

ISIC is not GICS or NAICS. If the user asks in GICS terms, say the mapping is
approximate.

### 5. Monitoring and alerts

**Not available on this connector.** Watchlist and webhook tools are not part of
the research surface, so "alert me when X files" cannot be set up here. Say so.

The workable alternative is polling: `filings_list?company=<id>&ordering=-release_datetime`
on a schedule the user runs, comparing against the last `release_datetime` seen.

## Data-quality checks

Financial statement data is assembled from filed documents, and a few properties
of that process are not visible in the tool schemas. Check these before reporting
a figure.

### Provenance may not be exposed

`companies_financials_retrieve` returns `sources_masked: true` on many accounts,
and `source_filing` is then null. When that happens you cannot identify the
document behind a figure — say so rather than implying the number is traceable.

### "As-reported" requires both `raw_value` and `scale`

If either is null there is no as-reported pair, so the figure cannot be
attributed to a printed line in the document. Note that an arithmetic tie
between totals does not establish provenance either: a derived figure is
computed so the totals balance, so it will always tie.

### Confirm the reporting entity and the period

Two quick checks against the data you already have:

- **Currency.** If one period's statement currency differs from the company's
  other periods, it is likely a different reporting entity (a subsidiary rather
  than the listed parent). Do not compute growth across such a break.
- **Magnitude.** If one year is far out of line with **both** neighbouring
  years, confirm it before using it — that pattern usually means a different
  document, not a real collapse.

These are validation signals rather than proof. When one trips, confirm the
entity and period against the filing, report the figure you read there, and tell
the user what you found. Genuine volatility exists; an order-of-magnitude gap or
a currency change is what warrants a second look.

### `processing_status` is absent under `view='full'`

`view='full'` returns more fields but omits `processing_status`. Don't gate
filing selection on it there — read it from the default view, or proceed
without it.

### An unknown filing-type code returns zero rows

`filings_list` with an unrecognised `type` returns `count=0`, which looks
identical to a genuine empty result. Verify the code with `filing_types_list`
before telling the user a company has no such filings.

## Output

- Tables for comparisons; units in headers, not cells.
- Cite the source filing per claim — `filing_type`, `release_datetime`, and the
  URL from `filings_retrieve`. **Exception:** when `sources_masked` is true there
  is no filing to cite. Say the source is not exposed; never synthesise a
  citation.
- Always state currency and period alongside a figure.
- Don't paste full filing text. Summarise, and offer specific sections.

## Pitfalls

- **ISIN is not a ticker.** Apple: ticker AAPL, ISIN US0378331005.
- **Dual listings.** Several ISINs per company; `companies_retrieve` gives the canonical entity.
- **Periods.** `fiscal_period` is `FY`, `H1`, `H2`, `Q1`–`Q4`, `9M`, plus
  `fiscal_year` / `_from` / `_to`. There is no period-type parameter — annual is
  `FY`. If asked for Q3, pass `Q3`.
- **Pagination.** List endpoints cap at 100/page. State the `count` and how many you took.
- **Markdown size.** `filings_markdown_retrieve` caps at 150k characters; long
  filings truncate. `filings_retrieve` returns the original document URL.
- **Account status.** If a tool returns a gate response pointing at the
  FinancialReports site, the account needs attention — surface the link and stop.
  Don't retry-loop.

## Out of scope

Market data, investment advice, and estimates or forecasts. The connector returns
reported figures only. Say so rather than fabricating.
