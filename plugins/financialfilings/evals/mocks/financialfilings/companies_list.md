---
type: agent
---
You are the `companies_list` MCP tool for this run. Answer each call with one JSON
object only.

⚠ WHY AN AGENT MOCK. The first version was fixed and returned Nordwind for every
search, so a search for any other name "found" Nordwind and a wrong resolution
looked like a right one. Cases that need more companies carry their own mock.

The universe is the one row below. Keep it only if it passes every filter given:
`search` (its text occurs in `name`, case-insensitive), `countries` (comma-separated
ISO codes, must include `SE`), `sub_industry` (must be `2819`) and `listing_status`
(must be `LISTED`). If it passes, answer exactly the block; if not, answer
`{"count": 0, "next": null, "previous": null, "results": []}`.

```json
{"count": 1, "next": null, "previous": null, "results": [
  {"id": 4412, "name": "Nordwind Energi AB",
   "tagline": "Direct-drive wind turbine nacelles and gearboxes",
   "isins": ["SE0000111222"], "lei": "5299001A2B3C4D5E6F70",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "SE", "date_public": "2007-06-14"}
]}
```
