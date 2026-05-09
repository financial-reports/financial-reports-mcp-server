---
name: financial-filings-research
description: Research public companies' regulatory filings, financial data, and industry context using the FinancialReports MCP server. Use when the user mentions a listed company by name, ticker, or ISIN, asks about 10-Ks, 10-Qs, annual or quarterly reports, financial statements (revenue, EBITDA, debt, cash flow), insider transactions, ESG disclosures, or wants to compare companies, screen by industry (ISIC), or set up filings alerts. Covers SEC, ESMA, AMF, BaFin, AFM, CMVM, and other global regulators.
---

# Financial Filings Research

This skill teaches Claude how to combine the 43 tools exposed by the FinancialReports MCP server into the workflows analysts actually run — company lookup, filings retrieval, multi-company comparison, industry screening, and ongoing monitoring.

The MCP server is the data layer. This skill is the workflow layer.

## When to use

Activate when the user mentions any of:

- **A specific public company** — by name (Apple), ticker (AAPL), or ISIN (US0378331005)
- **A regulatory filing** — 10-K, 10-Q, annual report, quarterly report, prospectus, ad-hoc disclosure, insider transaction, ESG report
- **Financial line items** — revenue, EBITDA, net income, total debt, cash flow, working capital, segment data
- **Industry analysis** — sector screening, peer comparison, ISIC classification
- **Monitoring intent** — "alert me when…", "watch this company", "track new filings"
- **Comparison intent** — "compare X vs Y", "rank these companies by…"

Skip when the user is asking about market data (prices, volumes, options) — that's not what this server provides.

## Tool reference

For the full catalog with input parameters and gotchas see `references/tool-cheatsheet.md`. Quick decision table:

| Goal | Tool sequence |
|---|---|
| Find a company | `companies_list` (name/country filter) → `companies_retrieve` for full detail |
| Resolve an ISIN | `isins_retrieve` (ISIN → company) |
| Get filings | `filings_list` → `filings_retrieve` → `filings_markdown_retrieve` for content |
| Track filing revisions | `filings_history_retrieve` (audit trail of amendments) |
| See what just landed | `filings_live_pulse_retrieve` (most recent across all companies) |
| Get financials | `companies_financials_retrieve` (annual or quarterly, normalized line items) |
| Predict next report | `companies_next_annual_report_retrieve` |
| Industry screening | `isic_sections_list` → `isic_classes_list` → `companies_list?isic_class=…` |
| Watchlist | `watchlist_retrieve`, `watchlist_companies_create`, `watchlist_companies_bulk_add_create` |
| Alerts setup | `webhooks_create` → `webhooks_test_create` → `webhooks_deliveries_retrieve` |
| Reference data | `countries_list`, `filing_categories_list`, `filing_types_list`, `languages_list`, `sources_list` |
| Line item glossary | `line_item_definitions_list`, `line_item_definitions_retrieve` |

## Workflows

### 1. Look up a company

Always resolve to a canonical company ID before calling per-company tools.

1. If the user gives an **ISIN**, call `isins_retrieve` directly.
2. If the user gives a **name or ticker**, call `companies_list` with `search=<query>`. If multiple results, ask the user to disambiguate (companies can be dual-listed under different ISINs).
3. Once you have the company ID, optionally call `companies_retrieve` for full metadata (LEI, country, ISIC class, primary listing).

Pitfall: don't paginate `companies_list` past page 2 just to find a match — refine the search query instead.

### 2. Retrieve and summarize a filing

When the user asks "show me Apple's most recent 10-K":

1. Resolve company → `companies_list?search=Apple` → pick correct entity (parent vs subsidiary).
2. List filings → `filings_list?company=<id>&filing_type=10-K&ordering=-publication_date&limit=5`.
3. For the chosen filing, get content → `filings_markdown_retrieve?id=<filing_id>`.
4. Summarize per the user's actual question (risk factors, MD&A, segment results) — don't dump the whole document.

Always cite the filing's `publication_date` and `period_end_date` in your summary so the user knows the vintage.

### 3. Compare financials across companies

When asked to compare net debt for `[Iberdrola, Engie, Enel, RWE]` for the latest fiscal year:

