"""
AUTO-GENERATED FILE by scripts/generate_mcp_tools.py
"""
import os
from typing import Any, Coroutine
from mcp.server.fastmcp import FastMCP
import httpx
import json
import asyncio

mcp = FastMCP("financial-reports")

API_KEY = os.environ.get("API_KEY")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.financialreports.eu")

if not API_KEY:
    raise ValueError("API_KEY environment variable not set.")

# Shared client setup
headers = {
    'X-API-Key': API_KEY,
    'User-Agent': 'FinancialReports-MCP-Server/1.0'
}

client = httpx.AsyncClient(
    base_url=API_BASE_URL,
    headers=headers,
    verify=False,
    timeout=60.0
)


async def format_response(response: httpx.Response) -> str:
    """Formats an httpx.Response into a JSON string for the LLM."""
    try:
        response.raise_for_status()
        data = response.json()
        json_string = json.dumps(data, indent=2)
        return f"""```json
{json_string}
```"""
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.status_code} {e.response.reason_phrase}\nBody: {e.response.text}"
    except Exception as e:
        return f"Error formatting response: {e}"


@mcp.tool()
async def companies_list(
    countries: str | None = None,
    industry: str | None = None,
    industry_group: str | None = None,
    isin: str | None = None,
    lei: str | None = None,
    on_watchlist: bool | None = None,
    ordering: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    search: str | None = None,
    sector: str | None = None,
    sub_industry: str | None = None,
    ticker: str | None = None,
    view: str | None = "summary",
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of companies.

    Args:
        countries (Optional[str]): Filter by Company country ISO Alpha-2 code(s). Comma-separated for multiple values.
        industry (Optional[str]): Filter by ISIC Group code.
        industry_group (Optional[str]): Filter by ISIC Division code.
        isin (Optional[str]): Filter by Company ISIN. Case-insensitive.
        lei (Optional[str]): Filter by Company Legal Entity Identifier (LEI). Case-insensitive.
        on_watchlist (Optional[bool]): Filter by companies on the user's watchlist. Use 'true' to see only watchlist companies, 'false' to exclude them. Omitting the parameter returns all companies.
        ordering (Optional[str]): Which field to use when ordering the results. Available fields: `id`, `name`, `date_ipo`, `year_founded`, `country_iso__name`. Prefix with '-' for descending order (e.g., `-name`).
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        search (Optional[str]): A search term.
        sector (Optional[str]): Filter by ISIC Section code.
        sub_industry (Optional[str]): Filter by ISIC Class code.
        ticker (Optional[str]): Filter by Company primary stock Ticker symbol. Case-insensitive.
        view (Optional[str]): Controls the level of detail. Omit for a default 'summary' view, or use 'full' to include all details for each company.
    """
    try:
        query_params = {
            "countries": countries,
            "industry": industry,
            "industry_group": industry_group,
            "isin": isin,
            "lei": lei,
            "on_watchlist": on_watchlist,
            "ordering": ordering,
            "page": page,
            "page_size": page_size,
            "search": search,
            "sector": sector,
            "sub_industry": sub_industry,
            "ticker": ticker,
            "view": view,
        }

        path_params = {
        }

        url = f"/companies/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def companies_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve detailed information for a single company by its internal ID.

    Args:
        id (int): A unique integer value identifying this company.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/companies/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def countries_list(
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a list of all supported countries.

    Args:
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
    """
    try:
        query_params = {
            "page": page,
            "page_size": page_size,
        }

        path_params = {
        }

        url = f"/countries/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def countries_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific country by its ID.

    Args:
        id (int): A unique integer value identifying this country.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/countries/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def filing_types_list(
    page: int | None = None,
    page_size: int | None = None,
    search: str | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of all available filing types.

    Args:
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        search (Optional[str]): A search term.
    """
    try:
        query_params = {
            "page": page,
            "page_size": page_size,
            "search": search,
        }

        path_params = {
        }

        url = f"/filing-types/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def filing_types_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific filing type by its ID.

    Args:
        id (int): A unique integer value identifying this filing type.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/filing-types/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def filings_list(
    added_to_platform_from: str | None = None,
    added_to_platform_to: str | None = None,
    company: int | None = None,
    company_isin: str | None = None,
    countries: str | None = None,
    language: str | None = None,
    languages: str | None = None,
    lei: str | None = None,
    on_watchlist: bool | None = None,
    ordering: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    release_datetime_from: str | None = None,
    release_datetime_to: str | None = None,
    search: str | None = None,
    source: float | None = None,
    sources: str | None = None,
    type: str | None = None,
    updated_date_from: str | None = None,
    updated_date_to: str | None = None,
    view: str | None = "summary",
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of regulatory filings.

    Args:
        added_to_platform_from (Optional[str]): Filter by date added to platform (inclusive start date, YYYY-MM-DDTHH:MM:SSZ format).
        added_to_platform_to (Optional[str]): Filter by date added to platform (inclusive end date, YYYY-MM-DDTHH:MM:SSZ format).
        company (Optional[int]): Filter by internal Company ID.
        company_isin (Optional[str]): Filter by Company ISIN. Case-insensitive.
        countries (Optional[str]): Filter by Company country ISO Alpha-2 code(s). Comma-separated for multiple values (e.g., US,GB,DE).
        language (Optional[str]): Filter by a single filing language ISO 639-1 code (e.g., en).
        languages (Optional[str]): Filter by filing language ISO 639-1 code(s). Comma-separated for multiple values (e.g., en,de).
        lei (Optional[str]): Filter by Company Legal Entity Identifier (LEI).
        on_watchlist (Optional[bool]): Filter by companies on the user's watchlist. Use 'true' to see only watchlist companies, 'false' to exclude them. Omitting the parameter returns all companies.
        ordering (Optional[str]): Which field to use when ordering the results. Available fields: `id`, `release_datetime`, `added_to_platform`. Prefix with '-' for descending order (e.g., `-release_datetime`).
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        release_datetime_from (Optional[str]): Filter by release datetime (inclusive start, YYYY-MM-DDTHH:MM:SSZ format).
        release_datetime_to (Optional[str]): Filter by release datetime (inclusive end, YYYY-MM-DDTHH:MM:SSZ format).
        search (Optional[str]): A search term.
        source (Optional[float]): Filter by a single data source ID.
        sources (Optional[str]): Filter by data source ID(s). Comma-separated for multiple values (e.g., 38,40,51).
        type (Optional[str]): Filter by Filing Type code (e.g., 10-K).
        updated_date_from (Optional[str]): Filter by the date a filing was last updated on the platform (inclusive start, YYYY-MM-DDTHH:MM:SSZ format).
        updated_date_to (Optional[str]): Filter by the date a filing was last updated on the platform (inclusive end, YYYY-MM-DDTHH:MM:SSZ format).
        view (Optional[str]): Controls the level of detail. Omit for a default 'summary' view, or use 'full' to include all details for each filing.
    """
    try:
        query_params = {
            "added_to_platform_from": added_to_platform_from,
            "added_to_platform_to": added_to_platform_to,
            "company": company,
            "company_isin": company_isin,
            "countries": countries,
            "language": language,
            "languages": languages,
            "lei": lei,
            "on_watchlist": on_watchlist,
            "ordering": ordering,
            "page": page,
            "page_size": page_size,
            "release_datetime_from": release_datetime_from,
            "release_datetime_to": release_datetime_to,
            "search": search,
            "source": source,
            "sources": sources,
            "type": type,
            "updated_date_from": updated_date_from,
            "updated_date_to": updated_date_to,
            "view": view,
        }

        path_params = {
        }

        url = f"/filings/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def filings_markdown_retrieve(
    filing_id: int,
    offset: int = 0,
    limit: int = 50000
) -> str:
    """
    **Access Level Required:** Access to full filing content in Markdown requires a **Level 2** Plan or higher.

---
Retrieve the raw processed content of a single filing in Markdown format.
    
    NOTE: This tool uses client-side pagination. If the content is cut off, 
    call this tool again with an increased 'offset'.

    Args:
        filing_id (int): The ID of the filing to retrieve.
        offset (int): Character offset to start reading from (default 0).
        limit (int): Number of characters to read (default 50,000).
    """
    try:
        # 1. Fetch the FULL content (backend does not support range requests)
        url = f"/filings/{filing_id}/markdown/"
        response = await client.get(url)
        
        if response.status_code != 200:
             return f"Error: {response.status_code} {response.reason_phrase}\n{response.text}"

        # 2. Get full text and length
        full_text = response.text
        total_length = len(full_text)
        
        # 3. Slice the text
        end_index = min(offset + limit, total_length)
        chunk = full_text[offset:end_index]
        
        # 4. Construct a helpful status header for the LLM
        header = f"--- MARKDOWN CONTENT (Chars {offset} to {end_index} of {total_length}) ---\n"
        if end_index < total_length:
            header += f"--- WARNING: Content truncated. Call this tool again with offset={end_index} to continue. ---\n"
        
        return header + "\n" + chunk

    except Exception as e:
        return f"Error retrieving markdown: {e}"

@mcp.tool()
async def filings_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve detailed information for a single filing by its ID.

    Args:
        id (int): A unique integer value identifying this filing.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/filings/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_classes_list(
    code: str | None = None,
    code__iexact: str | None = None,
    code__in: list | None = None,
    industry_code: str | None = None,
    industry_group_code: str | None = None,
    name__icontains: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sector_code: str | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of ISIC Classes.

    Args:
        code (Optional[str]): 
        code__iexact (Optional[str]): 
        code__in (Optional[list]): Multiple values may be separated by commas.
        industry_code (Optional[str]): Filter by parent ISIC Group code (e.g., 011)
        industry_group_code (Optional[str]): Filter by grandparent ISIC Division code (e.g., 01)
        name__icontains (Optional[str]): 
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        sector_code (Optional[str]): Filter by great-grandparent ISIC Section code (e.g., A)
    """
    try:
        query_params = {
            "code": code,
            "code__iexact": code__iexact,
            "code__in": code__in,
            "industry_code": industry_code,
            "industry_group_code": industry_group_code,
            "name__icontains": name__icontains,
            "page": page,
            "page_size": page_size,
            "sector_code": sector_code,
        }

        path_params = {
        }

        url = f"/isic-classes/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_classes_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Class by its ID.

    Args:
        id (int): A unique integer value identifying this sub industry.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/isic-classes/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_divisions_list(
    code: str | None = None,
    code__iexact: str | None = None,
    code__in: list | None = None,
    name__icontains: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sector_code: str | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of ISIC Divisions.

    Args:
        code (Optional[str]): 
        code__iexact (Optional[str]): 
        code__in (Optional[list]): Multiple values may be separated by commas.
        name__icontains (Optional[str]): 
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        sector_code (Optional[str]): Filter by parent ISIC Section code (e.g., A)
    """
    try:
        query_params = {
            "code": code,
            "code__iexact": code__iexact,
            "code__in": code__in,
            "name__icontains": name__icontains,
            "page": page,
            "page_size": page_size,
            "sector_code": sector_code,
        }

        path_params = {
        }

        url = f"/isic-divisions/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_divisions_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Division by its ID.

    Args:
        id (int): A unique integer value identifying this industry group.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/isic-divisions/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_groups_list(
    code: str | None = None,
    code__iexact: str | None = None,
    code__in: list | None = None,
    industry_group_code: str | None = None,
    name__icontains: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sector_code: str | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of ISIC Groups.

    Args:
        code (Optional[str]): 
        code__iexact (Optional[str]): 
        code__in (Optional[list]): Multiple values may be separated by commas.
        industry_group_code (Optional[str]): Filter by parent ISIC Division code (e.g., 01)
        name__icontains (Optional[str]): 
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
        sector_code (Optional[str]): Filter by grandparent ISIC Section code (e.g., A)
    """
    try:
        query_params = {
            "code": code,
            "code__iexact": code__iexact,
            "code__in": code__in,
            "industry_group_code": industry_group_code,
            "name__icontains": name__icontains,
            "page": page,
            "page_size": page_size,
            "sector_code": sector_code,
        }

        path_params = {
        }

        url = f"/isic-groups/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_groups_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Group by its ID.

    Args:
        id (int): A unique integer value identifying this industry.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/isic-groups/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_sections_list(
    code: str | None = None,
    code__iexact: str | None = None,
    code__in: list | None = None,
    name__icontains: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of ISIC Sections.

    Args:
        code (Optional[str]): 
        code__iexact (Optional[str]): 
        code__in (Optional[list]): Multiple values may be separated by commas.
        name__icontains (Optional[str]): 
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
    """
    try:
        query_params = {
            "code": code,
            "code__iexact": code__iexact,
            "code__in": code__in,
            "name__icontains": name__icontains,
            "page": page,
            "page_size": page_size,
        }

        path_params = {
        }

        url = f"/isic-sections/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_sections_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Section by its ID.

    Args:
        id (int): A unique integer value identifying this sector.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/isic-sections/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def languages_list(
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a list of all supported languages for filings.

    Args:
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
    """
    try:
        query_params = {
            "page": page,
            "page_size": page_size,
        }

        path_params = {
        }

        url = f"/languages/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def languages_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific language by its ID.

    Args:
        id (int): A unique integer value identifying this Language.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/languages/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def schema_retrieve(
    format: str | None = None,
    lang: str | None = None,
) -> str:
    """
    OpenApi3 schema for this API. Format can be selected via content negotiation.

- YAML: application/vnd.oai.openapi
- JSON: application/vnd.oai.openapi+json

    Args:
        format (Optional[str]): 
        lang (Optional[str]): 
    """
    try:
        query_params = {
            "format": format,
            "lang": lang,
        }

        path_params = {
        }

        url = f"/schema/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def sources_list(
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of all available data sources.

    Args:
        page (Optional[int]): A page number within the paginated result set.
        page_size (Optional[int]): Number of results to return per page.
    """
    try:
        query_params = {
            "page": page,
            "page_size": page_size,
        }

        path_params = {
        }

        url = f"/sources/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def sources_retrieve(
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific data source by its ID.

    Args:
        id (int): A unique integer value identifying this source.
    """
    try:
        query_params = {
        }

        path_params = {
            "id": id,
        }

        url = f"/sources/{id}/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def watchlist_retrieve(
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Fetches all companies currently in the authenticated user's watchlist.

    Args:
    """
    try:
        query_params = {
        }

        path_params = {
        }

        url = f"/watchlist/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

@mcp.tool()
async def downloader_jobs_status_retrieve(
    job_id: str,
) -> str:
    """
    No description available.

    Args:
        job_id (str): 
    """
    try:
        query_params = {
        }

        path_params = {
            "job_id": job_id,
        }

        url = f"/downloader/jobs/{job_id}/status/"
        if path_params:
            url = url.format(**path_params)

        response = await client.get(
            url,
            params={k: v for k, v in query_params.items() if v is not None}
        )

        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"

# --- Main entrypoint ---
def main():
    try:
        mcp.run(transport='stdio')
    finally:
        try:
            asyncio.run(client.aclose())
        except Exception as e:
            print(f"Error closing httpx client: {e}")

if __name__ == "__main__":
    main()
