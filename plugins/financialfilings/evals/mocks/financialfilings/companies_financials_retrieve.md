---
type: fixed
expect:
  id: number
---
{"company": {{input.id}}, "currency": "SEK", "results": [
  {"fiscal_year": 2025, "fiscal_period": "FY", "period_end_date": "2025-12-31",
   "statement_type": "IS", "trust_tier": "XBRL_AUDITED",
   "line_items": [
     {"name": "Revenue", "raw_value": 51900, "scale": "MILLIONS", "value": 51900000000},
     {"name": "Operating profit", "raw_value": 4110, "scale": "MILLIONS", "value": 4110000000},
     {"name": "Net income", "raw_value": 3002, "scale": "MILLIONS", "value": 3002000000}
   ]},
  {"fiscal_year": 2024, "fiscal_period": "FY", "period_end_date": "2024-12-31",
   "statement_type": "IS", "trust_tier": "XBRL_AUDITED",
   "line_items": [
     {"name": "Revenue", "raw_value": 47330, "scale": "MILLIONS", "value": 47330000000},
     {"name": "Operating profit", "raw_value": 3480, "scale": "MILLIONS", "value": 3480000000},
     {"name": "Net income", "raw_value": 2455, "scale": "MILLIONS", "value": 2455000000}
   ]}
]}
