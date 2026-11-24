---
type: fixed
---
<!-- GENERATED from the shipping module's `_resource_markdown` by
     scripts/sync_eval_guide_mocks.py. Do NOT hand-write this file: the
     first version was hand-written and invented this tool's content. -->
# Markdown-fetch strategy

## When to use filings_markdown_retrieve

Markdown has *broader* coverage than the normalised financials dataset. Reach for it when:

- `companies_financials_retrieve` returns null/missing for a line item the user asked for (debt schedules, segment data, non-IFRS metrics, capex breakdowns, etc.).
- The user wants a *section* of a filing (risk factors, MD&A, going concern, climate disclosures) — use the /find_filing_section slash command.
- The user wants verbatim language from the filing.

Do NOT reach for markdown when:

- The user wants a single normalised KPI for a single period and `companies_financials_retrieve` has it.
- The user just wants to know what was filed and when — use /summarize_recent_filings instead.

## Sharing a filing link with a human

You (the model) fetch filing text with filings_markdown_retrieve(filing_id) — you never need a URL for that. When a *human* needs to open a filing, hand them a PUBLIC link: `viewer_url` (the interactive web page) or the raw file (`document_url` on default `filings_list` rows; `document` on `view='full'` rows and on `filings_retrieve`). If a row's `processing_status` is PENDING, QUEUED, PROCESSING, FAILED or SKIPPED and its `file_extension` is not PDF, HTML, HTM or XHTML, the web page has nothing to show yet, so hand them the raw file link instead of `viewer_url`; if that link is null, say no file link is available yet rather than inventing one. A null status tells you nothing: keep `viewer_url`. NEVER give a user an `/api/...` URL — including the auth-gated markdown endpoint and the paginated `next`/`previous` links — those require credentials and return 403 for an unauthenticated person.

## processing_status: a hint, never a selection gate

Rows from `filings_list` (either view) and the `filings_retrieve` response carry `processing_status`. It can still be null on a row. Values: `COMPLETED` (markdown available), `PENDING`, `QUEUED`, `PROCESSING`, `FAILED`, `SKIPPED`.

- It is NOT a filings_list filter.
- Never gate filing selection on it: pick the newest row that matches the type you want. A null/absent value means UNKNOWN, not 'not ready' — proceed with `filings_markdown_retrieve`.
- When it IS present and is not `COMPLETED`, that filing has no markdown available (it may still be processing, or may never get any — e.g. `SKIPPED`/`FAILED`). If the user asked for THAT filing (e.g. the latest), say so rather than silently answering from an older one; otherwise the next-newest matching row may do.
- Otherwise use it only to explain a markdown call that fails with a not-found error: no markdown is available for that filing, and the error alone does not say whether it ever will, so do not promise it. Any other error is about access or availability.

## Pagination

To read one SECTION of a long filing, call `filings_markdown_outline(filing_id)` first: it lists the headings with character offsets, and `filings_markdown_retrieve` at a heading's offset starts at that heading. Page only when the outline has nothing usable.

Long filings (annual reports can run to hundreds of pages) come back paginated. `filings_markdown_retrieve` accepts `offset` and `limit` (default limit 50000 chars, per-call cap 150000). When the response contains a truncation marker, call again with an increased `offset` until the marker is gone, you've located the section you needed, or you have made 10 calls — then stop and say the document was truncated.

Don't blindly fetch every page — if you've found the answer (e.g. located the risk-factor section the user asked for), stop.

## Markdown-fallback workflow

User asks: "What's Roche's free cash flow for FY2024?"

1. resolve: `companies_list?search=Roche` → company id.
2. try the structured path: `companies_financials_retrieve(company_id, fiscal_year=2024)`.
3. if levered_free_cash_flow_cf is null/missing in that response: `filings_list?company=<id>&types=10-K,10-K-ESEF&ordering=-release_datetime&page_size=10`, then take the newest row. If its processing_status is present and not 'COMPLETED' it has no markdown available — say so, and use the next-newest only if an older filing still answers the question. A null/absent value is not a reason to skip.
4. `filings_markdown_retrieve` on that filing_id, paginate until you hit the cash-flow statement.
5. Extract the value, cite the filing (type + release_datetime + page-ish location).
