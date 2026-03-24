import httpx
import yaml
import jinja2
import re
from pathlib import Path
import json
import sys

SCHEMA_URL = "https://financialreports.eu/api/schema/"
OUTPUT_FILE = Path(__file__).parent.parent / "src" / "financial_reports_mcp.py"

# --- UPDATED HEADER FOR FASTAPI & SSE ---
FILE_HEADER_TEMPLATE = """\"\"\"
AUTO-GENERATED FILE by scripts/generate_mcp_tools.py
\"\"\"
import os
import httpx
import json
import asyncio
import contextvars
import uvicorn
from typing import Any, Coroutine, Optional
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sse_starlette.sse import EventSourceResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport

mcp = FastMCP("financial-reports")

# Extract the underlying server object to attach our custom SSE transport
_mcp_server = getattr(mcp, '_mcp_server', None) or getattr(mcp, '_server')

API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.financialreports.eu")

# We use ContextVars to securely pass the token from the FastAPI request into the FastMCP tool context
current_token: contextvars.ContextVar[str] = contextvars.ContextVar("current_token")

app = FastAPI(title="FinancialReports MCP Connector")
security = HTTPBearer()
sse = SseServerTransport("/message")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing Bearer Token")
    return credentials.credentials

@app.get("/sse")
async def handle_sse(request: Request, token: str = Depends(verify_token)):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await _mcp_server.run(streams[0], streams[1], _mcp_server.create_initialization_options())

@app.post("/message")
async def handle_message(request: Request, token: str = Depends(verify_token)):
    # Inject the token into the current async context before executing the tool
    current_token.set(token)
    await sse.handle_post_message(request.scope, request.receive, request._send)

async def get_client() -> httpx.AsyncClient:
    token = current_token.get()
    headers = {
        'Authorization': f'Bearer {token}',
        'User-Agent': 'FinancialReports-MCP-Server/2.0'
    }
    return httpx.AsyncClient(
        base_url=API_BASE_URL,
        headers=headers,
        verify=False,
        timeout=60.0
    )
"""

FUNCTION_DEFINITIONS = """
async def format_response(response: httpx.Response) -> str:
    \"\"\"Formats an httpx.Response into a JSON string for the LLM.\"\"\"
    try:
        response.raise_for_status()
        data = response.json()
        json_string = json.dumps(data, indent=2)
        return f\"\"\"```json\\n{json_string}\\n```\"\"\"
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.status_code} {e.response.reason_phrase}\\nBody: {e.response.text}"
    except Exception as e:
        return f"Error formatting response: {e}"
"""

# --- UPDATED TOOL TEMPLATES TO USE GET_CLIENT() ---
TOOL_TEMPLATE = """
@mcp.tool()
async def {{ func_name }}(
    {%- for param in params %}
    {{ param.name }}: {{ param.py_type }}{{ param.default_val }},
    {%- endfor %}
) -> str:
    \"\"\"
    {{ description }}
    \"\"\"
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

        async with await get_client() as client:
            response = await client.get(
                url,
                params={k: v for k, v in query_params.items() if v is not None}
            )
        return await format_response(response)
    except Exception as e:
        return f"Error calling API: {e}"
"""

MARKDOWN_TOOL_TEMPLATE = """
@mcp.tool()
async def {{ func_name }}(
    filing_id: int,
    offset: int = 0,
    limit: int = 50000
) -> str:
    \"\"\"
    {{ description }}
    \"\"\"
    try:
        url = f"/filings/{filing_id}/markdown/"
        async with await get_client() as client:
            response = await client.get(url)

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
        return f"Error retrieving markdown: {e}"
"""

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
        print(f"Failed to download or parse schema: {e}", file=sys.stderr)
        sys.exit(1)

    env = jinja2.Environment()
    standard_template = env.from_string(TOOL_TEMPLATE)
    markdown_template = env.from_string(MARKDOWN_TOOL_TEMPLATE)

    generated_code = [FILE_HEADER_TEMPLATE, FUNCTION_DEFINITIONS]

    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        if "get" not in path_item:
            continue

        operation = path_item["get"]
        operation_id = operation.get("operationId")
        if not operation_id:
            continue

        func_name = snake_case(operation_id)
        description = operation.get("description", "No description available.").strip()
        formatted_path = re.sub(r'\{([^}]+)\}', r'{\1}', path)

        if func_name == "filings_markdown_retrieve":
            tool_context = {
                "func_name": func_name,
                "description": description,
            }
            generated_code.append(markdown_template.render(tool_context))
            continue

        params = []
        schema_params = operation.get("parameters", [])

        for param in schema_params:
            name = param["name"]
            is_path = param["in"] == "path"
            is_query = param["in"] == "query"
            is_required = param.get("required", False)
            param_schema = param.get("schema", {})
            schema_type = param_schema.get("type")
            schema_format = param_schema.get("format")
            default = param_schema.get("default")

            py_type, py_type_str, default_val = get_python_type(schema_type, schema_format, is_required, default)

            params.append({
                "name": snake_case(name),
                "py_type": py_type,
                "py_type_str": py_type_str,
                "default_val": default_val,
                "description": param.get("description", "").strip(),
                "is_path": is_path,
                "is_query": is_query,
            })

        tool_context = {
            "func_name": func_name,
            "description": description,
            "params": params,
            "path": formatted_path
        }
        generated_code.append(standard_template.render(tool_context))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(generated_code))
        # --- UPDATED ENTRYPOINT TO RUN UVICORN INSTEAD OF STDIO ---
        f.write("\n\nif __name__ == \"__main__\":\n")
        f.write("    uvicorn.run(\"financial_reports_mcp:app\", host=\"0.0.0.0\", port=8000)\n")

    print(f"Successfully generated MCP server tools at: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()