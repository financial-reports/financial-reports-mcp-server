# FinancialReports MCP — Tool Cheatsheet

46 tools across 9 domains. This file is loaded on demand; the main `SKILL.md` covers the workflows. Use this when you need exact parameter names, return shapes, or pitfalls for a specific tool.

Note on surface size: only a curated subset is exposed by default (`companies_*`, `filings_*`, `isins_*`, plus the guide tools and in-filing search). The rest — ISIC, reference data, watchlists, webhooks — require `MCP_FULL_SURFACE=1` on the server. If a tool below isn't in your `tools/list`, that's why.

## Companies (6)

### `companies_list`
List public companies. **First tool to call** when resolving a name/ticker to an ID.

Key params: `search`, `countries` (comma-separated ISO-3166 alpha-2), `sector` / `industry_group` / `industry` / `sub_industry` (ISIC Section / Division / Group / Class codes), `isin`, `lei`, `ticker`, `cik`, `listing_status`, `page`, `page_size`, `ordering`.

Not parameters: country (singular) and isic_class. Use `countries`, and pass the 4-digit class code to `sub_industry`.

Returns (CompanyMinimal): `id`, `name`, `tagline`, `isins`, `lei`, `sub_industry_code`, `country_code`. The full field set (`sector`, `industry`, `sub_industry`, `ticker`, ...) comes from `companies_retrieve`.

Pitfall: `search` is fuzzy. "Apple" matches Apple Inc., Apple Hospitality REIT, etc. Inspect results, don't auto-pick.

### `companies_retrieve`
Full detail for one company. Call after `companies_list` when the user asks for metadata that's not in the list view.

Key params: `id`.

Returns (Company): the CompanyMinimal fields plus `description`, `homepage_link`, `ir_link`, `address`/`city`/`zip_code`, `country_code`, `ticker`, `sector`/`industry_group`/`industry`/`sub_industry`, `isins`/`primary_isin`, `lei`, `listing_status`/`delisting_date`, `legal_status`/`legal_form`/`jurisdiction`, `is_merged`/`merged_into`. There is no `website`, `headquarters`, or parent/subsidiary field.

### `companies_financials_retrieve`
Normalized financial line items. **outputSchema-advertised** — Claude can render structured cards.

Key params: `id` (company, path), `fiscal_period` (`FY`/`H1`/`Q1`...), `fiscal_year`, `fiscal_year_from`, `fiscal_year_to`, `statement_type` (`BS`/`IS`/`CFS`), `line_items` (comma-separated KPI codes), `as_of`.

Not parameters: period_type, from_date, to_date. Annual is `fiscal_period='FY'`; year ranges use `fiscal_year_from` / `fiscal_year_to`.

Returns: `{company_id, currency, sources_masked, filters, period_count, periods[]}`; each period carries `statements[]`, each statement `line_items[]` of `{code, name, statement_type, depth, parent_code, value, raw_value, scale, currency, source_page}`.

Pitfall: line items are normalized across regulators but currency is per-filing. Don't aggregate currencies without conversion.

### `companies_next_annual_report_retrieve`
Predicted publication date of the next annual report. Useful for monitoring setup ("when's Apple's next 10-K?").

Key params: `id`.

Returns (NextAnnualReport): `start_date`, `end_date`, `confidence`, `is_overdue`. There is no predicted_date or basis field.

### `companies_resolve_create`
Resolve many identifiers to company IDs in **one** call. Prefer this over a loop of `companies_list` calls whenever the user hands you a list — a portfolio, a screen, a spreadsheet column.

Key params: `rows` (required) — the batch of identifiers to resolve.

Returns: `{summary, results}`.

Pitfall: it is a POST only because a large batch does not fit in a query string — it creates nothing. Treat it as a read.

### `companies_merges_retrieve`
Company merge records: which shell entity was folded into which canonical company. Use it when an ID or name you were given returns nothing, or two names look like the same issuer.

Key params: none.

Returns: `id`, `shell_id`, `canonical_id`, `shell_name`, `canonical_name`, `pattern`, `confidence`, `merged_at`, `reversed_at`.

Pitfall: `reversed_at` being set means the merge was undone — do not follow `canonical_id` in that case.

## Filings (4)

### `filings_list`
List filings across companies. **outputSchema-advertised**.

