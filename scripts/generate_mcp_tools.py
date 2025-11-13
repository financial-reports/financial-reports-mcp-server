import httpx
import yaml
import jinja2
import re
from pathlib import Path
import json

SCHEMA_URL = "https://financialreports.eu/api/schema/"
OUTPUT_FILE = Path(__file__).parent.parent / "src" / "worker.py"

# --- TEMPLATE START ---

FILE_HEADER_TEMPLATE = """
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
        return f\"\"\"```json
{json_string}
```\"\"\"
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.status_code} {e.response.reason_phrase}\\nBody: {e.response.text}"
    except Exception as e:
        return f"Error formatting response: {e}"
"""

TOOL_TEMPLATE = """
@mcp.tool()
async def {{ func_name }}(
    ctx,
    {%- for param in params %}
    {{ param.name }}: {{ param.py_type }}{{ param.default_val }},
    {%- endfor %}
) -> str:
    \"\"\"
    {{ description }}
    \"\"\"
    # Get the API Key passed from the Worker Entrypoint
    api_key = ctx.request_context.lifespan_context.get("api_key")
    if not api_key:
        return "Error: No API Key provided. Please add ?api_key=YOUR_KEY to your MCP server URL."

    client = get_client(api_key)
    
    try:
        query_params = {
            {%- for param in params if param.is_query %}
            "{{ param.name }}": {{ param.name }},
            {%- endfor %}
        }
        path_params = {
            {%- for param in params if param.is_path %}
            "{{ param.name }}": {{ param.name }},
            {%- endfor %}
        }
        url = f"{{ path }}"
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
"""

MARKDOWN_TOOL_TEMPLATE = """
@mcp.tool()
async def {{ func_name }}(
    ctx,
    filing_id: int,
    offset: int = 0,
    limit: int = 50000
) -> str:
    \"\"\"
    {{ description }}
    NOTE: Client-side pagination enabled.
    \"\"\"
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
             return f"Error: {response.status_code} {response.reason_phrase}\\n{response.text}"

        full_text = response.text
        total_length = len(full_text)
        end_index = min(offset + limit, total_length)
        chunk = full_text[offset:end_index]
        
        header = f"--- MARKDOWN CONTENT (Chars {offset} to {end_index} of {total_length}) ---\\n"
        if end_index < total_length:
            header += f"--- WARNING: Content truncated. Call this tool again with offset={end_index} to continue. ---\\n"
        
        return header + "\\n" + chunk

    except Exception as e:
        await client.aclose()
        return f"Error retrieving markdown: {e}"
"""

# Cloudflare Worker that reads ?api_key=...
WORKER_TEMPLATE = """
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
"""

# --- TEMPLATE END ---

def get_python_type(schema_type, schema_format=None, is_required=True, default=None):
    py_type = "Any"
    if schema_type == "integer": py_type = "int"
    elif schema_type == "number": py_type = "float"
    elif schema_type == "string": py_type = "str"
    elif schema_type == "boolean": py_type = "bool"
    elif schema_type == "array": py_type = "list"
    elif schema_type == "object": py_type = "dict"
    
    py_type_str = py_type
    default_val = ""

    if not is_required:
        py_type = f"{py_type} | None"
        py_type_str = f"Optional[{py_type_str}]"
        default_val = " = None"

    if default is not None:
        if schema_type == "string":
            default_val = f' = "{default}"'
        else:
            default_val = f" = {default}"

    if is_required and default is None:
         default_val = ""

    return py_type, py_type_str, default_val

def snake_case(s):
    s = re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
    return re.sub(r'[^a-z0-9_]+', '_', s).strip('_')

def main():
    try:
        response = httpx.get(SCHEMA_URL)
        response.raise_for_status()
        schema = yaml.safe_load(response.content)
    except Exception as e:
        print(f"Failed to download or parse schema: {e}")
        return

    env = jinja2.Environment()
    standard_template = env.from_string(TOOL_TEMPLATE)
    markdown_template = env.from_string(MARKDOWN_TOOL_TEMPLATE)

    generated_code = [FILE_HEADER_TEMPLATE]

    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        if "get" not in path_item:
            continue
        operation = path_item["get"]
        operation_id = operation.get("operationId")
        if not operation_id: continue
        func_name = snake_case(operation_id)
        description = operation.get("description", "No description available.").strip()
        formatted_path = re.sub(r'\{([^}]+)\}', r'{\1}', path)

        if func_name == "filings_markdown_retrieve":
            tool_context = {"func_name": func_name, "description": description}
            generated_code.append(markdown_template.render(tool_context))
            continue

        params = []
        schema_params = operation.get("parameters", [])
        for param in schema_params:
            name = param["name"]
            py_type, py_type_str, default_val = get_python_type(param.get("schema", {}).get("type"), param.get("schema", {}).get("format"), param.get("required", False), param.get("schema", {}).get("default"))
            params.append({"name": snake_case(name), "py_type": py_type, "py_type_str": py_type_str, "default_val": default_val, "description": param.get("description", "").strip(), "is_path": param["in"] == "path", "is_query": param["in"] == "query"})

        tool_context = {"func_name": func_name, "description": description, "params": params, "path": formatted_path}
        generated_code.append(standard_template.render(tool_context))

    generated_code.append(WORKER_TEMPLATE)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(generated_code))
    print(f"Successfully generated Cloudflare Worker code at: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
