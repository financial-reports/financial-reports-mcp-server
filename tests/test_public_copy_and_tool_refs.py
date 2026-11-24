"""Public copy states no data origin (#181), and server text names only tools the
default surface serves (#182)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_mcp_tools import _PRUNED_EXCLUDE  # noqa: E402

ORIGIN_CLAIM = re.compile(
    r"official regulators|securities regulators|straight from|sourced (directly )?from"
    r"|internal sourcing system|official filing authorit|source regulators",
    re.IGNORECASE,
)
PUBLIC_COPY = (
    "README.md",
    "README.zh-CN.md",
    "server.json",
    ".cursor-plugin/plugin.json",
    "plugins/financialfilings/README.md",
    "plugins/financialfilings/.claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "gemini-extension.json",
    "glama.json",
    "skills/README.md",
    "skills/financial-filings-research/SKILL.md",
    "skills/financial-filings-research/references/tool-cheatsheet.md",
    # Landing page and server instructions are inline in the generator.
    "scripts/generate_mcp_tools.py",
)
PHRASE = "official filings, as published"
# The registry rejects longer descriptions, and versions there are immutable.
REGISTRY_DESCRIPTION_LIMIT = 100


@pytest.mark.parametrize("rel_path", PUBLIC_COPY)
def test_public_copy_states_no_origin(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert not ORIGIN_CLAIM.findall(text), f"{rel_path} says where the data comes from"


def test_instructions_use_the_agreed_phrase(mcp_module) -> None:
    assert PHRASE in mcp_module.mcp.instructions


def test_landing_page_uses_the_agreed_phrase() -> None:
    generator = (REPO_ROOT / "scripts/generate_mcp_tools.py").read_text(encoding="utf-8")
    assert generator.count("Official filings, as published.") == 1, "landing page footer"
    assert "to official filings, as published, from listed companies" in generator


def test_registry_description_fits_the_limit() -> None:
    server = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
    assert len(server["description"]) <= REGISTRY_DESCRIPTION_LIMIT


def test_registry_description_uses_the_agreed_phrase() -> None:
    """Lower case, so the listing never opens with "Official" next to our name."""
    server = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
    assert PHRASE in server["description"]


def test_generated_server_names_no_pruned_tool(mcp_module) -> None:
    """A client told about a tool the default surface removes will try to call it.
    Scanning the whole module covers instructions, guides, prompts and errors."""
    text = Path(mcp_module.__file__).read_text(encoding="utf-8")
    pruned = re.compile(r"\b(" + "|".join(sorted(_PRUNED_EXCLUDE)) + r")\b")
    assert not sorted(set(pruned.findall(text)))


def test_default_surface_does_not_offer_watchlist_management(mcp_module) -> None:
    """Prose has no tool name for the check above to catch. `on_watchlist` stays:
    it filters on a watchlist the user keeps on the website."""
    companies_list = mcp_module.mcp._tool_manager._tools["companies_list"]
    assert "watchlist" not in mcp_module.mcp.instructions.lower()
    assert "watchlist" not in companies_list.description.lower()


def test_public_docs_do_not_promise_alerts_or_webhooks() -> None:
    assert "Alert me when" not in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "提醒我" not in (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    assert "webhooks" not in (REPO_ROOT / "skills/README.md").read_text(encoding="utf-8")


# Names a reader compares us against, the client a limit was measured on, and a
# coverage claim that went stale once standardised financials went global.
NAMED_THIRD_PARTY = re.compile(
    r"Capital IQ|Bloomberg|FactSet|Refinitiv|\bWRDS\b|Compustat|Claude\.ai|ESEF/EU-derived",
    re.IGNORECASE,
)


def test_tool_text_names_no_third_party(mcp_module) -> None:
    texts = {"instructions": mcp_module.mcp.instructions}
    texts.update(
        {name: tool.description or "" for name, tool in mcp_module.mcp._tool_manager._tools.items()}
    )
    offenders = {name: NAMED_THIRD_PARTY.findall(text) for name, text in texts.items()}
    assert not {name: hits for name, hits in offenders.items() if hits}


def test_capped_upstream_description_ends_on_a_sentence() -> None:
    from generate_mcp_tools import _cap_at_sentence

    text = "First sentence. " + "word " * 400
    cut = _cap_at_sentence(text, 1500)
    assert cut == "First sentence."
    no_stop = "word " * 400
    cut = _cap_at_sentence(no_stop, 1500)
    assert len(cut) <= 1503 and cut.endswith("word...")
    assert _cap_at_sentence("Short.", 1500) == "Short."


def test_financials_description_is_not_cut_mid_word(mcp_module) -> None:
    """The upstream text is over the cap; the bare slice ended it on "A l..."."""
    description = mcp_module.mcp._tool_manager._tools["companies_financials_retrieve"].description
    upstream = description.split("**When to use this tool:**")[0].rstrip()
    assert upstream.endswith("."), upstream[-80:]
