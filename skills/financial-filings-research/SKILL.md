---
name: financial-filings-research
description: Use for questions about a public company's regulatory filings or financials — revenue, EBITDA, net income, debt, cash flow, 10-K/20-F/annual reports, insider transactions, peer or industry screening, or resolving a company by name, ticker, ISIN or LEI via the FinancialReports MCP connector. Carries the workflows plus the data-quality checks that the tool schemas do not express: masked provenance, as-reported vs computed figures, and the currency and magnitude checks that catch a wrong source document.
---

# Financial Filings Research

This skill teaches Claude how to combine the 16 tools the hosted FinancialReports MCP connector exposes (46 exist in the full schema; the rest are not enabled) into the workflows analysts actually run — company lookup, filings retrieval, multi-company comparison, industry screening, and ongoing monitoring.

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

For the full catalog with input parameters and gotchas see `references/tool-cheatsheet.md`.

**Check your `tools/list` before following a sequence below.** The 46 tools are the *full* schema-derived surface. The hosted server exposes a curated **16** by default — 12 schema-derived, the 3 `get_fr_*` guide tools, and `filings_markdown_search` — plus 3 prompts (`summarize_recent_filings`, `compare_financials_yoy`, `find_filing_section`). The rest require `MCP_FULL_SURFACE=1` on the server, so on the hosted connector they are **not available and calling them will fail**.

Rows marked **†** need `MCP_FULL_SURFACE=1`. If the user asks for one of those against the hosted connector, say the capability isn't exposed — don't silently substitute a tool that answers a different question.

