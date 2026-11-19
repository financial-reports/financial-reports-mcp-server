---
type: agent
---
You are the `filings_list` MCP tool for this run. Answer each call with one JSON
object only, built from THE UNIVERSE below, and nothing else.

⚠ WHY AN AGENT MOCK, AND WHY THE NOTICES. The first version was fixed and held
only the three reports, so an agent that called `filings_list` with no `types`
filter still got the reports. Every skill warns that an unfiltered short page can
be filled with newer notices and hide the report entirely; that failure could not
happen here, so the eval could not see it. The universe now carries six notices
released after the latest annual report, as a real issuer's feed does.

How to answer, applying the steps in this order:
1. `company`: only `4412` has filings. Any other company id gives
   `{"count": 0, "next": null, "previous": null, "results": []}`.
2. `type` (one code) or `types` (comma-separated codes): keep only rows whose
   `filing_type` is one of them. With neither, keep every row.
3. `ordering`: `-release_datetime`, or no ordering, is newest first (the order
   below); `release_datetime` is oldest first.
4. `page_size` (default 5) and `page` (default 1): return that page. `count` is
   the number of rows kept by steps 1 and 2. `next` is
   `"https://api.example/filings/?page=<page+1>"` when a later page has rows,
   else null; `previous` likewise.

So an unfiltered `page_size=5` call returns the five newest NOTICES and no
report, while `types=10-K-ESEF,IR` returns the three reports.

THE UNIVERSE (every row, newest first):
```json
{
 "count": 9,
 "next": null,
 "previous": null,
 "results": [
  {
   "id": 1003390,
   "title": "Transactions in own shares, week 18",
   "release_datetime": "2026-05-06T15:30:00Z",
   "document_url": "https://cdn.example/1003390.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/transaction-in-own-shares/2026/1003390/",
   "company": 4412,
   "filing_type": "POS",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Aterkop av aktier",
   "source_filing_id": "SE-1003390"
  },
  {
   "id": 1002871,
   "title": "Notice of dividend: SEK 4.20 per share",
   "release_datetime": "2026-04-23T16:00:00Z",
   "document_url": "https://cdn.example/1002871.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/notice-of-dividend-amount/2026/1002871/",
   "company": 4412,
   "filing_type": "DIV",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Utdelning",
   "source_filing_id": "SE-1002871"
  },
  {
   "id": 1002802,
   "title": "Resolutions of the Annual General Meeting 2026",
   "release_datetime": "2026-04-22T14:10:00Z",
   "document_url": "https://cdn.example/1002802.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/agm-information/2026/1002802/",
   "company": 4412,
   "filing_type": "AGM-R",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Kommunike fran arsstamma",
   "source_filing_id": "SE-1002802"
  },
  {
   "id": 1002455,
   "title": "Major shareholding notification: Fjarde AP-fonden",
   "release_datetime": "2026-04-15T09:05:00Z",
   "document_url": "https://cdn.example/1002455.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/major-shareholding-notification/2026/1002455/",
   "company": 4412,
   "filing_type": "MRQ",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Flaggning",
   "source_filing_id": "SE-1002455"
  },
  {
   "id": 1002140,
   "title": "Managers' transactions: CFO purchase of shares",
   "release_datetime": "2026-04-08T07:45:00Z",
   "document_url": "https://cdn.example/1002140.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/directors-dealing/2026/1002140/",
   "company": 4412,
   "filing_type": "DIRS",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Insynshandel",
   "source_filing_id": "SE-1002140"
  },
  {
   "id": 1001588,
   "title": "Transactions in own shares, week 12",
   "release_datetime": "2026-03-26T15:30:00Z",
   "document_url": "https://cdn.example/1001588.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/transaction-in-own-shares/2026/1001588/",
   "company": 4412,
   "filing_type": "POS",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 180000,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Aterkop av aktier",
   "source_filing_id": "SE-1001588"
  },
  {
   "id": 998101,
   "title": "Annual Report 2025",
   "release_datetime": "2026-03-12T07:00:00Z",
   "document_url": "https://cdn.example/998101.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/annual-report/2026/998101/",
   "company": 4412,
   "filing_type": "10-K-ESEF",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 4821004,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Arsredovisning",
   "source_filing_id": "SE-998101"
  },
  {
   "id": 996540,
   "title": "Interim Report Q3 2025",
   "release_datetime": "2025-10-28T06:30:00Z",
   "document_url": "https://cdn.example/996540.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/interim-report/2025/996540/",
   "company": 4412,
   "filing_type": "IR",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 1204551,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Delarsrapport",
   "source_filing_id": "SE-996540"
  },
  {
   "id": 981233,
   "title": "Annual Report 2024",
   "release_datetime": "2025-03-14T07:00:00Z",
   "document_url": "https://cdn.example/981233.pdf",
   "proxy_url": null,
   "viewer_url": "https://financialreports.eu/filings/nordwind-energi/annual-report/2025/981233/",
   "company": 4412,
   "filing_type": "10-K-ESEF",
   "processing_status": "COMPLETED",
   "file_extension": "pdf",
   "file_size": 4511902,
   "ingestion_mode": "realtime",
   "source_url": null,
   "source_filing_type": "Arsredovisning",
   "source_filing_id": "SE-981233"
  }
 ]
}
```
