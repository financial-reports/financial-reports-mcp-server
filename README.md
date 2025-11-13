# Financial Reports MCP Server

**Official Model Context Protocol (MCP) server for the FinancialReports API.**

This server acts as a bridge between an MCP client (like Claude Desktop) and the official FinancialReports API. It exposes the complete API surface as a set of LLM-callable tools, allowing for natural language queries of European company filings, financial data, and corporate information.

This server is generated directly from the official [FinancialReports OpenAPI schema](https://financialreports.eu/api/schema/) to ensure it is always up-to-date with the latest API endpoints.

> *Special thanks to [itisaevalex](https://github.com/itisaevalex) for their original [community-built MCP server](https://github.com/itisaevalex/financial-reports-mcp-server), which served as the inspiration and proof-of-concept for this official version.*

---

## 🚀 Getting Started (Docker)

The recommended way to run this server is with Docker.

### 1. Build the Image

From the root of this repository, build the Docker image. We use `--no-cache` to ensure the latest source code is always used, bypassing any stale layers.

We use --no-cache to ensure the latest source code is used
```
docker build --no-cache -t financial-reports-mcp .
```

### 2. Configure Your MCP Client (Claude Desktop)

Open your Claude Desktop configuration file:
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add the following entry to the `mcpServers` object, replacing `your_api_key_here` with your real FinancialReports API key:

```
{
  "mcpServers": {
    "financial-reports": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e", "API_KEY=your_api_key_here",
        "-e", "API_BASE_URL=https://api.financialreports.eu/",
        "-e", "MCP_TRANSPORT=stdio",
        "financial-reports-mcp:latest"
      ]
    }
  }
}
```


### 3. Restart Claude

Completely quit and restart the Claude Desktop application (Cmd+Q on macOS). The "financial-reports" toolset will now be available.

---

## 🔧 Local Python (Development)

If you want to run the server locally for development:

1.  **Create & Activate Environment:**
    ```
    python3 -m venv venv
    source venv/bin/activate
    ```

2.  **Install Dependencies:**
    ```
    pip install -r requirements.txt
    ```

3.  **Set Environment Variables:**
    Create a `.env` file in the project root (you can copy `.env.example`).
    ```
    API_KEY=your_api_key_here
    MCP_TRANSPORT=stdio
    ```

4.  **Run the Server:**
    ```
    python -m src.financial_reports_mcp
    ```

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

---

## ⚠️ Known Issues

### SDK `v1.3.2`
The `financial-reports-generated-client` version `v1.3.2` had a known authentication bug where the `ApiClient` failed to send the `X-API-Key` header. This server was built to bypass the SDK entirely and use `httpx` directly, which resolves this issue. SDK version `v1.3.3` has fixed this bug.

### `SSLCertVerificationError`
This server disables SSL certificate verification (`verify=False`) in its internal `httpx` client. This is necessary to accommodate local Python environments (especially on macOS) that may be missing the required root certificates. This is generally safe for this use case but is not recommended for highly sensitive production environments.