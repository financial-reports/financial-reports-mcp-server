# Financial Reports MCP Server

**Official Model Context Protocol (MCP) server for the FinancialReports API.**

This server acts as a bridge between an MCP client (like Claude Desktop) and the official FinancialReports API. It exposes the complete API surface as a set of LLM-callable tools, allowing for natural language queries of European company filings, financial data, and corporate information.

This server is generated directly from the official [FinancialReports OpenAPI schema](https://financialreports.eu/api/schema/) to ensure it is always up-to-date with the latest API endpoints.

> *Special thanks to [itisaevalex](https://github.com/itisaevalex) for their original [community-built MCP server](https://github.com/itisaevalex/financial-reports-mcp-server), which served as the inspiration and proof-of-concept for this official version.*

---

## 🌐 Using the hosted server

The official server is hosted at **`https://mcp.financialfilings.com/mcp`**. For most users you don't need to run anything locally — just point your MCP client at that URL and sign in with your FinancialReports account.

### Claude.ai / Claude Desktop / ChatGPT / Cursor

Add a new connector / MCP server with the URL `https://mcp.financialfilings.com/mcp`. The first call triggers an OAuth sign-in via AWS Cognito; a paid (Analyst or Enterprise) subscription is required for tool access.

---

## 🐳 Self-Hosting (Docker)

If you want to run your own instance, you'll need your own AWS Cognito user pool and app client wired into the same Django backend.

### 1. Configure environment

Copy `.env.example` to `.env` and fill in the Cognito values. The required variables are:

* `COGNITO_USER_POOL_ID`
* `COGNITO_CLIENT_ID`
* `COGNITO_CLIENT_SECRET`
* `MCP_BASE_URL` — public URL where this server is reachable (must be an allowed redirect URI on the Cognito app client)

The full list with defaults lives in [`.env.example`](.env.example).

### 2. Build & run

```bash
docker build -t financial-reports-mcp .
docker run --rm -p 8000:8000 --env-file .env financial-reports-mcp
```

The server listens on `:8000`. Health check: `GET /health`. MCP transport (Streamable HTTP): `POST /mcp`.

---

## 🔧 Local Python (development)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then edit .env
python scripts/generate_mcp_tools.py        # bake src/financial_reports_mcp.py
python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000
```

The MCP entrypoint will be at `http://localhost:8000/mcp`.

---

## 🛠️ Available Tools

This server dynamically generates tools for *all* `GET` endpoints in the FinancialReports API. As of this writing, this includes:

### Companies
* `companies_list`: Retrieve a paginated list of companies.
* `companies_retrieve`: Retrieve detailed information for a single company by ID.

### Filings
* `filings_list`: Retrieve a paginated list of regulatory filings.
* `filings_retrieve`: Retrieve detailed information for a single filing by ID.
* `filings_markdown_retrieve`: Retrieve the raw processed content of a filing in Markdown format.

### ISIC (Industry Classification)
* `isic_sections_list`: Retrieve a paginated list of ISIC Sections.
* `isic_sections_retrieve`: Retrieve details for a specific ISIC Section by ID.
* `isic_divisions_list`: Retrieve a paginated list of ISIC Divisions.
* `isic_divisions_retrieve`: Retrieve details for a specific ISIC Division by ID.
* `isic_groups_list`: Retrieve a paginated list of ISIC Groups.
* `isic_groups_retrieve`: Retrieve details for a specific ISIC Group by ID.
* `isic_classes_list`: Retrieve a paginated list of ISIC Classes.
* `isic_classes_retrieve`: Retrieve details for a specific ISIC Class by ID.

### Reference Data
* `countries_list`: Retrieve a list of all supported countries.
* `countries_retrieve`: Retrieve details for a specific country by ID.
* `filing_types_list`: Retrieve a paginated list of all available filing types.
* `filing_types_retrieve`: Retrieve details for a specific filing type by ID.
* `languages_list`: Retrieve a list of all supported languages for filings.
* `languages_retrieve`: Retrieve details for a specific language by ID.
* `sources_list`: Retrieve a paginated list of all available data sources.
* `sources_retrieve`: Retrieve details for a specific data source by ID.

### User Watchlist
* `watchlist_retrieve`: Fetch all companies currently in the authenticated user's watchlist.
* `watchlist_companies_create`: (POST) Add a company to the user's watchlist.
* `watchlist_companies_destroy`: (DELETE) Remove a company from the user's watchlist.

### API & Download
* `schema_retrieve`: OpenAPI schema for the API.
* `downloader_jobs_status_retrieve`: Check status of a download job.

---

## 💡 Example Prompts

* "Using the financial-reports tool, find the company details for 'Volkswagen AG'."
* "Get me the 5 most recent filings for 'LVMH'."
* "List all available ISIC sections."
* "What filing types are available?"
* "Using financial-reports, get the filing detail for filing ID 12345."

