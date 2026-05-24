# FinancialReports MCP — Tool Cheatsheet

42 tools across 8 domains. This file is loaded on demand; the main `SKILL.md` covers the workflows. Use this when you need exact parameter names, return shapes, or pitfalls for a specific tool.

## Companies (4)

### `companies_list`
List public companies. **First tool to call** when resolving a name/ticker to an ID.

Key params: `search`, `country` (ISO-3166), `isic_class`, `page`, `page_size` (max 100), `ordering`.

Returns: paginated list with `id`, `name`, `legal_name`, `isin_primary`, `country`, `isic_class`, `lei`.

Pitfall: `search` is fuzzy. "Apple" matches Apple Inc., Apple Hospitality REIT, etc. Inspect results, don't auto-pick.

### `companies_retrieve`
Full detail for one company. Call after `companies_list` when the user asks for metadata that's not in the list view.

Key params: `id`.

Returns: everything from `companies_list` + `lei`, `description`, `website`, `headquarters`, parent/subsidiary relationships.

### `companies_financials_retrieve`
Normalized financial line items. **outputSchema-advertised** — Claude can render structured cards.

Key params: `id` (company), `period_type` (`annual` | `quarterly`), `from_date`, `to_date`, `line_items` (list).

Returns: time series of `{period_end_date, currency, line_item, value}`.

Pitfall: line items are normalized across regulators but currency is per-filing. Don't aggregate currencies without conversion.

### `companies_next_annual_report_retrieve`
Predicted publication date of the next annual report. Useful for monitoring setup ("when's Apple's next 10-K?").

Key params: `id`.

Returns: `{predicted_date, confidence, basis}`.

## Filings (4)

### `filings_list`
List filings across companies. **outputSchema-advertised**.

Key params: `company`, `filing_type`, `filing_category`, `country`, `from_date`, `to_date`, `ordering` (default `-publication_date`).

Returns: `{id, company, filing_type, publication_date, period_end_date, language, source_url, pdf_url}`.

Pitfall: `filing_type` is jurisdiction-specific (e.g. "10-K" for US issuers vs. "Annual Report" generically). Use `filing_categories_list` for cross-jurisdiction queries — categories normalise across markets.

### `filings_retrieve`
Single filing detail. **outputSchema-advertised**.

Key params: `id`.

Returns: `filings_list` row + `summary`, `language`, `regulator`, `pdf_url`, `markdown_available`.

### `filings_history_retrieve`
Audit trail — every revision of a filing (originals, amendments, restatements).

Key params: `id`.

Use case: "has this filing been amended?"

### `filings_markdown_retrieve`
Filing content as markdown (capped at **150K characters**).

Key params: `id`.

Pitfall: long 10-Ks (300+ pages) get truncated. For full text, use the `pdf_url` from `filings_retrieve`.

## ISIC Classifications (8)

ISIC = International Standard Industrial Classification (UN). Hierarchy: section (letter) → division (2-digit) → group (3-digit) → class (4-digit).

| Tool | Purpose |
|---|---|
| `isic_sections_list` / `isic_sections_retrieve` | Top level (A–U) |
| `isic_divisions_list` / `isic_divisions_retrieve` | 2-digit (e.g., 35 = Electricity, gas) |
| `isic_groups_list` / `isic_groups_retrieve` | 3-digit |
| `isic_classes_list` / `isic_classes_retrieve` | 4-digit (most specific; what `companies_list?isic_class=…` filters on) |

## ISINs (2)

### `isins_list`
**outputSchema-advertised.** All ISINs for a company (handles dual-listings).

Key params: `company`, `country`.

### `isins_retrieve`
ISIN → company lookup.

Key params: `isin` (12-char alphanumeric).

Returns: `{isin, company, exchange, country, currency, primary}`.

Pitfall: not every ISIN is in our index. If `isins_retrieve` 404s, fall back to `companies_list?search=`.

## Reference Data (8)

Lookups for filtering and labeling. All have `_list` and `_retrieve` variants.

| Tool | Returns |
|---|---|
| `countries_list` / `countries_retrieve` | ISO-3166 country metadata |
| `filing_categories_list` / `filing_categories_retrieve` | Cross-jurisdiction categories (annual_report, insider_transaction, etc.) |
| `filing_types_list` / `filing_types_retrieve` | Jurisdiction-specific types (10-K, DEF 14A, AR-Form, etc.) |
| `languages_list` / `languages_retrieve` | ISO-639 language codes for filings |
| `sources_list` / `sources_retrieve` | Source regulators (the canonical list is returned by the API; treat the response as authoritative rather than hardcoding regulator names) |

Use these for **labeling**, not lookup. Don't call `countries_list` to find country IDs — `companies_list?country=US` accepts ISO codes directly.

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
