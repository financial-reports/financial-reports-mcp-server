"""Text sent to the model must not name a regulator (#178).

We do not disclose sourcing in customer-facing copy, and server text reaches
customers through the model's answers: one answer called a filing "a later SEC
filing". Form-to-code translation stays, because it is how a caller holding
"10-Q" finds `IR`; only the regulator's name goes.
"""
from __future__ import annotations

import re

NAMED_REGULATOR = re.compile(r"\b(SEC|ESMA|ASX|EDGAR|FCA|BaFin)\b")
CLIENT_INSTRUCTION_CAP = 4096


def test_instructions_name_no_regulator(mcp_module) -> None:
    assert not NAMED_REGULATOR.findall(mcp_module.mcp.instructions)


def test_filing_type_guide_names_no_regulator(mcp_module) -> None:
    assert not NAMED_REGULATOR.findall(mcp_module._resource_filing_types.fn())


def test_tool_descriptions_name_no_regulator(mcp_module) -> None:
    offenders = {
        name: NAMED_REGULATOR.findall(tool.description or "")
        for name, tool in mcp_module.mcp._tool_manager._tools.items()
    }
    assert not {name: hits for name, hits in offenders.items() if hits}


def test_instructions_tell_the_model_how_to_describe_provenance(mcp_module) -> None:
    """Removing the words is not enough: a model can still name the regulator
    from a filing title or its own knowledge, so the rule has to be stated."""
    text = mcp_module.mcp.instructions
    assert "official filing authorities" in text
    assert "Never name a regulator" in text
    assert "unless the user asked about that form" in text


def test_key_guidance_survives_the_client_instruction_cap(mcp_module) -> None:
    """Claude Code cuts server instructions at 4096 characters (measured
    2026-11-02: rule text stopped at exactly that offset, mid-sentence). Text
    past the cap never reaches the model, so what must arrive has to sit before it.
    """
    delivered = mcp_module.mcp.instructions[:CLIENT_INSTRUCTION_CAP]
    assert "unless the user asked about that form" in delivered
    for resource in (
        "fr://guide/filing-types",
        "fr://guide/industry-classification",
        "fr://guide/markdown-strategy",
    ):
        assert resource in delivered, f"{resource} is cut off by the client cap"
    assert "values missing from the normalised financials" in delivered


def test_form_check_is_not_worded_as_repeating_it_to_the_user(mcp_module) -> None:
    """"READ IT BACK" meant check the field, but reads as "say it to the user"."""
    assert "READ IT BACK" not in mcp_module.mcp.instructions
