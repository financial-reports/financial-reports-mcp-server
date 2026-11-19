---
type: fixed
---
FinancialFilings filing-type codes. `filings_list?type=` and `types=` take THESE
codes, never a source form name such as 10-K, 20-F, S-1 or 13F-HR.

| code | meaning | typical source forms |
|---|---|---|
| AR | Annual Report | 10-K, 20-F, Arsredovisning, Geschaftsbericht, Jaarverslag |
| IR | Interim Report | 10-Q, Delarsrapport, Halbjahresbericht |
| CT | Company Announcement | ad-hoc and price-sensitive notices |
| DIRS | Director's Dealing | insider transaction notifications |
| PR | Press Release | |
| PRE | Preliminary Results | |

An unknown code is a 400 naming it. `source_filing_type` on a returned row shows
the national form the code was mapped from, so confirm it when the distinction
matters: one code covers several national annual-report forms.
