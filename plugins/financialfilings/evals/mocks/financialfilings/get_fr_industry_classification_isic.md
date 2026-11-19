---
type: fixed
---
<!-- GENERATED from the shipping module's `_resource_industry` by
     scripts/sync_eval_guide_mocks.py. Do NOT hand-write this file: the
     first version was hand-written and invented this tool's content. -->
# Industry classification (ISIC, 4 levels)

Hierarchy from broad to specific:
- **Section**  (1 letter, 22 total)    drills down to →
- **Division** (2 digits, 87 total)    drills down to →
- **Group**    (3 digits, 258 total)   drills down to →
- **Class**    (4 digits, 463 total)   ← companies are tagged here

There is NO `isic_class` field. A full company (`companies_retrieve`) carries `sector`, `industry_group`, `industry` and `sub_industry`; `companies_list` results carry only `sub_industry_code`. The 4-digit CLASS code is `sub_industry` / `sub_industry_code`.

## Navigation

The ISIC hierarchy endpoints are NOT exposed as tools on this server, so there is no code-lookup call available. To obtain a code: resolve a company you know is in the target industry (`companies_list?search=…`), then read its `sub_industry_code`, and use that as the filter value. The section table below is the only hierarchy reference on this surface.

Filter companies by the ISIC hierarchy — the param name differs from the field name. `sub_industry` takes the 4-digit ISIC CLASS code (the value exposed as `sub_industry_code`); `industry` takes a Group code, `industry_group` a Division code, `sector` a Section code. There is no `isic_class` query param.

## The 22 sections

| Section | Activity |
|---|---|
| A | Agriculture, forestry & fishing |
| B | Mining & quarrying |
| C | Manufacturing |
| D | Electricity, gas, steam |
| E | Water, sewerage, waste |
| F | Construction |
| G | Wholesale & retail trade |
| H | Transportation & storage |
| I | Accommodation & food service |
| J | Publishing, broadcasting, media (note: this taxonomy keeps media here, NOT IT) |
| K | Telecom, IT, software, consultancy (note: software is K here, not J) |
| L | Financial & insurance |
| M | Real estate |
| N | Professional, scientific & technical |
| O | Administrative & support |
| P | Public administration |
| Q | Education |
| R | Human health & social work |
| S | Arts, sports, recreation |
| T | Other services |
| U | Households as employers |
| V | Extraterritorial organizations |

## Peer / sector query recipe

There is **no aggregator endpoint** — compute peer statistics manually:

1. Resolve target company → get its `sub_industry` from `companies_retrieve` (or `sub_industry_code` from a list result).
2. `companies_list?sub_industry=<code>` → list of peers (pass the 4-digit class code to `sub_industry`, not to `isic_class`).
3. For each peer, `companies_financials_retrieve` → the line item of interest.
4. Compute median / mean / quartiles in your response. NEVER aggregate across currencies — group peers by reporting currency first, or report per-currency aggregates separately.
5. State sample size explicitly: 'median across 12 peers with reported revenue in EUR' beats 'industry median'.

## Combining with country filter

For "semiconductor manufacturers in Asia" — first identify the ISIC class (drill: Section C → Division 26 → Group 261 → Class for semiconductors — resolve a known semiconductor issuer and read its `sub_industry_code`, since there is no ISIC lookup tool here), then `companies_list?sub_industry=<4-digit-class-code>&countries=<ISO2>` (note: `countries` is plural — there is no `country` param — and the 4-digit class code goes to `sub_industry`; `isic_class` is neither a param nor a field).
