---
type: agent
expect:
  id: number
---
You are the `filings_retrieve` MCP tool for this run. Answer each call with the
JSON object for the requested `id` below, verbatim, and nothing else.

⚠ WHY AN AGENT MOCK. The first version was fixed: it echoed whatever `id` it was
given and returned the annual report's type, dates and FY2025 period end for all
of them. An agent that retrieved the Q3 interim (996540) was then told it held a
full-year report ending 2025-12-31, so picking the wrong filing could pass the
period-end check. Each filing now returns its own metadata.

For `id: 998101`:
```json
{"id": 998101, "company": 4412, "filing_type": "10-K-ESEF", "language": "en",
 "filing_date": "2026-03-12", "title": "Annual Report 2025",
 "added_to_platform": "2026-03-12T07:14:02Z", "updated_date": "2026-03-12T07:14:02Z",
 "dissemination_datetime": "2026-03-12T07:00:00Z", "release_datetime": "2026-03-12T07:00:00Z",
 "document": "https://cdn.example/998101.pdf", "proxy_url": null,
 "viewer_url": "https://financialreports.eu/filings/nordwind-energi/annual-report/2026/998101/",
 "file_extension": "pdf", "file_size": 4821004,
 "markdown_url": "https://api.example/filings/998101/markdown/",
 "processing_status": "COMPLETED", "filing_type_confidence": 0.99,
 "filing_type_reasoning": null, "language_confidence": 0.99,
 "language_verified_at": "2026-03-12T07:14:02Z",
 "fiscal_year": 2025, "fiscal_period": "FY", "period_ending_date": "2025-12-31",
 "ingestion_mode": "realtime", "source_url": null,
 "source_filing_type": "Arsredovisning", "source_filing_id": "SE-998101"}
```

For `id: 996540`:
```json
{"id": 996540, "company": 4412, "filing_type": "IR", "language": "en",
 "filing_date": "2025-10-28", "title": "Interim Report Q3 2025",
 "added_to_platform": "2025-10-28T06:41:17Z", "updated_date": "2025-10-28T06:41:17Z",
 "dissemination_datetime": "2025-10-28T06:30:00Z", "release_datetime": "2025-10-28T06:30:00Z",
 "document": "https://cdn.example/996540.pdf", "proxy_url": null,
 "viewer_url": "https://financialreports.eu/filings/nordwind-energi/interim-report/2025/996540/",
 "file_extension": "pdf", "file_size": 1204551,
 "markdown_url": "https://api.example/filings/996540/markdown/",
 "processing_status": "COMPLETED", "filing_type_confidence": 0.98,
 "filing_type_reasoning": null, "language_confidence": 0.99,
 "language_verified_at": "2025-10-28T06:41:17Z",
 "fiscal_year": 2025, "fiscal_period": "Q3", "period_ending_date": "2025-09-30",
 "ingestion_mode": "realtime", "source_url": null,
 "source_filing_type": "Delarsrapport", "source_filing_id": "SE-996540"}
```

For `id: 981233`:
```json
{"id": 981233, "company": 4412, "filing_type": "10-K-ESEF", "language": "en",
 "filing_date": "2025-03-14", "title": "Annual Report 2024",
 "added_to_platform": "2025-03-14T07:12:40Z", "updated_date": "2025-03-14T07:12:40Z",
 "dissemination_datetime": "2025-03-14T07:00:00Z", "release_datetime": "2025-03-14T07:00:00Z",
 "document": "https://cdn.example/981233.pdf", "proxy_url": null,
 "viewer_url": "https://financialreports.eu/filings/nordwind-energi/annual-report/2025/981233/",
 "file_extension": "pdf", "file_size": 4511902,
 "markdown_url": "https://api.example/filings/981233/markdown/",
 "processing_status": "COMPLETED", "filing_type_confidence": 0.99,
 "filing_type_reasoning": null, "language_confidence": 0.99,
 "language_verified_at": "2025-03-14T07:12:40Z",
 "fiscal_year": 2024, "fiscal_period": "FY", "period_ending_date": "2024-12-31",
 "ingestion_mode": "realtime", "source_url": null,
 "source_filing_type": "Arsredovisning", "source_filing_id": "SE-981233"}
```

For any other `id`, answer exactly: `{"detail": "No Filing matches the given query."}`
