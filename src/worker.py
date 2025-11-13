
import os
import httpx
import json
import asyncio
from mcp.server.fastmcp import FastMCP
from js import Response, URL

# Initialize FastMCP
mcp = FastMCP("financial-reports")

# --- HELPER: Dynamic Client ---
def get_client(api_key: str) -> httpx.AsyncClient:
    headers = {
        'X-API-Key': api_key,
        'User-Agent': 'FinancialReports-MCP-Server/1.1'
    }
    return httpx.AsyncClient(
        base_url="https://api.financialreports.eu",
        headers=headers,
        verify=False, 
        timeout=30.0
    )

async def format_response(response: httpx.Response) -> str:
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
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def companies_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve detailed information for a single company by its internal ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def countries_list(
    ctx,
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a list of all supported countries.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def countries_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific country by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def filing_types_list(
    ctx,
    page: int | None = None,
    page_size: int | None = None,
    search: str | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of all available filing types.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def filing_types_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific filing type by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def filings_list(
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def filings_markdown_retrieve(
    ctx,
    filing_id: int,
    offset: int = 0,
    limit: int = 50000
) -> str:
    """
    **Access Level Required:** Access to full filing content in Markdown requires a **Level 2** Plan or higher.

---
Retrieve the raw processed content of a single filing in Markdown format.
    NOTE: Client-side pagination enabled.
    """
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)

    try:
        # 1. Fetch the FULL content
        url = f"/filings/{filing_id}/markdown/"
        response = await client.get(url)
        await client.aclose()
        
        if response.status_code != 200:
             return f"Error: {response.status_code} {response.reason_phrase}\n{response.text}"

        full_text = response.text
        total_length = len(full_text)
        end_index = min(offset + limit, total_length)
        chunk = full_text[offset:end_index]
        
        header = f"--- MARKDOWN CONTENT (Chars {offset} to {end_index} of {total_length}) ---\n"
        if end_index < total_length:
            header += f"--- WARNING: Content truncated. Call this tool again with offset={end_index} to continue. ---\n"
        
        return header + "\n" + chunk

    except Exception as e:
        await client.aclose()
        return f"Error retrieving markdown: {e}"

@mcp.tool()
async def filings_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve detailed information for a single filing by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_classes_list(
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_classes_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Class by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_divisions_list(
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_divisions_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Division by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_groups_list(
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_groups_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Group by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_sections_list(
    ctx,
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
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def isic_sections_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific ISIC Section by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def languages_list(
    ctx,
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a list of all supported languages for filings.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def languages_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific language by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def schema_retrieve(
    ctx,
    format: str | None = None,
    lang: str | None = None,
) -> str:
    """
    OpenApi3 schema for this API. Format can be selected via content negotiation.

- YAML: application/vnd.oai.openapi
- JSON: application/vnd.oai.openapi+json
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def sources_list(
    ctx,
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve a paginated list of all available data sources.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def sources_retrieve(
    ctx,
    id: int,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Retrieve details for a specific data source by its ID.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def watchlist_retrieve(
    ctx,
) -> str:
    """
    **Access Level Required:** Requires **Level 1** Plan or higher.

---
Fetches all companies currently in the authenticated user's watchlist.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

@mcp.tool()
async def downloader_jobs_status_retrieve(
    ctx,
    job_id: str,
) -> str:
    """
    No description available.
    """
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
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
        await client.aclose()
        return await format_response(response)
    except Exception as e:
        await client.aclose()
        return f"Error calling API: {e}"

# --- CLOUDFLARE DURABLE OBJECT ---
class FinancialReportsServer(DurableObject):
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env
        self.app = mcp.sse_app()

    async def fetch(self, request):
        import asgi
        
        # EXTRACT API KEY FROM URL QUERY PARAMS
        # Using JS URL object for reliability in the Worker environment
        url_obj = URL.new(request.url)
        api_key = url_obj.searchParams.get("api_key")
        
        # Inject into context
        scope_extras = {
            "lifespan_context": {"api_key": api_key}
        }
        
        return await asgi.fetch(self.app, request, self.env, self.ctx, scope=scope_extras)

# Worker Entrypoint
async def on_fetch(request, env):
    # Route everything to the Durable Object
    id = env.FinancialReports.idFromName("singleton")
    stub = env.FinancialReports.get(id)
    return await stub.fetch(request)
