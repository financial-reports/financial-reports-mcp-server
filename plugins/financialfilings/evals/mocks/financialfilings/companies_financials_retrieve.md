---
type: fixed
expect:
  id: number
---
{"company_id": {{input.id}}, "template": "industrial", "currency": {"code": "SEK", "name": "Swedish krona", "symbol": "kr"},
 "sources_masked": false, "period_count": 2,
 "filters": {"statement_type": null, "fiscal_year": null, "fiscal_period": null,
             "line_items": null, "as_of": null,
             "as_known_at": null, "include": null},
 "periods": [
  {"fiscal_year": 2025, "fiscal_period": "FY", "period_start_date": "2025-01-01",
   "period_end_date": "2025-12-31", "statements": [
     {"statement_type": "IS", "statement_type_display": "Income Statement", "currency": {"code": "SEK", "name": "Swedish krona", "symbol": "kr"},
      "currency_mismatch": false, "accounting_standard": "IFRS",
      "accounting_standard_basis": "filer_stated", "consolidation_basis": "consolidated",
      "is_comparative": false,
      "source_filing": {"id": 998101, "filing_type": "10-K-ESEF", "release_datetime": "2026-03-12T07:00:00Z"},
      "sources": [{"filing_id": 998101, "filing_type": "10-K-ESEF", "release_datetime": "2026-03-12T07:00:00Z", "is_selected": true}],
      "line_items": [
        {"code": "revenue", "name": "Revenue", "statement_type": "IS", "depth": 0,
         "value": "51900000000", "raw_value": "51900", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true},
        {"code": "operating_income_loss", "name": "Operating profit", "statement_type": "IS", "depth": 0,
         "value": "4110000000", "raw_value": "4110", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true},
        {"code": "net_income_loss", "name": "Net income", "statement_type": "IS", "depth": 0,
         "value": "3002000000", "raw_value": "3002", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true}
      ]}]},
  {"fiscal_year": 2024, "fiscal_period": "FY", "period_start_date": "2024-01-01",
   "period_end_date": "2024-12-31", "statements": [
     {"statement_type": "IS", "statement_type_display": "Income Statement", "currency": {"code": "SEK", "name": "Swedish krona", "symbol": "kr"},
      "currency_mismatch": false, "accounting_standard": "IFRS",
      "accounting_standard_basis": "filer_stated", "consolidation_basis": "consolidated",
      "is_comparative": false,
      "source_filing": {"id": 981233, "filing_type": "10-K-ESEF", "release_datetime": "2025-03-14T07:00:00Z"},
      "sources": [{"filing_id": 981233, "filing_type": "10-K-ESEF", "release_datetime": "2025-03-14T07:00:00Z", "is_selected": true}],
      "line_items": [
        {"code": "revenue", "name": "Revenue", "statement_type": "IS", "depth": 0,
         "value": "47330000000", "raw_value": "47330", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true},
        {"code": "operating_income_loss", "name": "Operating profit", "statement_type": "IS", "depth": 0,
         "value": "3480000000", "raw_value": "3480", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true},
        {"code": "net_income_loss", "name": "Net income", "statement_type": "IS", "depth": 0,
         "value": "2455000000", "raw_value": "2455", "scale": "millions", "currency": "SEK",
         "trust_tier": "xbrl", "confirmed": true}
      ]}]}
 ],
 "notice": null, "history_window": {"limited": false}}
