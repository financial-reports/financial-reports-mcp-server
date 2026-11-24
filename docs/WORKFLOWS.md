# FinancialReports MCP — Research Workflows

Harness-agnostic guidance for composing the 61 FinancialFilings MCP tools into the workflows analysts actually run. Any MCP-aware agent (Claude, Codex, Cursor, Kilo, opencode, Gemini CLI, Hermes, …) with this connector enabled can use this. The Claude Agent Skill at `skills/financial-filings-research/` is built around this same content; this file is the portable source so non-Claude harnesses get equal guidance.

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

## Plugin skills: the job-shaped workflows

If you use the FinancialFilings plugin for Claude, these sequences are packaged as
skills that load when the request matches, so Claude takes the right path without
being told. Each one carries the pitfalls for its job, which is the part the
table below cannot.

| Job | Skill | What it gets right that a bare tool call does not |
|---|---|---|
| A named part of one filing: risk factors, segment note, guidance, auditor's report | `filing-section-finder` | Searches **inside** the report instead of downloading it, filters to reports so newer notices cannot hide it, and quotes the passage rather than paraphrasing |
| One company: tear sheet, profile, or a results recap | `company-brief` | Takes figures from the structured path, pins the fiscal period, picks the newest annual **or** interim by release date, and carries currency and period end on every number |
| Several named companies side by side | `peer-comparison` | Routes plain names through `companies_list` rather than the batch resolver, keeps currencies and period ends as columns, and says which companies it could not resolve |
| A list of companies in an industry | `industry-screen` | Applies `listing_status=LISTED` (US ISIC 2619: 392 rows unfiltered, 81 with it), names the class code it screened on, and reports the true count rather than one page |

`financial-filings-research` is the base the four build on: company resolution,
tool order, and the provenance, as-reported and currency checks.

Measured with `claude plugin eval` against a no-plugin baseline: each skill scores
at or near 1.00 on its case where the same model without it scores near 0. See
`plugins/financialfilings/evals/README.md`.

## Tool decision table

**Check what you actually have before following a sequence below.** The hosted server exposes a curated **26** tools by default — 15 schema-derived, the 3 `get_fr_*` guide tools, and the 8 hand-written tools (`filings_search`, `filings_markdown_search`, `filings_markdown_search_batch`, `filings_markdown_outline`, `filings_search_save`, `filings_search_new`, `filings_search_saved_list`, `filings_search_saved_delete`) — plus 3 prompts (`summarize_recent_filings`, `compare_financials_yoy`, `find_filing_section`). The rest require `MCP_FULL_SURFACE=1` on the server, so on the hosted connector they are **not in your `tools/list` and calling them will fail**.

Rows marked **†** need `MCP_FULL_SURFACE=1`. If you hit one on the default surface, say so plainly rather than substituting a tool that answers a different question.

