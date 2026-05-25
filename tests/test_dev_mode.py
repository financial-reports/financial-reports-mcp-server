"""DEV_MODE_API_KEY auth bypass — local-development only."""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator

import pytest


@pytest.fixture()
def dev_mode_module(respx_router, monkeypatch) -> Iterator[object]:
    """Re-import the MCP module with DEV_MODE_API_KEY set."""
    monkeypatch.setenv("DEV_MODE_API_KEY", "fr_test_devkey_abc123")
    # Force MCP_BASE_URL to a non-prod hostname so the prod guard does not trip.
    monkeypatch.setenv("MCP_BASE_URL", "http://localhost:8000")
    sys.modules.pop("src.financial_reports_mcp", None)
    import src.financial_reports_mcp as m  # type: ignore
    importlib.reload(m)
    yield m


def test_dev_mode_config_exposed(dev_mode_module) -> None:
    """The generated module reads DEV_MODE_API_KEY at import time."""
    assert dev_mode_module.DEV_MODE_API_KEY == "fr_test_devkey_abc123"
