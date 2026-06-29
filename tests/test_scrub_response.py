"""`markdown_url` is stripped from filing tool output.

The MCP must never surface the auth-gated ``/api/.../markdown/`` URL — it returns
403 for an unauthenticated human. The model reads filing content via
``filings_markdown_retrieve(filing_id)`` (keyed by the ``id`` field, not a URL);
a human gets the public ``viewer_url`` / ``document`` / ``proxy_url`` links,
which are deliberately KEPT.

Two layers:
  1. unit  — ``_scrub_response`` removes ``markdown_url`` anywhere (recursively)
             while preserving the public link fields and the
             extraction-provenance scrub it already performed.
  2. wiring — ``filings_retrieve`` / ``filings_list`` actually run the scrubber
             on the upstream payload before returning it.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

_MD_URL = "https://api.financialreports.eu/filings/46692507/markdown/"
_VIEWER = "https://financialreports.eu/filings/nvidia/10-q/2026/46692507/"
_DOC = "https://cdn.financialreports.eu/raw/46692507.zip"
_PROXY = "https://financialreports.eu/filings/render/46692507/"


# --- 1. unit: _scrub_response ------------------------------------------------


def test_scrub_removes_markdown_url_keeps_public_links(mcp_module) -> None:
    obj = {
        "id": 46692507,
        "markdown_url": _MD_URL,
        "viewer_url": _VIEWER,
        "document": _DOC,
        "proxy_url": _PROXY,
    }
    out = mcp_module._scrub_response(obj)

    assert out is obj  # mutates in place, returns the same object
    assert "markdown_url" not in out
    # Public, human-shareable links are preserved.
    assert out["viewer_url"] == _VIEWER
    assert out["document"] == _DOC
    assert out["proxy_url"] == _PROXY


def test_scrub_removes_markdown_url_in_nested_results(mcp_module) -> None:
    payload = {
        "count": 2,
        "next": "https://api.financialreports.eu/filings/?page=2",
        "previous": None,
        "results": [
            {"id": 1, "markdown_url": _MD_URL, "viewer_url": "v1"},
            {"id": 2, "markdown_url": _MD_URL, "viewer_url": "v2"},
        ],
    }
    out = mcp_module._scrub_response(payload)

    for row in out["results"]:
        assert "markdown_url" not in row
        assert row["viewer_url"]  # kept
    # Pagination metadata is intentionally retained — the scrubber's only job is
    # to drop markdown_url; the LLM-facing nudge keeps the model from handing
    # these /api/ URLs to a human.
    assert out["next"] == "https://api.financialreports.eu/filings/?page=2"
    assert out["count"] == 2


def test_scrub_still_strips_extraction_provenance(mcp_module) -> None:
    # Regression: the original responsibility (hide internal model/prompt) holds.
    obj = {
        "extraction": {
            "model": "secret-internal-model",
            "prompt_version": "v9",
            "extracted_at": "2026-01-01T00:00:00Z",
            "notes": "ok",
        }
    }
    out = mcp_module._scrub_response(obj)

    assert "model" not in out["extraction"]
    assert "prompt_version" not in out["extraction"]
    assert out["extraction"]["extracted_at"] == "2026-01-01T00:00:00Z"
    assert out["extraction"]["notes"] == "ok"


def test_scrub_noop_without_target_fields(mcp_module) -> None:
    obj = {"id": 7, "title": "x", "viewer_url": "v"}
    out = mcp_module._scrub_response(obj)
    assert out == {"id": 7, "title": "x", "viewer_url": "v"}


# --- 2. wiring: the tools actually run the scrubber --------------------------


def test_filings_retrieve_output_schema_omits_markdown_url(mcp_module) -> None:
    # The advertised output_schema must not list a field the runtime always
    # strips — otherwise tools/list still tells the client `markdown_url`
    # exists even though it's never returned.
    tool = mcp_module.mcp._tool_manager._tools["filings_retrieve"]
    assert "markdown_url" not in repr(tool.output_schema)


def _tool(mcp_module, name: str):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


@pytest.mark.asyncio
async def test_filings_retrieve_strips_markdown_url(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/46692507/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 46692507,
                "markdown_url": _MD_URL,
                "viewer_url": _VIEWER,
                "document": _DOC,
                "proxy_url": _PROXY,
                "processing_status": "COMPLETED",
            },
        )
    )

    out = await _tool(mcp_module, "filings_retrieve")(id=46692507)

    assert "markdown_url" not in out
    assert out["viewer_url"] == _VIEWER  # public link survives the round trip
    assert out["document"] == _DOC
    assert out["processing_status"] == "COMPLETED"


def test_format_response_strips_markdown_url(mcp_module) -> None:
    # The text-tool path (_format_response) must scrub too, so the coverage
    # argument doesn't rely on "no text tool ever returns a filing" holding.
    resp = httpx.Response(
        200,
        json={"id": 1, "markdown_url": _MD_URL, "viewer_url": _VIEWER},
        request=httpx.Request("GET", f"{TEST_API_BASE}/filings/1/"),
    )
    out = mcp_module._format_response(resp)
    assert "markdown_url" not in out
    assert "viewer_url" in out  # public link survives


@pytest.mark.asyncio
async def test_filings_list_strips_markdown_url_per_row(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {"id": 46692507, "markdown_url": _MD_URL, "viewer_url": _VIEWER}
                ],
            },
        )
    )

    out = await _tool(mcp_module, "filings_list")()

    row = out["results"][0]
    assert "markdown_url" not in row
    assert row["viewer_url"] == _VIEWER
