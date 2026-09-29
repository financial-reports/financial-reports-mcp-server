"""A null enum value must not make FastMCP reject a whole structured result.

drf-spectacular renders a described enum as `{"allOf": [{"$ref": <Enum>}],
"description": ...}`. `_make_fields_nullable` deliberately skips combinator
nodes, so such a property stayed enum-only, and a null `processing_status`
failed output validation for the ENTIRE `filings_list` / `filings_retrieve`
result. The API does null it (the #106 guidance says null means unknown), so
the proxy must accept it. Invalid non-null values must still be rejected.
"""
from __future__ import annotations

import jsonschema
import pytest


def _property_nodes(schema, prop):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if prop in node.get("properties", {}):
                found.append(node["properties"][prop])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return found


def _validator(root, node):
    wrapped = dict(node)
    for key in ("$defs", "definitions"):
        if key in root:
            wrapped[key] = root[key]
    return jsonschema.Draft202012Validator(wrapped)


@pytest.mark.parametrize("tool_name", ["filings_list", "filings_retrieve"])
def test_processing_status_accepts_null_and_rejects_garbage(mcp_module, tool_name) -> None:
    schema = mcp_module.mcp._tool_manager._tools[tool_name].output_schema
    nodes = _property_nodes(schema, "processing_status")
    assert nodes, f"{tool_name}: processing_status not in output_schema"
    for node in nodes:
        v = _validator(schema, node)
        assert v.is_valid(None), f"{tool_name}: null rejected by {node!r}"
        assert v.is_valid("COMPLETED"), f"{tool_name}: COMPLETED rejected"
        assert not v.is_valid("NOT_A_STATUS"), f"{tool_name}: enum no longer enforced"
