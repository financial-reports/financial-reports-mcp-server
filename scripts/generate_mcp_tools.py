import httpx
import yaml
import jinja2
import re
from pathlib import Path
import json
import asyncio
import sys

SCHEMA_URL = "https://financialreports.eu/api/schema/"
OUTPUT_FILE = Path(__file__).parent.parent / "src" / "financial_reports_mcp.py"

FILE_HEADER_TEMPLATE = """\"\"\"
AUTO-GENERATED FILE by scripts/generate_mcp_tools.py
\"\"\"
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
"""

FUNCTION_DEFINITIONS = """
async def format_response(response: httpx.Response) -> str:
    \"\"\"Formats an httpx.Response into a JSON string for the LLM.\"\"\"
    try:
        response.raise_for_status()
        data = response.json()
        json_string = json.dumps(data, indent=2)
        return f\"\"\"```json\n{json_string}\n```\"\"\"
    except httpx.HTTPStatusError as e:
        return f"Error: {e.response.status_code} {e.response.reason_phrase}\\nBody: {e.response.text}"
    except Exception as e:
        return f"Error formatting response: {e}"
"""

TOOL_TEMPLATE = """
@mcp.tool()
async def {{ func_name }}(
    {%- for param in params %}
    {{ param.name }}: {{ param.py_type }}{{ param.default_val }},
    {%- endfor %}
) -> str:
    \"\"\"
    {{ description }}

    Args:
    {%- for param in params %}
        {{ param.name }} ({{ param.py_type_str }}): {{ param.description }}
    {%- endfor %}
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

    NOTE: This tool uses client-side pagination. If the content is cut off,
    call this tool again with an increased 'offset'.

    Args:
        filing_id (int): The ID of the filing to retrieve.
        offset (int): Character offset to start reading from (default 0).
        limit (int): Number of characters to read (default 50,000).
    \"\"\"
    try:
        url = f"/filings/{filing_id}/markdown/"
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
            print(f"Generating SPECIAL handling for: {func_name}")
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
        f.write("\n\ndef main():\n")
        f.write("    try:\n")
        f.write("        mcp.run(transport='stdio')\n")
        f.write("    finally:\n")
        f.write("        try:\n")
        f.write("            asyncio.run(client.aclose())\n")
        f.write("        except Exception as e:\n")
        f.write("            print(f\"Error closing httpx client: {e}\")\n\n")
        f.write("if __name__ == \"__main__\":\n")
        f.write("    main()\n")

    print(f"Successfully generated MCP server tools at: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()