| Goal | Tool sequence |
|---|---|
| Find a company | `companies_list` (name/country filter) → `companies_retrieve` for full detail |
| Resolve many identifiers at once | `companies_resolve_create` for ISINs, LEIs, CIKs or tickers (batch; prefer over a loop). ⚠ **Not for plain names:** a name alone never returns `matched`, only `ambiguous` with candidates, so loop `companies_list?search=` for a list of names |
| Resolve an ISIN | `isins_retrieve` (ISIN → company); `isins_list` for a company's dual listings |
| Which filings or companies mention X | `filings_search` (the term plus its translations as separate queries, up to 5, plus country/type/date filters) → `filings_markdown_search` on the hits. `filings_list` matches metadata and titles, never filing text |
| Which companies mention X (a list of companies, not filings) | `filings_search` with `group_by="company"`: one row per company with its matching-filing count, first and last release date and best-matching filing, counted over the top matches by relevance (the result says when there are more: narrow the dates, countries or types to count them all). Then `filings_search` with `companies=<id>`, or `companies=<id,id,…>` for a basket, to read those companies' hits |
| Get filings | `filings_list` → `filings_retrieve` → `filings_markdown_retrieve` for content |
| Search inside a large filing | `filings_markdown_search` (don't fetch 10 MB to find one section); `filings_markdown_search_batch` for one query across a set you already hold |
| Read one section of a long filing | `filings_markdown_outline` (its headings with offsets) → `filings_markdown_retrieve` at the section's offset, instead of paging from the start; few or no headings → `filings_markdown_search` |
| Get financials | `companies_financials_retrieve` (annual or quarterly, normalized line items) |
| Predict next report | `companies_next_annual_report_retrieve` |
| Understand filing types / ISIC / fetch strategy | `get_fr_filing_type_taxonomy`, `get_fr_industry_classification_isic`, `get_fr_markdown_fetch_strategy` |
| Track filing revisions **†** | `filings_history_retrieve` (audit trail of amendments) |
| Industry screening | resolve a known peer → read its `sub_industry_code` → `companies_list?sub_industry=…` |
| Watch for new filings matching a search | `filings_search_save` once with `filings_search`'s `queries` and its `companies`, `countries`, `types`, `languages` and `release_datetime_from` / `_to` filters → `filings_search_new` on each check: it returns only filings added since the last pull, each once, including ones published long ago but added since. `filings_search_saved_list` to find a saved search's id; `filings_search_saved_delete` to stop. Don't re-run `filings_search` with a moving date: it misses filings published before your last run but added after it |
| Watch one company's filings | poll `filings_list?company=<id>&ordering=-added_to_platform` and keep the newest `added_to_platform` you have seen (see workflow 5) |
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
2. `companies_list?sub_industry=<4-digit class code>&countries=<comma-separated ISO2>&listing_status=LISTED`
   (`listing_status=LISTED` is required — US ISIC 2619 returns 392 without it, 81 with it, and the unfiltered list is dominated by companies delisted decades ago.).
3. For each result, `companies_financials_retrieve` to filter by the metric, then sort and present.

ISIC ≠ NAICS ≠ GICS. This MCP exposes ISIC; if the user asks for GICS sectors, explain the mapping is approximate.

### 5. Filings monitoring (multi-step setup)

There are no push alerts on this connector: watchlist and webhook tools are not
part of the research surface, so "email me when X files" cannot be set up here.
Say so rather than attempting it. What does work is a check the user (or their
agent) runs on a schedule:

1. **A topic or a set of filters** ("new filings mentioning a share buyback in
   Germany") → `filings_search_save` once with `filings_search`'s query and
   filters (`queries`, `companies`, `countries`, `types`, `languages`,
   `release_datetime_from` / `_to`), and keep the id it returns. Leave out
   `ordering`, `group_by` and paging: the save refuses them, because pulls come
   oldest first by when a filing was added. On each check call
   `filings_search_new(saved_search_id=…)`: it returns only the filings added
   since the previous pull, each one once. `more=true` means another pull would
   return more right now. If a response was lost, call it again with
   `repeat_last_pull=True` to get that same batch back, free.
2. **One company's filings** → `filings_list?company=<id>&ordering=-added_to_platform`,
   keeping the newest `added_to_platform` seen; next time read back to a little
   before it and skip the filing ids you already have.

Compare on `added_to_platform` (when FinancialFilings received the filing), not
`release_datetime` (when the issuer published it). A filing published last month
can arrive today, and a check keyed on `release_datetime` skips it for good.

## Common pitfalls

- **ISIN ≠ ticker.** AAPL is the ticker; US0378331005 is the ISIN. Don't conflate them in tool calls.
- **Dual listings.** Some companies have multiple ISINs; `companies_retrieve` returns the canonical entity.
- **Period types.** `companies_financials_retrieve` takes `fiscal_period` (`FY`, `H1`, `H2`, `Q1`–`Q4`, `9M`) plus `fiscal_year` / `fiscal_year_from` / `fiscal_year_to`. There is no period-type parameter — annual is `fiscal_period='FY'`, quarterly is `Q1`-`Q4`. If the user asked for "Q3", pass `fiscal_period='Q3'`; don't return the annual figure.
- **Pagination.** List endpoints cap at 100/page. For screening, tell the user the total (`count`) and that you took the top N.
- **Markdown size.** `filings_markdown_retrieve` returns pages: `limit` defaults to 50K chars, capped at 150K per call. When the response carries the truncation marker, call again with the `offset` it gives, and stop once you have the section you need. `filings_retrieve` returns the original document URL for full fidelity.
- **Account soft-gate.** If a tool returns a markdown gate response pointing at the FinancialReports site, the account needs attention — surface the link to the user and stop, don't retry-loop.

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
