"""What Claude's connector directory requires of every served tool.

The developer portal flags a tool without a `title` or without a
`readOnlyHint`/`destructiveHint` annotation, and reviewers reject tool names
over 64 characters (claude.com/docs/connectors/building/review-criteria).
The listing reads the tools live from the server, so a generator change that
drops an annotation would surface there first; this catches it in CI instead.
"""

from __future__ import annotations

import asyncio

MAX_TOOL_NAME = 64


def _served_tools(mcp_module):
    tools = asyncio.run(mcp_module.mcp.get_tools())
    return [t.to_mcp_tool() for t in tools.values()]


def test_every_tool_has_a_title_and_a_safety_hint(mcp_module) -> None:
    missing = []
    for tool in _served_tools(mcp_module):
        hints = tool.annotations
        if not tool.title or hints is None or not hints.title:
            missing.append((tool.name, "title"))
        if hints is None or (
            hints.readOnlyHint is None and hints.destructiveHint is None
        ):
            missing.append((tool.name, "readOnlyHint/destructiveHint"))
    assert not missing, missing


def test_every_tool_name_fits_the_directory_limit(mcp_module) -> None:
    too_long = [
        t.name for t in _served_tools(mcp_module) if len(t.name) > MAX_TOOL_NAME
    ]
    assert not too_long, too_long