| Goal | Tool sequence |
|---|---|
| Find a company | `companies_list` (name/country filter) → `companies_retrieve` for full detail |
| Resolve many identifiers at once | `companies_resolve_create` (batch; prefer over a loop of `companies_list`) |
| Resolve an ISIN | `isins_retrieve` (ISIN → company); `isins_list` for a company's dual listings |
| Get filings | `filings_list` → `filings_retrieve` → `filings_markdown_retrieve` for content |
| Search inside a large filing | `filings_markdown_search` (don't fetch 10 MB to find one section) |
| Get financials | `companies_financials_retrieve` (annual or quarterly, normalized line items) |
| Predict next report | `companies_next_annual_report_retrieve` |
| Understand filing types / ISIC / fetch strategy | `get_fr_filing_type_taxonomy`, `get_fr_industry_classification_isic`, `get_fr_markdown_fetch_strategy` |
| Track filing revisions **†** | `filings_history_retrieve` (audit trail of amendments) |
| Industry screening | resolve a known peer → read its `sub_industry_code` → `companies_list?sub_industry=…` |
| Watchlist **†** | `watchlist_retrieve`, `watchlist_companies_create`, `watchlist_companies_bulk_add_create` |
| Alerts setup **†** | `webhooks_create` → `webhooks_test_create` → `webhooks_deliveries_retrieve` |
| Reference data | `filing_categories_list`, `filing_types_list`; **†** `countries_list`, `languages_list`, `sources_list` |
| Line item glossary **†** | `line_item_definitions_list`, `line_item_definitions_retrieve` |

Note on ISIC: the hierarchy tools are NOT exposed on this surface, and there is no `isic_class` param or field — filter with `companies_list?sub_industry=<4-digit class code>` — and `get_fr_industry_classification_isic` is on the default surface, so a class code is still resolvable without them.

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
2. List filings → `filings_list?company=<id>&type=10-K&ordering=-release_datetime&page_size=5`.
3. For the chosen filing, get content → `filings_markdown_retrieve?id=<filing_id>`.
4. Summarize per the user's actual question (risk factors, MD&A, segment results) — don't dump the whole document.

Always cite the filing's `release_datetime` and `period_ending_date` in your summary so the user knows the vintage.

### 3. Compare financials across companies

When asked to compare net debt for `[Iberdrola, Engie, Enel, RWE]` for the latest fiscal year:

1. Resolve each company in parallel.
2. Call `companies_financials_retrieve` for each in parallel, requesting the same `fiscal_period='FY'` (and `fiscal_year`) and same `line_items`.
3. Render a table — columns: company, currency, period_end_date, value. Always show the period explicitly; mixing FY2024 and FY2023 silently is a real risk.
4. Flag missing data with "n/a" rather than zero.

Pitfall: currencies. Always show the currency next to the value, never collapse to a single number without conversion logic the user can audit.

### 4. Industry screening

When the user wants "EU utilities with revenue > €10B":

1. Get the 4-digit ISIC class code for utilities — the hierarchy tools are not exposed on this server, so resolve a known utility and read its `sub_industry_code`.
2. Call `companies_list?sub_industry=<4-digit class code>&countries=<comma-separated EU ISO2 codes>`.
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
- **Cite the source filing** for every factual claim — include `filing_type`, `release_datetime`, and a short URL fragment (filings_retrieve returns a direct URL). **Exception:** when `sources_masked` is true, `source_filing` is null and there is nothing to cite. Say the source is not exposed. Never synthesise a citation to satisfy this rule — a fabricated citation is worse than an acknowledged gap.
- **Quote currency and period explicitly** — never present a number stripped of context.
- **Use markdown bold for the user's actual answer**, not the supporting context.
- **Don't paste full filing text.** Summarize. Offer to fetch specific sections on request.

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

## Common pitfalls

- **ISIN ≠ ticker.** Apple's ticker is AAPL; its ISIN is US0378331005. Don't conflate them in tool calls.
- **Dual listings.** Some companies have multiple ISINs (e.g., a US ADR and a foreign primary). `companies_retrieve` returns the canonical entity.
- **Period types.** `companies_financials_retrieve` accepts `fiscal_period` (`FY`, `H1`, `H2`, `Q1`–`Q4`, `9M`) plus `fiscal_year` / `fiscal_year_from` / `fiscal_year_to`. There is no period-type parameter — annual is `fiscal_period='FY'`, quarterly is `Q1`-`Q4`. If the user asked for "Q3" pass `fiscal_period='Q3'`; don't return the annual figure.
- **Pagination.** Most list endpoints cap at 100 per page. For screening, explicitly tell the user how many results exist (`count` field) and that you've taken the top N.
- **Watchlist requires authentication.** `watchlist_*` and `webhooks_*` operate on the authenticated user. Anonymous calls fail.
- **Markdown size.** `filings_markdown_retrieve` is capped at 150K characters. Long 10-Ks may be truncated — `filings_retrieve` returns the original PDF URL for full-fidelity retrieval.
- **Account-status soft-gate.** All tools are free for any authenticated FinancialReports user (no paid plan required). If a tool unexpectedly returns a markdown gate response pointing at `financialreports.eu`, the user's account needs attention — surface the link to them and stop, don't retry-loop.

## Example user queries (and the workflows they trigger)

- *"Find Apple's most recent 10-K and summarize the risk factors that changed year-over-year."* → Workflow 1 + 2 (twice, with year-over-year diff).
- *"Compare net debt levels across European utilities — Iberdrola, Engie, Enel, RWE — for the latest fiscal year."* → Workflow 3.
- *"Show me insider-transaction filings at Tesla in the last 30 days."* → Workflow 2 with `type='DIRS'` filter.
- *"List EU airlines that filed annual reports in the last 6 months."* → Workflow 4 with date filter.
- *"Alert me when any company in my watchlist files an 8-K."* → Workflow 5.
- *"What's the LEI for ASML?"* → Workflow 1 (resolve via `companies_list`, return `lei` field from `companies_retrieve`).

## What this skill does NOT cover

- Real-time market data (prices, quotes, volumes) — different problem domain.
- Investment recommendations or financial advice — never produce these from filings data.
- Estimates or forecasts — the MCP returns reported figures only; analyst consensus is out of scope.

For any of those, tell the user the FinancialReports MCP doesn't provide that and stop — don't fabricate.
