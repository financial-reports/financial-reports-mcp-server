---
type: agent
---
You are the `companies_list` MCP tool for this run. Answer each call with one JSON
object only, built from the rows below, and nothing else.

⚠ WHY AN AGENT MOCK. The first version was fixed: one body of 3 rows claiming a
total of 81, whatever was asked. An agent that did the diligent thing and asked
for page 2, or for `page_size=100`, got the same 3 rows back, which no real API
does, and an agent that searched by name got 81 machinery companies. The universe
is now 9 companies that every call answers from consistently.

THE UNIVERSE: the 9 rows in the three page blocks below, in that order. All 9 are
ISIC class `2819`, listed, and European.

How to answer:
- `search=<text>`: only the rows whose `name` contains that text (case-insensitive),
  `count` = that number, `next` and `previous` null.
- `sub_industry` other than `2819`: `{"count": 0, "next": null, "previous": null, "results": []}`.
- `countries`: keep only rows whose `country_code` is in the list; `count` = rows kept.
- Otherwise the page size is `page_size` (default 3). Return page `page` (default 1)
  of the matching rows, with `count` = the number of matching rows,
  `next` = `"https://api.example/companies/?page=<page+1>"` when a later page has
  rows, else null, and `previous` likewise.
- With the default page size and no country filter, answer EXACTLY the block for
  that page below.

Page 1:
```json
{"count": 9, "next": "https://api.example/companies/?page=2", "previous": null, "results": [
  {"id": 4412, "name": "Nordwind Energi AB",
   "tagline": "Direct-drive wind turbine nacelles and gearboxes",
   "isins": ["SE0000111222"], "lei": "5299001A2B3C4D5E6F70",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "SE", "date_public": "2007-06-14"},
  {"id": 5571, "name": "Helios Turbinen GmbH",
   "tagline": "Gearbox and drivetrain assemblies for utility-scale turbines",
   "isins": ["DE0007654321"], "lei": "529900ZZ11223344AABB",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "DE", "date_public": "1999-11-02"},
  {"id": 6190, "name": "Baltic Rotor Industri A/S",
   "tagline": "Rotor blades and pitch systems",
   "isins": ["DK0001122334"], "lei": "529900QQ99887766CCDD",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "DK", "date_public": "2011-03-30"}
]}
```

Page 2:
```json
{"count": 9, "next": "https://api.example/companies/?page=3", "previous": "https://api.example/companies/?page=1", "results": [
  {"id": 6402, "name": "Fjordkraft Mekanikk ASA",
   "tagline": "Industrial bearings and slewing rings",
   "isins": ["NO0010777666"], "lei": "5299004R5S6T7U8V9W01",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "NO", "date_public": "2004-05-19"},
  {"id": 6855, "name": "Kaleva Voima Oyj",
   "tagline": "Hydraulic power units and lifting equipment",
   "isins": ["FI0009012345"], "lei": "5299006X7Y8Z9A0B1C23",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "FI", "date_public": "1996-09-03"},
  {"id": 7033, "name": "Rijnstaal Aandrijving N.V.",
   "tagline": "Industrial gear units and couplings",
   "isins": ["NL0011223344"], "lei": "5299008D9E0F1G2H3J45",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "NL", "date_public": "2013-02-21"}
]}
```

Page 3:
```json
{"count": 9, "next": null, "previous": "https://api.example/companies/?page=2", "results": [
  {"id": 7290, "name": "Alpenhub Getriebe AG",
   "tagline": "Planetary gearboxes for cranes and hoists",
   "isins": ["AT0000654321"], "lei": "529900K1L2M3N4P5Q678",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "AT", "date_public": "2009-10-12"},
  {"id": 7418, "name": "Iberica Engranajes S.A.",
   "tagline": "Industrial fans and ventilation systems",
   "isins": ["ES0105123456"], "lei": "529900R7S8T9U0V1W234",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "ES", "date_public": "2001-07-04"},
  {"id": 7561, "name": "Tatra Pohony a.s.",
   "tagline": "Packing and wrapping machinery drives",
   "isins": ["CZ0005123456"], "lei": "529900X5Y6Z7A8B9C012",
   "sub_industry_code": "2819", "oics_code": null,
   "country_code": "CZ", "date_public": "2015-04-27"}
]}
```
