"""The Claude Code plugin, its marketplace and the registry entry must agree.

The plugin lives in its own folder, `plugins/financialfilings/`, because
Anthropic's plugin directory bundles the whole plugin folder and holds any
version with a file over 256 KiB for a reviewer (`scripts/openapi.snapshot.json`
and `scripts/generate_mcp_tools.py` are both over that). The repo root keeps
its own copy of the skill, `.mcp.json` and icon for everything that reads them
from there (the Cursor plugin, `cp -R skills/...` installs), so these tests
also require the two copies to stay identical.

`claude plugin validate` checks each manifest's shape; it does not check that
they point at the same server, or that the copies agree. These do.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "financialfilings"
SKILL = Path("skills") / "financial-filings-research"

# Anthropic plugin directory limits (claude.com/docs/plugins/pre-submission-checklist).
MAX_FILE_BYTES = 256 * 1024
MAX_FILES = 512
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree(base: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(base)): p.read_bytes()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def test_marketplace_lists_the_plugin_folder():
    plugin = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    market = _load(ROOT / ".claude-plugin" / "marketplace.json")
    entries = [p for p in market["plugins"] if p["name"] == plugin["name"]]
    assert len(entries) == 1, market["plugins"]
    assert (ROOT / entries[0]["source"]).resolve() == PLUGIN


def test_plugin_mcp_server_is_the_registry_remote():
    remotes = {r["url"] for r in _load(ROOT / "server.json")["remotes"]}
    servers = _load(PLUGIN / ".mcp.json")["mcpServers"]
    assert len(servers) == 1, servers
    (server,) = servers.values()
    assert server["type"] == "http"
    assert server["url"] in remotes, (server["url"], remotes)


def test_plugin_copies_match_the_root():
    assert _tree(PLUGIN / SKILL) == _tree(ROOT / SKILL), (
        "plugins/financialfilings/skills/ and skills/ differ: edit both, or copy one over the other"
    )
    for rel in (".mcp.json", "LICENSE", "assets/icon.png"):
        assert (PLUGIN / rel).read_bytes() == (ROOT / rel).read_bytes(), rel


def test_plugin_paths_resolve_inside_the_plugin_folder():
    manifest = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    icon = (PLUGIN / manifest["icon"]).resolve()
    assert icon.is_file() and PLUGIN in icon.parents, manifest["icon"]
    assert (PLUGIN / SKILL / "SKILL.md").is_file()


def test_plugin_folder_fits_the_directory_limits():
    files = [p for p in PLUGIN.rglob("*") if p.is_file() or p.is_symlink()]
    assert len(files) <= MAX_FILES
    assert not [p for p in files if p.is_symlink()]
    too_big = [
        (str(p.relative_to(PLUGIN)), p.stat().st_size)
        for p in files
        if p.suffix.lower() not in IMAGE_SUFFIXES and p.stat().st_size >= MAX_FILE_BYTES
    ]
    assert not too_big, too_big