Key params: `company`, `type` (one filing-type code) / `types` (comma-separated), `category` / `categories` (numeric FilingCategory ids), `countries` (comma-separated ISO2), `release_datetime_from`, `release_datetime_to`, `page_size`, `ordering`. `ordering` accepts ONLY `release_datetime`, `added_to_platform`, `id` (prefix `-` to reverse) — any other value is silently ignored and you get default order back.

Returns (FilingSummary): `{id, title, release_datetime, document_url, proxy_url, viewer_url, company, filing_type, processing_status, file_extension, file_size}`. Note `processing_status` is on THIS list response only — it is absent from `filings_retrieve`.

Pitfall: the param is `type`, not `filing_type`, and the code is jurisdiction-specific (e.g. "10-K" for US issuers vs. a local annual type). Use `filing_categories_list` to find a numeric category id, then pass `category`/`categories` for cross-jurisdiction queries — categories normalise across markets.

### `filings_retrieve`
Single filing detail. **outputSchema-advertised**.

Key params: `id`.

Returns (Filing): `id`, `company`, `filing_type`, `language`, `filing_date`, `title`, `added_to_platform`, `updated_date`, `dissemination_datetime`, `release_datetime`, `source`, `document`, `proxy_url`, `viewer_url`, `file_extension`, `file_size`, `markdown_url`, `filing_type_confidence`, `filing_type_reasoning`, `fiscal_year`, `fiscal_period`, `period_ending_date`. It is NOT a superset of the list row — notably `processing_status` is on the `filings_list` (FilingSummary) shape only. There is no `summary`, `regulator`, `pdf_url` or `markdown_available`.

### `filings_history_retrieve`
Audit trail — every revision of a filing (originals, amendments, restatements).

Key params: `id`.

Use case: "has this filing been amended?"

### `filings_markdown_retrieve`
Filing content as markdown (capped at **150K characters**).

Key params: `id`.

Pitfall: long 10-Ks (300+ pages) get truncated. For the raw file, use `document` from `filings_retrieve` (there is no pdf_url field).

## ISIC Classifications (8)

ISIC = International Standard Industrial Classification (UN). Hierarchy: section (letter) → division (2-digit) → group (3-digit) → class (4-digit).

> **None of the ISIC hierarchy endpoints below are exposed as tools on this MCP
> server** — they are all in the generator's prune list, so calling them returns
> "unknown tool". They are listed for reference only. To obtain a code, resolve a
> company you know sits in the target industry and read its `sub_industry_code`.

| API endpoint (NOT an MCP tool here) | Level | `companies_list` param |
|---|---|---|
| `isic_sections_list` / `isic_sections_retrieve` | Top level (A–U) | `sector` |
| `isic_divisions_list` / `isic_divisions_retrieve` | 2-digit (e.g., 35 = Electricity, gas) | `industry_group` |
| `isic_groups_list` / `isic_groups_retrieve` | 3-digit | `industry` |
| `isic_classes_list` / `isic_classes_retrieve` | 4-digit (most specific) | `sub_industry` |

## ISINs (2)

### `isins_list`
**outputSchema-advertised.** All ISINs for a company (handles dual-listings).

Key params: `company`, `code`, `codes`, `is_primary`, `search`, `page`, `page_size`.

Not a parameter: country.

### `isins_retrieve`
ISIN → company lookup.

Key params: `code` (12-char ISIN, path).

Not a parameter: isin — the path parameter is `code`.

Returns (ISIN): `code`, `is_primary`, `company`, `figi`, `composite_figi`, `share_class_figi`, `security_type`, `security_type2`, `market_sector`, `exch_code`, `figi_last_updated`.

Pitfall: not every ISIN is in our index. If `isins_retrieve` 404s, fall back to `companies_list?search=`.

## Security Listings (2)

Where a company's shares actually trade. Use these when the user asks about a **ticker on a specific exchange** — ISINs identify the security, listings identify the venue.

### `security_listings_list`
Exchange + ticker per company, with FIGI identifiers.

Key params: `company`, `ticker`, `mic` (ISO-10383 market code), `exch_code`, `figi`, `page`, `page_size`, `ordering`.

Returns: `id`, `company`, `mic`, `ticker`, `exch_code`, `exchange_name`, `security_type`, `market_sector`, `figi`, `composite_figi`, `share_class_figi`.

