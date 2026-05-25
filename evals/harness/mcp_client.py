"""Model-agnostic MCP client over Streamable HTTP with a static bearer token.

We deliberately do NOT do the interactive OAuth dance here — a headless eval
can't open a browser. The caller supplies a pre-obtained access token
(FR_MCP_TOKEN, or one minted via cognito_token.py). The same client serves
every model adapter, so Claude and DeepSeek see the identical tool surface.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPSession:
    """Thin wrapper over an initialized MCP ClientSession."""

    def __init__(self, session: ClientSession):
        self._session = session

    async def list_tools(self) -> list[ToolSpec]:
        resp = await self._session.list_tools()
        return [
            ToolSpec(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
            )
            for t in resp.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Returns (text, ok). ok=False when the tool reported isError."""
        result = await self._session.call_tool(name, arguments or {})
        parts: list[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
            else:
                parts.append(str(getattr(block, "data", block)))
        return "\n".join(parts), not bool(getattr(result, "isError", False))


@asynccontextmanager
async def open_mcp(url: str, token: str) -> AsyncIterator[MCPSession]:
    """Open + initialize an MCP session against a remote Streamable HTTP server."""
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield MCPSession(session)
