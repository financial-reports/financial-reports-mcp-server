# Token-budget audit

Total tools registered: **24**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `filings_list` | 2202 | 5998 | 2049 |
| `companies_financials_retrieve` | 4454 | 3394 | 1961 |
| `filings_search` | 3508 | 848 | 1089 |
| `filings_markdown_retrieve` | 3174 | 171 | 835 |
| `companies_list` | 1057 | 1888 | 736 |
| `companies_resolve_create` | 2727 | 87 | 702 |
| `filings_markdown_search_batch` | 2323 | 202 | 630 |
| `filings_markdown_search` | 1948 | 164 | 528 |
| `filings_search_save` | 1111 | 815 | 480 |
| `filings_retrieve` | 1179 | 74 | 312 |
| `usage_retrieve` | 1182 | 33 | 303 |
| `filings_search_new` | 775 | 154 | 231 |
| `filings_markdown_outline` | 589 | 203 | 197 |
| `filing_types_list` | 396 | 318 | 178 |
| `companies_retrieve` | 592 | 74 | 166 |
| `isins_list` | 121 | 529 | 162 |
| `isins_retrieve` | 465 | 77 | 135 |
| `filings_search_saved_delete` | 260 | 100 | 90 |
| `companies_next_annual_report_retrieve` | 235 | 74 | 76 |
| `filing_categories_list` | 112 | 175 | 71 |
| `filings_search_saved_list` | 207 | 70 | 68 |
| `get_fr_filing_type_taxonomy` | 208 | 33 | 60 |
| `get_fr_industry_classification_isic` | 190 | 33 | 55 |
| `get_fr_markdown_fetch_strategy` | 187 | 33 | 54 |

**Total approx tokens for `tools/list`: 11168**

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
