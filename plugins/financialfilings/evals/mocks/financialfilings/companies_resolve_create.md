---
type: fixed
---
{"summary": {"matched": 0, "matched_via_alias": 0, "ambiguous": 3, "not_covered": 1},
 "results": [
  {"ref": "1", "input": {"name": "Nordwind Energi"},
   "status": "ambiguous", "resolved_via": null, "company": null,
   "candidates": [{"id": 4412, "name": "Nordwind Energi AB", "country_iso": "SE",
                   "isin": "SE0000111222", "listing_status": "LISTED"}],
   "warnings": ["name-only row; a name alone never returns matched"]},
  {"ref": "2", "input": {"name": "Helios Turbinen"},
   "status": "ambiguous", "resolved_via": null, "company": null,
   "candidates": [{"id": 5571, "name": "Helios Turbinen GmbH", "country_iso": "DE",
                   "isin": "DE0007654321", "listing_status": "LISTED"}],
   "warnings": ["name-only row; a name alone never returns matched"]},
  {"ref": "3", "input": {"name": "Atlas Rotor"},
   "status": "ambiguous", "resolved_via": null, "company": null,
   "candidates": [{"id": 7120, "name": "Atlas Rotor Industri A/S", "country_iso": "DK",
                   "isin": "DK0001122334", "listing_status": "LISTED"},
                  {"id": 7121, "name": "Atlas Rotor Holding Oyj", "country_iso": "FI",
                   "isin": "FI0009988776", "listing_status": "LISTED"}],
   "warnings": ["two listed entities match this name"]},
  {"ref": "4", "input": {"name": "Brightwater Marine"},
   "status": "not_covered", "resolved_via": null, "company": null,
   "candidates": [], "warnings": []}
 ]}
