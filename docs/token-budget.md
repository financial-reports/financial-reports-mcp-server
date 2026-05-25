# Token-budget audit

Total tools registered: **42**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `filings_list` | 795 | 2535 | 831 |
| `companies_financials_retrieve` | 1497 | 682 | 544 |
| `companies_list` | 615 | 1067 | 419 |
| `webhooks_create` | 643 | 690 | 332 |
| `line_item_definitions_list` | 620 | 586 | 301 |
| `filings_markdown_retrieve` | 1030 | 171 | 299 |
| `webhooks_deliveries_replay_create` | 123 | 769 | 222 |
| `webhooks_test_create` | 140 | 719 | 214 |
| `webhooks_regenerate_secret_create` | 128 | 719 | 211 |
| `isic_classes_list` | 42 | 730 | 192 |
| `isic_groups_list` | 41 | 653 | 173 |
| `filings_retrieve` | 578 | 74 | 162 |
| `companies_retrieve` | 555 | 74 | 156 |
| `isins_list` | 88 | 529 | 154 |
| `isic_divisions_list` | 44 | 570 | 153 |
| `isic_sections_list` | 43 | 495 | 133 |
| `isins_retrieve` | 430 | 77 | 126 |
| `filing_types_list` | 56 | 318 | 93 |
| `webhooks_delivery_detail_retrieve` | 171 | 124 | 73 |
| `webhooks_list` | 109 | 175 | 70 |
| `watchlist_companies_bulk_add_create` | 140 | 117 | 64 |
| `watchlist_companies_bulk_remove_create` | 141 | 117 | 64 |
| `filing_categories_list` | 79 | 175 | 62 |
| `sources_list` | 56 | 175 | 57 |
| `languages_list` | 55 | 175 | 56 |
| `countries_list` | 43 | 175 | 53 |
| `filings_history_retrieve` | 118 | 74 | 47 |
| `companies_next_annual_report_retrieve` | 102 | 74 | 43 |
| `webhooks_retrieve` | 93 | 74 | 41 |
| `watchlist_companies_create` | 63 | 90 | 37 |
| `webhooks_deliveries_retrieve` | 77 | 74 | 37 |
| `filing_categories_retrieve` | 58 | 74 | 32 |
| `isic_divisions_retrieve` | 56 | 74 | 32 |
| `filing_types_retrieve` | 54 | 74 | 31 |
| `isic_classes_retrieve` | 53 | 74 | 31 |
| `isic_groups_retrieve` | 53 | 74 | 31 |
| `isic_sections_retrieve` | 55 | 74 | 31 |
| `line_item_definitions_retrieve` | 51 | 77 | 31 |
| `sources_retrieve` | 54 | 74 | 31 |
| `watchlist_retrieve` | 93 | 33 | 31 |
| `countries_retrieve` | 50 | 74 | 30 |
| `languages_retrieve` | 51 | 74 | 30 |

**Total approx tokens for `tools/list`: 5760**

> **Methodology**: token count is approximated as `len(chars) // 4`
> (per-tool description + JSON-serialized parameter schema). The actual
> tiktoken/Claude-tokenizer count for JSON-dense schemas is typically
> 10–30% higher than this heuristic. Use this report for *relative*
> comparisons (which tool is biggest, did a change make things worse)
> rather than as an absolute budget against client context windows.

Reference budgets (anecdotal, 2026):
- < 5k tokens: lean
- 5k-15k tokens: acceptable for a focused server
- > 15k tokens: trim descriptions or split the server
