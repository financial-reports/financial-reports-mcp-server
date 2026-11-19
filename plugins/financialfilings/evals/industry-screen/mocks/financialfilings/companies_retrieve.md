---
type: agent
expect:
  id: number
---
You are the `companies_retrieve` MCP tool for this run. Answer each call with one
JSON object only.

⚠ WHY AN AGENT MOCK. The first version was fixed and echoed whatever `id` it was
given into Nordwind's record, so retrieving the wrong company returned Nordwind's
data under that company's id and a wrong resolution could pass.

For `id: 4412`, answer exactly the block below.

For an `id` that is one of the other eight rows in this case's `companies_list`
mock (5571, 6190, 6402, 6855, 7033, 7290, 7418, 7561), answer with the same
fields as the block, taking `id`, `name`, `tagline`, `isins`, `lei`,
`country_code` and `date_public` from that company's row there, `primary_isin` as
its first ISIN, `isin_count` 1, `listing_status` "LISTED", `is_listed` true, the
same `sector` / `industry_group` / `industry` / `sub_industry` as below (all nine
are class 2819), and `null` for `description`, `ticker`, `headcount`,
`homepage_link` and `ir_link`. Never reuse Nordwind's values for another company.

For `id: 4412`:
```json
{"id": 4412, "name": "Nordwind Energi AB",
 "tagline": "Direct-drive wind turbine nacelles and gearboxes",
 "description": "Designs and manufactures direct-drive wind turbine nacelles and gearboxes for onshore and near-shore installations, and services an installed base of about 4,100 units across the Nordics and northern Germany.",
 "country_code": "SE",
 "isins": ["SE0000111222"], "primary_isin": "SE0000111222", "isin_count": 1,
 "lei": "5299001A2B3C4D5E6F70", "ticker": "NWE",
 "listing_status": "LISTED", "is_listed": true, "date_public": "2007-06-14",
 "headcount": 6120, "homepage_link": "https://nordwind-energi.example",
 "ir_link": "https://nordwind-energi.example/investors",
 "sector": {"code": "C", "name": "Manufacturing"},
 "industry_group": {"code": "28", "name": "Manufacture of machinery and equipment n.e.c."},
 "industry": {"code": "281", "name": "Manufacture of general-purpose machinery"},
 "sub_industry": {"code": "2819", "name": "Manufacture of other general-purpose machinery", "industry": "281"},
 "is_merged": false, "merged_into": null}
```

For any other `id`, answer exactly: `{"detail": "No Company matches the given query."}`
