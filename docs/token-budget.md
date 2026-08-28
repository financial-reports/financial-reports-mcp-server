# Token-budget audit

Total tools registered: **16**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `companies_financials_retrieve` | 3182 | 682 | 965 |
| `filings_list` | 1067 | 2535 | 899 |
| `companies_resolve_create` | 2770 | 87 | 713 |
| `companies_list` | 1035 | 1263 | 573 |
| `filings_markdown_retrieve` | 1367 | 171 | 383 |
| `filings_retrieve` | 1111 | 74 | 295 |
| `companies_retrieve` | 559 | 74 | 157 |
| `isins_list` | 88 | 529 | 154 |
| `filings_markdown_search` | 372 | 164 | 134 |
| `isins_retrieve` | 432 | 77 | 127 |
| `filing_types_list` | 56 | 318 | 93 |
| `filing_categories_list` | 79 | 175 | 62 |
| `get_fr_filing_type_taxonomy` | 208 | 33 | 60 |
| `get_fr_industry_classification_isic` | 190 | 33 | 55 |
| `get_fr_markdown_fetch_strategy` | 165 | 33 | 49 |
| `companies_next_annual_report_retrieve` | 102 | 74 | 43 |

**Total approx tokens for `tools/list`: 4762**

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
