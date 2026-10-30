# Token-budget audit

Total tools registered: **18**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `filings_list` | 1705 | 4338 | 1510 |
| `companies_financials_retrieve` | 4558 | 1208 | 1441 |
| `companies_list` | 1068 | 1888 | 739 |
| `companies_resolve_create` | 2727 | 87 | 702 |
| `filings_markdown_retrieve` | 2436 | 171 | 651 |
| `filings_retrieve` | 1144 | 74 | 304 |
| `usage_retrieve` | 1182 | 33 | 303 |
| `filings_markdown_search_batch` | 829 | 202 | 257 |
| `filing_types_list` | 397 | 318 | 178 |
| `companies_retrieve` | 592 | 74 | 166 |
| `isins_list` | 121 | 529 | 162 |
| `isins_retrieve` | 465 | 77 | 135 |
| `filings_markdown_search` | 372 | 164 | 134 |
| `companies_next_annual_report_retrieve` | 235 | 74 | 76 |
| `filing_categories_list` | 112 | 175 | 71 |
| `get_fr_filing_type_taxonomy` | 208 | 33 | 60 |
| `get_fr_industry_classification_isic` | 190 | 33 | 55 |
| `get_fr_markdown_fetch_strategy` | 187 | 33 | 54 |

**Total approx tokens for `tools/list`: 6998**

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

> **Regenerate on Python 3.11** — the version CI uses. `Schema chars` is
> the JSON-serialized parameter schema, and its serialization differs
> between Python versions even with an identical pydantic (measured: 3.11
> vs 3.14 differ by 111 chars on `filings_list` alone, both on pydantic
> 2.13.4). Regenerating off-version yields a file the `eval-fast`
> freshness gate rejects for reasons unrelated to your change. If you are
> not on 3.11, run the generator + this script inside `python:3.11-slim`.
