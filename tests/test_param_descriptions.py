"""Tool parameters carry the schema's descriptions (#132 item 3).

The generator emitted bare `type: str | None`, so the model saw no guidance on
the parameter itself — while the REST schema's `type`/`types` descriptions
already say "taxonomy codes, not regulator form names". 83 unknown-filing-type
400s in 30 days of prod traffic were models passing form names there.
"""
from __future__ import annotations

import pytest


def _input_schema(mcp_module, tool_name):
    tool = mcp_module.mcp._tool_manager._tools[tool_name]
    return tool.parameters


@pytest.mark.parametrize(
    "tool_name,param,must_contain",
    [
        ("filings_list", "types", "not regulator form names"),
        ("filings_list", "type", "not regulator form names"),
        ("filings_list", "source_filing_type", "regulator's own form name"),
        ("companies_financials_retrieve", "line_items", "Unknown codes return"),
    ],
)
def test_param_description_reaches_the_input_schema(
    mcp_module, tool_name, param, must_contain
) -> None:
    props = _input_schema(mcp_module, tool_name)["properties"]
    assert param in props, sorted(props)
    assert must_contain in props[param].get("description", "")


def test_params_without_a_schema_description_get_none(mcp_module) -> None:
    """No invented text: a param the schema leaves undescribed stays so."""
    import json
    import os

    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    op = snap["paths"]["/filings/"]["get"]
    undescribed = [
        p["name"] for p in op["parameters"] if p.get("in") == "query" and not p.get("description")
    ]
    props = _input_schema(mcp_module, "filings_list")["properties"]
    for name in undescribed:
        if name in props:
            assert "description" not in props[name], name


def test_only_allowlisted_params_are_described(mcp_module) -> None:
    """Token cost: every description is sent on every session. Emitting all of
    them measured +2,774 tokens on tools/list; only the allowlist is emitted."""
    allowed = mcp_module_allowlist()
    for name in ("filings_list", "companies_list", "companies_financials_retrieve"):
        for pname, prop in _input_schema(mcp_module, name)["properties"].items():
            if "description" in prop:
                assert pname in allowed, (name, pname)


def mcp_module_allowlist():
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_mcp_tools.py")
    spec = importlib.util.spec_from_file_location("_gen_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._DESCRIBED_PARAMS


def test_descriptions_are_capped(mcp_module) -> None:
    for name in ("filings_list", "companies_list", "companies_financials_retrieve"):
        for pname, prop in _input_schema(mcp_module, name)["properties"].items():
            assert len(prop.get("description", "")) <= 320, (name, pname)
