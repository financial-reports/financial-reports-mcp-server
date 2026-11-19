---
type: fixed
---
<!-- GENERATED from the shipping module's `_resource_filing_types` by
     scripts/sync_eval_guide_mocks.py. Do NOT hand-write this file: the
     first version was hand-written and invented this tool's content. -->
# FinancialFilings filing-type codes (30 total)

Pass these via the `type` query param (or `types` for several) on `filings_list`, or via `types` on `filings_search`. The first column is the code; the third is the FinancialFilings taxonomy category.

## Form names are NOT codes — translate first

⚠️ **This section is written for `filings_list`, and `filings_search` differs in two ways that point OPPOSITE directions — so do not carry either rule across.**

- **Form names.** On `filings_list` a name that is not a code is REJECTED: the filter is an exact `code IN (...)`. On `filings_search` a regulator form name — `10-Q`, `8-K`, `20-F`, `S-1` — is ACCEPTED and searched as the type(s) its filings are filed under, and the result says how. So "translate first" is advice for `filings_list`, not a limit on `filings_search`.
- **Confirming the form.** The `search=` recipes and the `source_filing_type` check below are `filings_list` ONLY: `filings_search` has no `search` parameter and its rows carry the filing-type CODE, not `source_filing_type`. So there you can NARROW and you cannot CONFIRM — say the type is broader than the form, or re-run the filter through `filings_list` when the user asked for a specific one.

The CODE TABLE itself applies to both.

These codes are a cross-jurisdiction taxonomy, not form names. `type=10-Q` is not a code: an unknown code is rejected with a 400 that names it and, where one exists, suggests the replacement (the filter is an exact `code IN (...)`). Shares below measured on US filings over the 180 days to 2026-09-17.

| You want (form) | Use | Note |
|---|---|---|
| 10-Q quarterly report | `IR` + `search="10-Q"` | code alone is 92% 10-Q; title recall 94% |
| 20-F annual (foreign issuer) | `10-K` | 100% of 20-F |
| Form 4 insider transaction | `DIRS` + check `source_filing_type` | all Form 4 is DIRS, but DIRS is only 88.6% Form 4 |
| DEF 14A proxy statement | ⚠️ `PSI` + `search="DEF 14A"` | NOT the code named `DEF 14A` — see below |
| 8-K material event | `search="8-K"`, no `type` | 28 codes; see below |
| S-1 / 424B registration | `CAP` (53%), `RNS` (42%) | filter by date, then read titles |

⚠️ **`DEF 14A` is a name collision, and it is the dangerous one.** The code spelled `DEF 14A` does NOT hold DEF 14A proxy statements — those are `PSI` (3,234 in 180d). The `DEF 14A` code holds remuneration content, mostly parsed from 8-Ks (88 in 180d). Asking for `DEF 14A` returns real filings that are the wrong ones, so this fails silently in both directions.

**8-K has no single code** — it is classified by what the event IS, across 28 codes: `RNS` 28%, `ER` 28%, `MANG` 11%, `DVA` 11%, `CAP` 10%, `TAR` 3%. Omit `type` and pass `search="8-K"` with the company + date range: `search` covers the filing TITLE, and 93% of 8-K titles name the form. Same for 6-K (59% `RNS`).

⚠️ **A code is BROADER than the form, so do not report a taxonomy result as form-exact.** `type=IR` alone returns the 8% of `IR` that is 6-K/424B3, and omitting `type` returns every filing in the window. Pair the code with `search="<form>"` when the user asked for a specific form, and if you used the code alone, say so — "interim reports, which for US issuers are usually 10-Qs" is honest; calling them 10-Qs is not. Title recall measured on US filings: 10-Q 94%, 8-K 93%, DEF 14A 94%, **Form 4 only 9%**.

⭐ **The exact answer is on the row: `source_filing_type`** carries the source's own label verbatim ("10-Q", "8-K", "DEF 14A", "4", "20-F") and is populated on 99.99% of US filings. Filter by code to narrow, then READ `source_filing_type` to confirm which rows are really the form asked for. It beats a title search on both counts and it is the only precise option for Form 4. **It is nullable** — null means the source published no label, so the form is UNCONFIRMED for that row; report it as unconfirmed rather than assuming the code.

⚠️ **Form 4 is the case that needs it.** All Form 4 is `DIRS`, but `DIRS` is only **88.6%** Form 4: 8.9% is **Form 3** (initial statement of beneficial ownership — a HOLDINGS SNAPSHOT, not a transaction) and 1.4% Form 4/A. Returning `DIRS` as "insider transactions" mislabels roughly one row in nine. Titles cannot rescue this (9% recall); `source_filing_type` can. Use `source_filing_type in ("4", "4/A")` — `4/A` is an AMENDED Form 4, so a `4`-only filter silently drops it; label amendments as such, and filter to `4` alone only if the user asked for originals.

| Code | Name | Category |
|---|---|---|
| 10-K | Annual Report (US + 20-F) | Financial Reporting & Info |
| 10-K-ESEF | Annual Report (ESEF, EU) | Financial Reporting & Info |
| IR | Interim / Quarterly Report | Financial Reporting & Info |
| ER | Earnings Release | Financial Reporting & Info |
| XLSX | Financial Supplement Data | Financial Reporting & Info |
| AR | Audit Report / Information | Financial Reporting & Info |
| MDA | Management Reports / MD&A | Management & Remuneration |
| MANG | Board/Management Information | Management & Remuneration |
| DEF 14A | Remuneration Information | Management & Remuneration |
| DIRS | Director's Dealing (insider transactions) | Management & Remuneration |
| SR | Environmental & Social Information (ESG) | ESG Information |
| CGR | Governance Information | ESG Information |
| CT | Call Transcript (earnings calls) | Investor Communication |
| IP | Investor Presentation | Investor Communication |
| RPA | Report Publication Announcement | Investor Communication |
| TAR | M&A Activity | M&A, Partnerships & Legal |
| LTR | Legal Proceedings Report | M&A, Partnerships & Legal |
| AGM-R | AGM Information | Annual General Meeting |
| DVA | Voting Results & Voting Rights | Annual General Meeting |
| PSI | Proxy Solicitation & Information Statement | Annual General Meeting |
| CAP | Capital/Financing Update | Debt Information |
| IRAT | Interest Rate Update/Notice | Debt Information |
| MRQ | Major Shareholding Notification | Equity Information |
| DIV | Notice of Dividend Amount | Equity Information |
| SHA | Share Issue/Capital Change | Equity Information |
| POS | Transaction in Own Shares | Equity Information |
| FS | Fund Information / Factsheet | Investment Vehicle Info |
| NAV | Net Asset Value | Investment Vehicle Info |
| DLST | Delisting Announcement | Listing/Delisting |
| RNS | Regulatory Filings | Other |

If you need the source of truth at runtime (e.g. a new code was added since this resource was written), call `filing_types_list` — it returns the live list. A code absent from that list will match nothing silently, so check there before concluding a company has not filed something.
