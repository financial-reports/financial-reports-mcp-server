# Token-budget audit

Total tools registered: **17**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `filings_list` | 1668 | 4463 | 1532 |
| `companies_financials_retrieve` | 4558 | 980 | 1384 |
| `companies_list` | 1035 | 1888 | 730 |
| `companies_resolve_create` | 2770 | 87 | 713 |
| `filings_markdown_retrieve` | 2372 | 171 | 635 |
| `usage_retrieve` | 1182 | 33 | 303 |
| `filings_retrieve` | 1111 | 74 | 295 |
| `filing_types_list` | 364 | 318 | 170 |
| `companies_retrieve` | 559 | 74 | 157 |
| `isins_list` | 88 | 529 | 154 |
| `filings_markdown_search` | 372 | 164 | 134 |
| `isins_retrieve` | 432 | 77 | 127 |
| `companies_next_annual_report_retrieve` | 235 | 74 | 76 |
| `filing_categories_list` | 79 | 175 | 62 |
| `get_fr_filing_type_taxonomy` | 208 | 33 | 60 |
| `get_fr_industry_classification_isic` | 190 | 33 | 55 |
| `get_fr_markdown_fetch_strategy` | 187 | 33 | 54 |

**Total approx tokens for `tools/list`: 6641**

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
