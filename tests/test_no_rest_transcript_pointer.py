"""No tool description points at the REST transcript route: MCP credentials can't call it."""
from __future__ import annotations


def test_no_tool_description_points_at_rest_transcript(mcp_module) -> None:
    offenders = [
        name
        for name, tool in mcp_module.mcp._tool_manager._tools.items()
        if "/transcript/" in (tool.description or "")
    ]
    assert not offenders


def test_markdown_description_keeps_the_transcript_layout(mcp_module) -> None:
    desc = mcp_module.mcp._tool_manager._tools["filings_markdown_retrieve"].description
    assert "labelled by speaker." in desc
