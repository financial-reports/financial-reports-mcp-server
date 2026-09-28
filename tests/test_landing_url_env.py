"""The landing page must not be steered by the stale `LANDING_URL` env (#125).

Cloud Run `mcp-connector` sets LANDING_URL to the Claude-only guide, which
overrode #117's client-agnostic default: after v1.4.71 deployed, all 3 doc links
on the live page still pointed ChatGPT and Microsoft 365 Copilot users at the
Claude guide. The service env cannot be read or changed from this repo's
deploy identity, so the setting is renamed: MCP_LANDING_URL is the override,
and the legacy name is ignored (with a startup warning so ops can remove it).
"""
from __future__ import annotations

import importlib

LEGACY = "https://financialreports.eu/integrations/claude/"
DEFAULT = "https://financialfilings.com/mcp/"


def _reload(mcp_module):
    return importlib.reload(mcp_module)


def test_legacy_landing_url_env_no_longer_overrides_the_default(
    mcp_module, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("LANDING_URL", LEGACY)
    monkeypatch.delenv("MCP_LANDING_URL", raising=False)
    # The module's _configure_logging() runs basicConfig(force=True) on reload,
    # which removes caplog's handler; its stderr handler is what ops sees anyway.
    m = _reload(mcp_module)
    assert m.LANDING_URL == DEFAULT
    assert m.WEBSITE_URL == DEFAULT
    err = capsys.readouterr().err
    assert "LANDING_URL is set but no longer read" in err
    assert "MCP_LANDING_URL" in err


def test_mcp_landing_url_env_is_the_override(mcp_module, monkeypatch) -> None:
    monkeypatch.setenv("MCP_LANDING_URL", "https://example.test/guide/")
    monkeypatch.setenv("LANDING_URL", LEGACY)
    m = _reload(mcp_module)
    assert m.LANDING_URL == "https://example.test/guide/"


def test_default_when_neither_is_set(mcp_module, monkeypatch) -> None:
    monkeypatch.delenv("MCP_LANDING_URL", raising=False)
    monkeypatch.delenv("LANDING_URL", raising=False)
    m = _reload(mcp_module)
    assert m.LANDING_URL == DEFAULT