1. Resolve each company in parallel.
2. Call `companies_financials_retrieve` for each in parallel, requesting the same `period_type=annual` and same line items.
3. Render a table — columns: company, currency, period_end_date, value. Always show the period explicitly; mixing FY2024 and FY2023 silently is a real risk.
4. Flag missing data with "n/a" rather than zero.

Pitfall: currencies. Always show the currency next to the value, never collapse to a single number without conversion logic the user can audit.

### 4. Industry screening

When the user wants "EU utilities with revenue > €10B":

1. Get the ISIC class for utilities → `isic_sections_list` → drill down to `isic_classes_list?division=…`.
2. Call `companies_list?isic_class=<id>&country=<EU country list>`.
3. For each result, call `companies_financials_retrieve` to filter by the metric.
4. Sort and present.

Pitfall: ISIC vs NAICS vs GICS — these are different taxonomies. The MCP exposes ISIC. If the user asks for GICS sectors, explain the mapping is approximate.

### 5. Filings monitoring (multi-step setup)

When the user wants "alert me when any S&P 100 company files an 8-K":

1. Build the watchlist via `watchlist_companies_bulk_add_create` (one call, list of company IDs).
2. Create a webhook → `webhooks_create` with the user's endpoint + filter (`event_types=["filing.published"]`, `filing_types=["8-K"]`).
3. Test → `webhooks_test_create` to verify the user's endpoint accepts deliveries.
4. Save the webhook secret (`webhooks_regenerate_secret_create` if rotation needed).
5. Tell the user: deliveries can be inspected via `webhooks_deliveries_retrieve`, and individual ones replayed via `webhooks_deliveries_replay_create`.

## Output formatting

- **Tables for comparisons.** Markdown tables with units in headers, not in cells.
- **Cite the source filing** for every factual claim — include `filing_type`, `publication_date`, and a short URL fragment (filings_retrieve returns a direct URL).
- **Quote currency and period explicitly** — never present a number stripped of context.
- **Use markdown bold for the user's actual answer**, not the supporting context.
- **Don't paste full filing text.** Summarize. Offer to fetch specific sections on request.

## Common pitfalls

- **ISIN ≠ ticker.** Apple's ticker is AAPL; its ISIN is US0378331005. Don't conflate them in tool calls.
- **Dual listings.** Some companies have multiple ISINs (e.g., a US ADR and a foreign primary). `companies_retrieve` returns the canonical entity.
- **Period types.** `companies_financials_retrieve` accepts `period_type=annual` or `quarterly`; if the user asked for "Q3" don't return the annual figure.
- **Pagination.** Most list endpoints cap at 100 per page. For screening, explicitly tell the user how many results exist (`count` field) and that you've taken the top N.
- **Watchlist requires authentication.** `watchlist_*` and `webhooks_*` operate on the authenticated user. Anonymous calls fail.
- **Markdown size.** `filings_markdown_retrieve` is capped at 150K characters. Long 10-Ks may be truncated — `filings_retrieve` returns the original PDF URL for full-fidelity retrieval.
- **Free-tier vs paid.** Some tools soft-gate on subscription tier. If you get a markdown upgrade-link response, surface it to the user without retry-looping.

## Example user queries (and the workflows they trigger)

- *"Find Apple's most recent 10-K and summarize the risk factors that changed year-over-year."* → Workflow 1 + 2 (twice, with year-over-year diff).
- *"Compare net debt levels across European utilities — Iberdrola, Engie, Enel, RWE — for the latest fiscal year."* → Workflow 3.
- *"Show me insider-transaction filings at Tesla in the last 30 days."* → Workflow 2 with `filing_category=insider_transaction` filter.
- *"List EU airlines that filed annual reports in the last 6 months."* → Workflow 4 with date filter.
- *"Alert me when any company in my watchlist files an 8-K."* → Workflow 5.
- *"What's the LEI for ASML?"* → Workflow 1 (resolve via `companies_list`, return `lei` field from `companies_retrieve`).

## What this skill does NOT cover

- Real-time market data (prices, quotes, volumes) — different problem domain.
- Investment recommendations or financial advice — never produce these from filings data.
- Estimates or forecasts — the MCP returns reported figures only; analyst consensus is out of scope.

For any of those, tell the user the FinancialReports MCP doesn't provide that and stop — don't fabricate.
