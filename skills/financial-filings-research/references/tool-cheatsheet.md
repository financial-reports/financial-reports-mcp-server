# FinancialFilings MCP — Tool Cheatsheet

50 tools across 10 domains. This file is loaded on demand; the main `SKILL.md` covers the workflows. Use this when you need exact parameter names, return shapes, or pitfalls for a specific tool.

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

Pitfall: line items are normalized across markets but currency is per-filing. Don't aggregate currencies without conversion.

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

## Filings (7)

### `filings_list`
List filings across companies. **outputSchema-advertised**.

Key params: `company`, `type` (one filing-type code) / `types` (comma-separated), `category` / `categories` (numeric FilingCategory ids), `countries` (comma-separated ISO2), `release_datetime_from`, `release_datetime_to`, `page_size`, `ordering`. `ordering` accepts ONLY `release_datetime`, `added_to_platform`, `id`, `filing_type_confidence` (prefix `-` to reverse); any other value is silently ignored and you get default order back. `-filing_type_confidence` puts unscored filings (NULL, over a quarter of the corpus) FIRST; add `min_confidence=0` to rank only scored filings, most confident first.

Returns (FilingSummary): `{id, title, release_datetime, document_url, proxy_url, viewer_url, company, filing_type, processing_status, file_extension, file_size}`. `processing_status` is also on `view='full'` rows and on `filings_retrieve`; it can be null, which means unknown.

Pitfall: the param is `type`, not `filing_type`, and the code is jurisdiction-specific (e.g. "10-K" for US issuers vs. a local annual type). Use `filing_categories_list` to find a numeric category id, then pass `category`/`categories` for cross-jurisdiction queries — categories normalise across markets.

### `filings_retrieve`
Single filing detail. **outputSchema-advertised**.

Key params: `id`.

Returns (Filing): `id`, `company`, `filing_type`, `language`, `filing_date`, `title`, `added_to_platform`, `updated_date`, `dissemination_datetime`, `release_datetime`, `source`, `document`, `proxy_url`, `viewer_url`, `file_extension`, `file_size`, `markdown_url`, `filing_type_confidence`, `filing_type_reasoning`, `fiscal_year`, `fiscal_period`, `period_ending_date`. Also carries `processing_status` (can be null — unknown). There is no `summary`, `regulator`, `pdf_url` or `markdown_available`.

### `filings_history_retrieve`
Audit trail — every revision of a filing (originals, amendments, restatements).

Key params: `id`.

Use case: "has this filing been amended?"

### `filings_markdown_retrieve`
Filing content as markdown, in pages.

Key params: `filing_id`, `offset` (default 0), `limit` (default 50,000 characters; capped at 150,000 per call).

Pitfall: a long filing (300-page 10-K, ESEF annual report) does not fit in one call. When the response contains the truncation marker, call again with the `offset` it gives you. Stop as soon as you have the section you need (or use `filings_markdown_search` to jump to it) rather than paging the whole document. For the raw file, use `document` from `filings_retrieve` (there is no pdf_url field).

### `filings_search`
Full-text search across the text of EVERY filing — the corpus-wide "which filings / which companies mention X" tool. Nothing else here answers that question.

Key params: `queries` (1-5 phrases, OR-ed, each at most 200 chars; a single `query` string is also accepted), `company` / `companies` (up to 50 internal ids), `include_predecessors`, `countries`, `languages`, `types` (comma-separated filing-type CODES), `release_datetime_from` / `_to`, `added_to_platform_from` / `_to`, `ordering`, `max_results` (1-10,000, default 1,000), `group_by`, `page`, `page_size`.

Returns: matching filings with snippets showing where the text matched (only the first 10 results of a page carry snippets). `group_by="company"` returns one row per company instead — country, ISIN, matching-filing count, first and last release date, best filing — counted over the first `max_results` matches only, with no ordering and no snippets.

Pitfall: `types` takes FinancialFilings codes, NOT SEC form names — `S-1`, `13F-HR` and `424B5` are not codes and are rejected. Call `get_fr_filing_type_taxonomy` to translate. Filings are in many languages, so pass the term AND its translations as separate entries; an English query and its native-language phrasing find different filings. Fiscal year and period filters are NOT available here — use a release-date range. An empty result means no match among filings WITH extracted text, within the first 20 MB of each — unless the result says the search stopped early, in which case matches may exist.

Cost: one Markdown request per page that returns at least one result (6 credits, 12 if any filing on the page is a premium type). A search with no results bills nothing; every page bills separately.

### `filings_markdown_search`
Search ONE filing's markdown and get back only the matching passages.

Key params: `filing_id`, `query` (a SUBSTRING, at most 200 characters), `max_hits`.

Returns: hits with ~440 characters of context each and a character `offset`. Within reach, that offset reads further around the hit via `filings_markdown_retrieve`.

