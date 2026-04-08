"""Self-contained probe: boots a minimal MCP server in a background thread,
hits initialize + tools/list, prints everything we need to know about icons
and the streamable HTTP transport. No bash glue."""
import asyncio
import json
import threading
import time
import httpx
import uvicorn

from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Icon

import fastmcp
import mcp as mcp_pkg

print("=" * 60)
print("VERSIONS")
print("=" * 60)
print(f"  fastmcp: {fastmcp.__version__}")
print(f"  mcp:     {getattr(mcp_pkg, '__version__', 'unknown')}")

mcp = FastMCP(
    "financial-reports-probe",
    icons=[Icon(
        src="https://cdn.financialreports.eu/financialreports/static/assets/favicon/new/favicon.ico",
        mimeType="image/x-icon",
    )],
)

@mcp.tool()
async def hello() -> str:
    """A test tool."""
    return "world"

_mcp_server = getattr(mcp, "_mcp_server", None) or getattr(mcp, "_server")

print()
print("=" * 60)
print("FastMCP INTROSPECTION")
print("=" * 60)
print(f"  has streamable_http_app:    {hasattr(mcp, 'streamable_http_app')}")
print(f"  has http_app:               {hasattr(mcp, 'http_app')}")
print(f"  has sse_app:                {hasattr(mcp, 'sse_app')}")
print(f"  server name:                {getattr(_mcp_server, 'name', None)}")

try:
    init_options = _mcp_server.create_initialization_options()
    print(f"  init_options type:          {type(init_options).__name__}")
    # Try to dump to dict to see icons location
    if hasattr(init_options, "model_dump"):
        dumped = init_options.model_dump(exclude_none=True)
        print(f"  init_options dump:")
        print("    " + json.dumps(dumped, indent=2, default=str).replace("\n", "\n    "))
    else:
        print(f"  init_options repr:          {init_options!r}")
except Exception as e:
    print(f"  init_options error:         {e}")

# Check capabilities directly
try:
    caps = _mcp_server.get_capabilities(notification_options=None, experimental_capabilities={})
    print(f"  capabilities: {caps}")
except Exception as e:
    print(f"  capabilities error: {e}")

session_manager = StreamableHTTPSessionManager(
    app=_mcp_server,
    event_store=None,
    json_response=True,
    stateless=True,
)

async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)

@asynccontextmanager
async def lifespan(app):
    async with session_manager.run():
        yield

app = Starlette(routes=[Mount("/", app=handle_mcp)], lifespan=lifespan)


def run_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


print()
print("=" * 60)
print("BOOTING SERVER IN BACKGROUND THREAD")
print("=" * 60)
t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2.5)
print("  server up")

print()
print("=" * 60)
print("INITIALIZE REQUEST")
print("=" * 60)
with httpx.Client(timeout=10.0) as client:
    init_resp = client.post(
        "http://127.0.0.1:8765/",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "diag", "version": "0"},
            },
        },
    )
    print(f"  status: {init_resp.status_code}")
    print(f"  headers:")
    for k, v in init_resp.headers.items():
        print(f"    {k}: {v}")
    print(f"  body:")
    body_text = init_resp.text
    # Try parse as SSE
    if body_text.startswith("event:") or "data:" in body_text:
        for line in body_text.splitlines():
            if line.startswith("data:"):
                try:
                    parsed = json.loads(line[5:].strip())
                    print(json.dumps(parsed, indent=2))
                except Exception:
                    print(line)
            else:
                print(line)
    else:
        try:
            print(json.dumps(init_resp.json(), indent=2))
        except Exception:
            print(body_text)

    session_id = init_resp.headers.get("mcp-session-id")
    print()
    print(f"  >>> EXTRACTED session_id: {session_id!r}")

    if session_id:
        # Notifications/initialized
        print()
        print("=" * 60)
        print("notifications/initialized")
        print("=" * 60)
        notif_resp = client.post(
            "http://127.0.0.1:8765/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        print(f"  status: {notif_resp.status_code}")

        print()
        print("=" * 60)
        print("tools/list")
        print("=" * 60)
        tools_resp = client.post(
            "http://127.0.0.1:8765/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        print(f"  status: {tools_resp.status_code}")
        body = tools_resp.text
        if "data:" in body:
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        parsed = json.loads(line[5:].strip())
                        print(json.dumps(parsed, indent=2)[:1500])
                    except Exception:
                        print(line[:1500])
        else:
            print(body[:1500])

print()
print("=" * 60)
print("DONE")
print("=" * 60)
