# Token-budget audit

Total tools registered: **15**

| Tool | Description chars | Schema chars | Approx tokens |
|---|---:|---:|---:|
| `filings_list` | 795 | 2535 | 831 |
| `companies_financials_retrieve` | 1966 | 682 | 661 |
| `companies_list` | 1035 | 1067 | 524 |
| `filings_markdown_retrieve` | 1030 | 171 | 299 |
| `filings_retrieve` | 578 | 74 | 162 |
| `companies_retrieve` | 555 | 74 | 156 |
| `isins_list` | 88 | 529 | 154 |
| `filings_markdown_search` | 372 | 164 | 134 |
| `isins_retrieve` | 430 | 77 | 126 |
| `filing_types_list` | 56 | 318 | 93 |
| `filing_categories_list` | 79 | 175 | 62 |
| `get_fr_filing_type_taxonomy` | 208 | 33 | 60 |
| `get_fr_industry_classification_isic` | 190 | 33 | 55 |
| `get_fr_markdown_fetch_strategy` | 165 | 33 | 49 |
| `companies_next_annual_report_retrieve` | 102 | 74 | 43 |

**Total approx tokens for `tools/list`: 3409**

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