Pitfall: the offset is NOT always reachable. The server searches the whole document; `filings_markdown_retrieve` still stops at 10,000,000 bytes, so a hit past that names a passage this tool found and that one cannot fetch (1,586 filings in prod exceed the cap). The result SAYS which case you are in — read its NOTE rather than guessing, and when it says a hit is out of reach, use the ~440 characters of context here, which is the whole passage available. Tracked as #175; it disappears once retrieve windows on the API's own offset/limit.

Pitfall: use this INSTEAD of paging a long filing, but only once you HAVE the filing — to find which filings say something, use `filings_search`. `query` is a substring, not a phrase matcher: search a distinctive phrase, not a whole passage.

### `filings_markdown_search_batch`
One query across SEVERAL filings you already hold, in a single call.

Key params: `filing_ids` (max 20 per call), `query`, `max_hits_per_filing`.

Returns: per-filing hits with character offsets, and outcomes reported SEPARATELY — matched, no match, searched only in part, not searched.

Pitfall: it searches ONLY the filings you name, so a "no match" says nothing about filings outside your list — that question is `filings_search`'s. A filing can be BOTH matched and only partly searched: hits found before the byte cap are real, the tail past it is unknown. Do not read a partial search as an absence.

## Guide tools (3)

These take NO parameters. They exist because a tool-only MCP client cannot read MCP resources, so the same guidance is served both ways. Read the relevant one BEFORE filtering or screening — the codes are not guessable.

### `get_fr_filing_type_taxonomy`
The full 30-code filing-type taxonomy (codes, names, categories), plus the form-name translation table and the `DEF 14A` name collision.

Key params: none.

Pitfall: these are cross-jurisdiction codes, NOT form names. `S-1`, `13F-HR` and `424B5` are not codes; `10-K` is one (it also covers 20-F); and the code spelled `DEF 14A` does NOT hold DEF 14A proxy statements — those are `PSI`. Read this before passing `type`/`types` to `filings_list` or `types` to `filings_search`.

### `get_fr_industry_classification_isic`
The ISIC hierarchy (section / division / group / class) and the peer-screening recipe.

Key params: none.

Pitfall: there is no `isic_class` field — the 4-digit class is `sub_industry` / `sub_industry_code`.

### `get_fr_markdown_fetch_strategy`
When and how to fall back to `filings_markdown_retrieve`, including pagination and the `processing_status` caveat (a hint, not a gate).

Key params: none.

## ISIC Classifications (8)

ISIC = International Standard Industrial Classification (UN). Hierarchy: section (letter) → division (2-digit) → group (3-digit) → class (4-digit).

> **On the default surface, none of the ISIC hierarchy endpoints below are tools**:
> they are in the generator's prune list, so calling them returns "unknown tool".
> A server run with `MCP_FULL_SURFACE=1` does expose them; check your `tools/list`.
> Without them, resolve a company you know sits in the target industry and read
> its `sub_industry_code`.

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
| `sources_list` / `sources_retrieve` | Filing sources, labelled generically unless your account has them unlocked. Treat the response as authoritative |

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

1. `webhooks_create` with `url` (required), the triggers you want (`trigger_on_filing_received` for a filing's arrival, `trigger_on_filing_processed` once its content is ready, `trigger_on_filing_updated`), and the scope: `subscribed_filing_types` (filing-type codes) and/or `track_all_companies`. Optional: `include_markdown`, `include_isins`, `deliver_late_filings`. Capture the returned `secret_key`.
2. Immediately `webhooks_test_create` to verify the user's endpoint accepts and signs requests.
3. Tell the user the secret value once — we don't store it cleartext server-side.

Pitfall: there are no free-form event names: a webhook fires on the three `trigger_on_*` booleans only. Pick received vs processed deliberately: received fires on arrival, processed waits until the filing's content is ready. Don't invent fields; `webhooks_list` shows the shape of existing webhooks.

## Tool annotation summary

- 35 tools have `readOnlyHint=true` (safe to call without confirmation).
- 5 tools have `destructiveHint=true` (mutations: watchlist add/remove, webhook create, secret rotation).
- 2 tools are non-destructive probes (`webhooks_test_create`, `webhooks_deliveries_replay_create`) — they hit the user's external endpoint but don't mutate FinancialFilings state.
- 6 tools advertise `outputSchema` for structured rendering: `companies_list`, `companies_retrieve`, `companies_financials_retrieve`, `filings_list`, `filings_retrieve`, `isins_list`.

## Authentication

All tools require an authenticated session via Cognito OAuth (handled by the MCP server). Anonymous calls fail with 401. **Tools may soft-gate on rare account-status conditions (banned, deactivated); when that happens the response is a markdown link pointing the user back to their dashboard.
