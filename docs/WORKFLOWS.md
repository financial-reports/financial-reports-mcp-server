# FinancialReports MCP — Research Workflows

Harness-agnostic guidance for composing the 46 FinancialReports MCP tools into the workflows analysts actually run. Any MCP-aware agent (Claude, Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, …) with this connector enabled can use this. The Claude Agent Skill at `skills/financial-filings-research/` is built around this same content; this file is the portable source so non-Claude harnesses get equal guidance.

The MCP server is the **data layer**. This document is the **workflow layer**.

## When this applies

Use these tools when the user mentions:

- **A specific public company** — by name (Apple), ticker (AAPL), or ISIN (US0378331005)
- **A regulatory filing** — 10-K, 10-Q, annual/quarterly report, prospectus, ad-hoc disclosure, insider transaction, ESG report
- **Financial line items** — revenue, EBITDA, net income, total debt, cash flow, segment data
- **Industry analysis** — sector screening, peer comparison, ISIC classification
- **Monitoring intent** — "alert me when…", "watch this company", "track new filings"
- **Comparison intent** — "compare X vs Y", "rank these by…"

Not for market data (prices, volumes, options) — this server doesn't provide it.

## Tool decision table

**Check what you actually have before following a sequence below.** The 46 tools are the *full* schema-derived surface. The hosted server exposes a curated **16** by default — 12 schema-derived, the 3 `get_fr_*` guide tools, and `filings_markdown_search` — plus 3 prompts (`summarize_recent_filings`, `compare_financials_yoy`, `find_filing_section`). The rest require `MCP_FULL_SURFACE=1` on the server, so on the hosted connector they are **not in your `tools/list` and calling them will fail**.

Rows marked **†** need `MCP_FULL_SURFACE=1`. If you hit one on the default surface, say so plainly rather than substituting a tool that answers a different question.

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
| Industry screening **†** | resolve a known peer → read its `sub_industry_code` → `companies_list?sub_industry=…` |
| Watchlist **†** | `watchlist_retrieve`, `watchlist_companies_create`, `watchlist_companies_bulk_add_create` |
| Alerts setup **†** | `webhooks_create` → `webhooks_test_create` → `webhooks_deliveries_retrieve` |
| Reference data | `filing_categories_list`, `filing_types_list`; **†** `countries_list`, `languages_list`, `sources_list` |
| Line item glossary **†** | `line_item_definitions_list`, `line_item_definitions_retrieve` |

Note on ISIC: the hierarchy tools are NOT exposed on this surface, and there is no `isic_class` param or field — filter with `companies_list?sub_industry=<4-digit class code>` — and `get_fr_industry_classification_isic` is on the default surface, so you can still resolve a class code without the hierarchy tools.

## Workflows

### 1. Look up a company

Always resolve to a canonical company ID before calling per-company tools.

1. ISIN given → `isins_retrieve` directly.
2. Name or ticker given → `companies_list` with `search=<query>`. If multiple results, ask the user to disambiguate (companies can be dual-listed under different ISINs).
3. Once you have the ID, optionally `companies_retrieve` for full metadata (LEI, country, ISIC class, primary listing).

Don't paginate `companies_list` past page 2 to find a match — refine the search query instead.

### 2. Retrieve and summarize a filing

1. Resolve company → `companies_list?search=Apple` → pick the correct entity (parent vs subsidiary).
2. List filings → `filings_list?company=<id>&type=10-K&ordering=-release_datetime&page_size=5`.
3. Get content → `filings_markdown_retrieve?id=<filing_id>`.
4. Summarize per the user's actual question (risk factors, MD&A, segment results) — don't dump the whole document.

Always cite the filing's `release_datetime` and `period_ending_date` so the user knows the vintage.

### 3. Compare financials across companies

1. Resolve each company in parallel.
2. Call `companies_financials_retrieve` for each in parallel, with the same `fiscal_period` (and `fiscal_year`) and same `line_items`.
3. Render a table: company, currency, period_end_date, value. Always show the period explicitly — silently mixing FY2024 and FY2023 is a real risk.
4. Flag missing data as "n/a", never zero. Always show currency next to the value.

### 4. Industry screening

1. Get the 4-digit ISIC class code — the hierarchy tools are not exposed on this server, so resolve a company you know is in the industry and read its `sub_industry_code`.
2. `companies_list?sub_industry=<4-digit class code>&countries=<comma-separated ISO2>`.
3. For each result, `companies_financials_retrieve` to filter by the metric, then sort and present.

ISIC ≠ NAICS ≠ GICS. This MCP exposes ISIC; if the user asks for GICS sectors, explain the mapping is approximate.

### 5. Filings monitoring (multi-step setup)

1. Build the watchlist via `watchlist_companies_bulk_add_create` (one call, list of IDs).
2. `webhooks_create` with the user's endpoint + filter (`event_types=["filing.published"]`, `filing_types=["8-K"]`).
3. `webhooks_test_create` to verify the endpoint accepts deliveries.
4. Save the secret (`webhooks_regenerate_secret_create` if rotation needed).
5. Deliveries inspected via `webhooks_deliveries_retrieve`, replayed via `webhooks_deliveries_replay_create`.

## Common pitfalls

- **ISIN ≠ ticker.** AAPL is the ticker; US0378331005 is the ISIN. Don't conflate them in tool calls.
- **Dual listings.** Some companies have multiple ISINs; `companies_retrieve` returns the canonical entity.
- **Period types.** `companies_financials_retrieve` takes `fiscal_period` (`FY`, `H1`, `H2`, `Q1`–`Q4`, `9M`) plus `fiscal_year` / `fiscal_year_from` / `fiscal_year_to`. There is no period-type parameter — annual is `fiscal_period='FY'`, quarterly is `Q1`-`Q4`. If the user asked for "Q3", pass `fiscal_period='Q3'`; don't return the annual figure.
- **Pagination.** List endpoints cap at 100/page. For screening, tell the user the total (`count`) and that you took the top N.
- **Auth-scoped tools.** `watchlist_*` and `webhooks_*` operate on the authenticated user; anonymous calls fail.
- **Markdown size.** `filings_markdown_retrieve` caps at 150K chars; long 10-Ks may truncate — `filings_retrieve` returns the original PDF URL for full fidelity.
- **Account soft-gate.** All tools are free for any authenticated FinancialReports account. If a tool returns a markdown gate response pointing at `financialreports.eu`, surface the link to the user and stop — don't retry-loop.

## Output formatting

- Tables for comparisons, with units in headers not cells.
- Cite the source filing for every factual claim (`filing_type`, `release_datetime`, and the direct URL from `filings_retrieve`).
- Quote currency and period explicitly — never a number stripped of context.
- Don't paste full filing text; summarize and offer to fetch specific sections.

## Out of scope

- Real-time market data (prices, quotes, volumes).
- Investment recommendations or financial advice — never produce these from filings data.
- Estimates or forecasts — the MCP returns reported figures only.

For any of those, tell the user the FinancialReports MCP doesn't provide it and stop — don't fabricate.
