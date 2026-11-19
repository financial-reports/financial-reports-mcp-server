---
type: agent
---
You are the FinancialFilings company-search endpoint for this run. Answer each call
with a JSON object only, no prose, shaped
`{"count": N, "next": null, "previous": null, "results": [...]}`.

⚠ WHY AN AGENT MOCK. The suite's fixed `companies_list` returns Nordwind whatever
the search term, which in a four-company comparison hands every name the same
company. This case asks the agent to resolve FOUR names, so the mock has to vary
by `input.search`.

Match loosely and case-insensitively on `input.search`:

- "nordwind" -> one result: id 4412, "Nordwind Energi AB", country_code SE,
  isins ["SE0000111222"], sub_industry_code 2819, tagline and date_public set. Its
  reporting currency is SEK, but note the SERVED `CompanyMinimal` shape has no
  `currency`, `ticker` or `listing_status` field, so do not invent them.
- "helios" -> one result: id 5571, "Helios Turbinen GmbH", country_code DE,
  isins ["DE0007654321"], sub_industry_code 2819. Reports in EUR, which the agent
  learns from the financials call rather than from this one.
- "atlas" -> TWO results, deliberately: id 7120 "Atlas Rotor Industri A/S",
  country_code DK, isins ["DK0001122334"]; and id 7121 "Atlas Rotor Holding Oyj",
  country_code FI, isins ["FI0009988776"]. Both sub_industry_code 2819. The
  case checks that two plausible hits are surfaced rather than silently reduced
  to one.
- "brightwater" -> `{"count": 0, "next": null, "previous": null, "results": []}`.
  We hold nothing for this name.
- anything else -> count 0 and an empty results array.
