"""The Claude Code plugin, its marketplace and the registry entry must agree.

`claude plugin validate` checks each manifest's own shape; it does not check
that they point at the same server. These do.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_marketplace_lists_this_repo_as_the_plugin():
    plugin = _load(".claude-plugin/plugin.json")
    market = _load(".claude-plugin/marketplace.json")
    entries = [p for p in market["plugins"] if p["name"] == plugin["name"]]
    assert len(entries) == 1, market["plugins"]
    assert entries[0]["source"] == "./"


def test_plugin_mcp_server_is_the_registry_remote():
    remotes = {r["url"] for r in _load("server.json")["remotes"]}
    servers = _load(".mcp.json")["mcpServers"]
    assert len(servers) == 1, servers
    (server,) = servers.values()
    assert server["type"] == "http"
    assert server["url"] in remotes, (server["url"], remotes)


def test_plugin_ships_the_skill():
    assert (ROOT / "skills" / "financial-filings-research" / "SKILL.md").is_file()
