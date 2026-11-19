---
type: fixed
---
{"summary": {"matched": 2, "matched_via_alias": 0, "ambiguous": 1, "not_covered": 1},
 "results": [
  {"ref": "1", "input": {"name": "Nordwind Energi"},
   "status": "matched", "resolved_via": "name",
   "company": {"id": 4412, "name": "Nordwind Energi AB", "country_iso": "SE",
               "isin": "SE0000111222", "ticker": "NWE", "listing_status": "LISTED",
               "sub_industry_code": "2819"},
   "candidates": [], "warnings": []},
  {"ref": "2", "input": {"name": "Helios Turbinen"},
   "status": "matched", "resolved_via": "name",
   "company": {"id": 5571, "name": "Helios Turbinen GmbH", "country_iso": "DE",
               "isin": "DE0007654321", "ticker": "HTG", "listing_status": "LISTED",
               "sub_industry_code": "2819"},
   "candidates": [], "warnings": []},
  {"ref": "3", "input": {"name": "Atlas Rotor"},
   "status": "ambiguous", "resolved_via": null, "company": null,
   "candidates": [
     {"id": 7120, "name": "Atlas Rotor Industri A/S", "country_iso": "DK",
      "isin": "DK0001122334", "listing_status": "LISTED"},
     {"id": 7121, "name": "Atlas Rotor Holding Oyj", "country_iso": "FI",
      "isin": "FI0009988776", "listing_status": "LISTED"}
   ],
   "warnings": ["two listed entities match this name; confirm which one is meant"]},
  {"ref": "4", "input": {"name": "Brightwater Marine"},
   "status": "not_covered", "resolved_via": null, "company": null,
   "candidates": [], "warnings": []}
 ]}