Pitfall: one company has many listings, and the same `ticker` string is reused across exchanges (`BMW` on XETR is not `BMW` elsewhere). Always pair a ticker with `mic` or `exch_code` before treating it as unique.

### `security_listings_retrieve`
One listing by id.

Key params: `id`.

Returns: the same `SecurityListing` item as `security_listings_list` — `id`, `company`, `mic`, `ticker`, `exch_code`, `exchange_name`, `security_type`, `market_sector`, `figi`, `composite_figi`, `share_class_figi`. So if you already have the row from a list call, you do not need this.

## Reference Data (8)

Lookups for filtering and labeling. All have `_list` and `_retrieve` variants.

| Tool | Returns |
|---|---|
| `countries_list` / `countries_retrieve` | ISO-3166 country metadata |
| `filing_categories_list` / `filing_categories_retrieve` | Cross-jurisdiction categories (annual_report, insider_transaction, etc.) |
| `filing_types_list` / `filing_types_retrieve` | Jurisdiction-specific types (10-K, DEF 14A, AR-Form, etc.) |
| `languages_list` / `languages_retrieve` | ISO-639 language codes for filings |
| `sources_list` / `sources_retrieve` | Source regulators (the canonical list is returned by the API; treat the response as authoritative rather than hardcoding regulator names) |

Use these for **labeling**, not lookup. Don't call `countries_list` to find country IDs — `companies_list?countries=US` accepts ISO codes directly (note the plural; there is no `country` param).

## Line Item Definitions (2)

### `line_item_definitions_list`
All normalized financial line items with formal definitions.

Use when the user asks "what does 'EBITDA' mean in this dataset?" or "what line items can I query?"

### `line_item_definitions_retrieve`
Single line item by name.

## Watchlist (4)

Per-user, requires authenticated session.

| Tool | Hint |
|---|---|
| `watchlist_retrieve` | `readOnlyHint=true` — current contents |
| `watchlist_companies_create` | `destructiveHint=true` — add one company |
| `watchlist_companies_bulk_add_create` | `destructiveHint=true` — add many at once (preferred for >3 companies) |
| `watchlist_companies_bulk_remove_create` | `destructiveHint=true` — remove many |

Pitfall: bulk operations take a list of company IDs, not names. Resolve first.

## Webhooks (8)

For programmatic alerts. Per-user, requires authenticated session.

| Tool | Hint |
|---|---|
| `webhooks_list` / `webhooks_retrieve` | `readOnlyHint=true` |
| `webhooks_deliveries_retrieve` / `webhooks_delivery_detail_retrieve` | `readOnlyHint=true` — inspect past deliveries |
| `webhooks_create` | `destructiveHint=true` — register a new endpoint |
| `webhooks_regenerate_secret_create` | `destructiveHint=true` — rotate signing secret |
| `webhooks_test_create` | open-world probe (non-destructive) — "send me a test event" |
| `webhooks_deliveries_replay_create` | open-world probe — re-fire a past delivery |

### Webhook setup pattern

1. `webhooks_create` with `target_url`, `event_types`, `filters`. Capture the returned `secret`.
2. Immediately `webhooks_test_create` to verify the user's endpoint accepts and signs requests.
3. Tell the user the secret value once — we don't store it cleartext server-side.

Pitfall: `event_types` is restrictive (e.g., `filing.published`, `watchlist.changed`). Don't invent event names — call `webhooks_list` on an existing webhook to see valid values, or check the docs at https://financialreports.eu/integrations/claude/.

## Tool annotation summary

- 35 tools have `readOnlyHint=true` (safe to call without confirmation).
- 5 tools have `destructiveHint=true` (mutations: watchlist add/remove, webhook create, secret rotation).
- 2 tools are non-destructive probes (`webhooks_test_create`, `webhooks_deliveries_replay_create`) — they hit the user's external endpoint but don't mutate FinancialReports state.
- 6 tools advertise `outputSchema` for structured rendering: `companies_list`, `companies_retrieve`, `companies_financials_retrieve`, `filings_list`, `filings_retrieve`, `isins_list`.

## Authentication

All tools require an authenticated session via Cognito OAuth (handled by the MCP server). Anonymous calls fail with 401. **The connector is free** — any FinancialReports account (paid or free) has access. Tools may soft-gate on rare account-status conditions (banned, deactivated); when that happens the response is a markdown link pointing the user back to their dashboard.
