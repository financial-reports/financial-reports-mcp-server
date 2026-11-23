"""As-reported facts tools (web#10586, built in web#4964).

Two hand-written tools, 1:1 with the per-filing REST endpoints
(/filings/{id}/facts/, /filings/{id}/statements/). They are always emitted into
the generated module but registered only when MCP_UNSTD_FACTS_TOOLS=1, so the
default surface (prod, docs/token-budget.md, README) never lists them until the
routes are public (web#10584). The company series routes stay out.

Upstream bodies below are trimmed copies of real responses from the web repo's
views over the facts corpus, not invented shapes.
"""
from __future__ import annotations

import importlib
import json

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

UNSTD_TOOLS = (
    "filings_facts",
    "filings_statements",
)

FACTS_BODY = {
    "count": 64,
    "next": "https://api.financialreports.eu/filings/42817733/facts/?method=llm&page=2&page_size=5&statement=IS",
    "previous": None,
    "results": [
        {
            "label": "Terreinen en gebouwen", "statement": "IS", "scope": "consolidated",
            "value": "15623000", "unit": "EUR",
            "period": {"start": "2025-01-01", "end": "2025-12-31", "fiscal_label": "FY2025"},
            "method": "llm", "status": "accepted", "confidence": 0.934632361557823,
            "decimals": -3, "source": {"filing_id": 42817733, "ref": "t142.r0#c1"},
            "as_printed": {"value": "15.623", "scale": 3},
        },
        {
            "label": "Terreinen en gebouwen", "statement": "IS", "scope": "consolidated",
            "value": "15731000", "unit": "EUR",
            "period": {"start": "2024-01-01", "end": "2024-12-31", "fiscal_label": "FY2024"},
            "method": "llm", "status": "accepted", "confidence": 0.9483026855549267,
            "decimals": -3, "source": {"filing_id": 42817733, "ref": "t142.r0#c2"},
            "as_printed": {"value": "15.731", "scale": 3},
        },
    ],
}

STATEMENTS_BODY = {
    "filing_id": 42817733,
    "method": "llm",
    "statements": [
        {
            "statement": "IS", "title": "Geconsolideerde resultatenrekening", "role": "t46",
            "periods": [
                {"start": "2025-01-01", "end": "2025-12-31", "fiscal_label": "FY2025"},
                {"start": "2024-01-01", "end": "2024-12-31", "fiscal_label": "FY2024"},
            ],
            "rows": [
                {"label": "BEDRIJFSOPBRENGSTEN", "kind": "total", "unit": "EUR",
                 "values": ["4207221000", "4143794000"], "refs": ["t46.r0#c2", "t46.r0#c3"]},
                {"label": "Omzet", "unit": "EUR",
                 "values": ["4154733000", "4101159000"], "refs": ["t46.r1#c2", "t46.r1#c3"]},
            ],
        }
    ],
}

def _tool(module, name):
    tool = module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(module, "get_access_token", lambda: at)


@pytest.fixture()
def unstd_module(mcp_module, monkeypatch):
    """The generated module re-imported with MCP_UNSTD_FACTS_TOOLS=1.

    Teardown reloads it again with the flag cleared, so no later test sees the
    hidden tools on a module it did not reload itself. Runs inside the
    respx_router context (mcp_module depends on it), which the reload needs for
    the OIDC discovery call.
    """
    monkeypatch.setenv("MCP_UNSTD_FACTS_TOOLS", "1")
    importlib.reload(mcp_module)

    async def _instant(_seconds: float) -> None:
        return None

    mcp_module._retry_sleep = _instant
    yield mcp_module
    monkeypatch.delenv("MCP_UNSTD_FACTS_TOOLS", raising=False)
    importlib.reload(mcp_module)


# --- surface: off by default, on with the flag --------------------------------


def test_flag_defaults_off(mcp_module) -> None:
    assert mcp_module.MCP_UNSTD_FACTS_TOOLS is False


@pytest.mark.asyncio
async def test_flag_off_tools_absent_from_tools_list(mcp_module) -> None:
    from fastmcp import Client

    async with Client(mcp_module.mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names.isdisjoint(UNSTD_TOOLS), names & set(UNSTD_TOOLS)
    # The block is still emitted (the module is flag-independent); only
    # registration is gated.
    assert callable(mcp_module._unstd_facts_get)


@pytest.mark.asyncio
async def test_flag_off_call_is_rejected_as_unknown_tool(mcp_module) -> None:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    async with Client(mcp_module.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("filings_facts", {"id": 1})


@pytest.mark.asyncio
async def test_flag_on_tools_listed_read_only_with_their_params(unstd_module) -> None:
    from fastmcp import Client

    async with Client(unstd_module.mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(UNSTD_TOOLS) <= set(tools)
    expected_params = {
        "filings_facts": {"id", "statement", "method", "scope", "page", "page_size"},
        "filings_statements": {"id", "statement", "method", "scope"},
    }
    for name, params in expected_params.items():
        tool = tools[name]
        assert set(tool.inputSchema["properties"]) == params, name
        assert tool.inputSchema["required"] == ["id"], name
        assert tool.annotations.readOnlyHint is True
        description = " ".join(tool.description.split())
        assert "AS REPORTED" in description, name
        assert "No note numbers" in description, name
    # The API's three methods, not the two of the 2026-10 patch (#6240 added structured).
    for name in UNSTD_TOOLS:
        method_schema = json.dumps(tools[name].inputSchema["properties"]["method"])
        for value in ("xbrl", "structured", "llm"):
            assert f'"{value}"' in method_schema, name
    # Only the statements route picks one method by default; facts mixes them.
    facts_method = tools["filings_facts"].inputSchema["properties"]["method"]["description"]
    assert "mixed" in facts_method and "filer's own" not in facts_method


def test_flag_on_does_not_change_the_rest_of_the_surface(mcp_module, monkeypatch) -> None:
    before = set(mcp_module.mcp._tool_manager._tools)
    monkeypatch.setenv("MCP_UNSTD_FACTS_TOOLS", "1")
    importlib.reload(mcp_module)
    try:
        after = set(mcp_module.mcp._tool_manager._tools)
    finally:
        monkeypatch.delenv("MCP_UNSTD_FACTS_TOOLS", raising=False)
        importlib.reload(mcp_module)
    assert after - before == set(UNSTD_TOOLS)
    assert before <= after


# --- calls: path, params, compact pass-through --------------------------------


def _compact(body) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.asyncio
async def test_filings_facts_path_params_and_compact_output(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/42817733/facts/").mock(
        return_value=httpx.Response(200, json=FACTS_BODY)
    )
    out = await _tool(unstd_module, "filings_facts")(
        id=42817733, statement="IS", method="llm", scope="consolidated,separate", page=2, page_size=500
    )
    assert route.called
    req = route.calls.last.request
    assert dict(req.url.params) == {
        "statement": "IS", "method": "llm", "scope": "consolidated,separate", "page": "2", "page_size": "100",
    }
    assert req.headers["authorization"] == "Bearer real-access-token"
    assert out == _compact(FACTS_BODY)
    assert "\n" not in out and ": " not in out
    assert json.loads(out) == FACTS_BODY


@pytest.mark.asyncio
async def test_filings_statements_path_and_defaults_send_no_params(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/42817733/statements/").mock(
        return_value=httpx.Response(200, json=STATEMENTS_BODY)
    )
    out = await _tool(unstd_module, "filings_statements")(id=42817733)
    assert dict(route.calls.last.request.url.params) == {}
    assert out == _compact(STATEMENTS_BODY)


@pytest.mark.asyncio
async def test_filings_statements_sends_statement_method_and_scope(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/14477798/statements/").mock(
        return_value=httpx.Response(200, json=STATEMENTS_BODY)
    )
    await _tool(unstd_module, "filings_statements")(
        id=14477798, statement="IS,CF", method="structured", scope="separate"
    )
    assert dict(route.calls.last.request.url.params) == {
        "statement": "IS,CF", "method": "structured", "scope": "separate",
    }


@pytest.mark.asyncio
async def test_page_below_one_is_rejected_without_calling_upstream(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/42817733/facts/").mock(
        return_value=httpx.Response(200, json=FACTS_BODY)
    )
    out = await _tool(unstd_module, "filings_facts")(id=42817733, page=0)
    assert not route.called
    assert "page must be >= 1" in out


@pytest.mark.asyncio
async def test_path_param_cannot_rewrite_the_request_path(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(url__regex=rf"^{TEST_API_BASE}/.*").mock(
        return_value=httpx.Response(200, json={})
    )
    for bad_id in ("../admin", 0, -1, True):
        out = await _tool(unstd_module, "filings_statements")(id=bad_id)
        assert "id must be a positive integer" in out, bad_id
    assert not route.called


@pytest.mark.asyncio
async def test_oversized_statements_say_how_to_narrow_instead_of_returning_half(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    row = STATEMENTS_BODY["statements"][0]["rows"][1]
    big = {**STATEMENTS_BODY, "statements": [
        {**STATEMENTS_BODY["statements"][0], "rows": [row] * 2000}
    ]}
    assert len(_compact(big)) > unstd_module._MAX_RESULT_CHARS
    respx_router.get(f"{TEST_API_BASE}/filings/42817733/statements/").mock(
        return_value=httpx.Response(200, json=big)
    )
    out = await _tool(unstd_module, "filings_statements")(id=42817733)
    assert out.startswith("Invalid argument: result is")
    assert "statement=IS" in out


# --- errors: same text-tool contract as the generated tools (#104, #132) -------


@pytest.mark.asyncio
async def test_upstream_400_raises_with_the_field_message(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    msg = "Must be a comma-separated subset of: BS, IS, CI, CF, EQ, NOTE, OTHER."
    respx_router.get(f"{TEST_API_BASE}/filings/14477798/statements/").mock(
        return_value=httpx.Response(400, json={"statement": msg})
    )
    with pytest.raises(unstd_module.UpstreamHTTPError) as ei:
        await _tool(unstd_module, "filings_statements")(id=14477798, statement="PL")
    assert ei.value.upstream_status == 400
    assert msg in str(ei.value)


@pytest.mark.asyncio
async def test_upstream_404_raises_not_a_successful_string(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/29735/statements/").mock(
        return_value=httpx.Response(404, json={"detail": "No statements for this filing."})
    )
    with pytest.raises(unstd_module.UpstreamHTTPError) as ei:
        await _tool(unstd_module, "filings_statements")(id=29735)
    assert ei.value.upstream_status == 404


@pytest.mark.asyncio
async def test_upstream_403_for_non_staff_surfaces_as_an_error(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """With the flag on, a caller the API refuses (staff-only until web#10584,
    then any plan below the chosen level) gets the upstream 403 as a tool
    error, never as data."""
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/1/facts/").mock(
        return_value=httpx.Response(
            403, json={"detail": "You do not have permission to perform this action."}
        )
    )
    with pytest.raises(unstd_module.UpstreamHTTPError) as ei:
        await _tool(unstd_module, "filings_facts")(id=1)
    assert ei.value.upstream_status == 403


@pytest.mark.asyncio
async def test_no_token_returns_auth_error_without_calling_upstream(
    unstd_module, monkeypatch, respx_router
) -> None:
    monkeypatch.setattr(unstd_module, "get_access_token", lambda: None)
    route = respx_router.get(f"{TEST_API_BASE}/filings/1/facts/").mock(
        return_value=httpx.Response(200, json=FACTS_BODY)
    )
    out = await _tool(unstd_module, "filings_facts")(id=1)
    assert not route.called
    assert "access token" in out.lower()


@pytest.mark.asyncio
async def test_result_count_reaches_analytics(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    from fastmcp import Client

    _auth_as(unstd_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/42817733/facts/").mock(
        return_value=httpx.Response(200, json=FACTS_BODY)
    )
    captured: list[dict] = []
    monkeypatch.setattr(unstd_module._usage_emitter, "emit", lambda ev: captured.append(ev))
    async with Client(unstd_module.mcp) as client:
        await client.call_tool("filings_facts", {"id": 42817733})
    events = [e for e in captured if e["name"] == "filings_facts" and e["kind"] == "tool"]
    assert events and events[-1]["status"] == "ok"
    assert events[-1]["result_count"] == 2


# --- go-live: the snapshot refresh must not add generic twins ------------------


def test_generated_twins_are_replaced_by_the_hand_built_tools() -> None:
    """When /filings/{id}/facts/ and /statements/ land in the committed snapshot,
    the schema loop would emit filings_facts_retrieve / filings_statements_retrieve
    on every surface next to these tools. _REPLACED_BY_SYNTHETIC drops them."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from generate_mcp_tools import _REPLACED_BY_SYNTHETIC, snake_case

    for op_id in ("filings_facts_retrieve", "filings_statements_retrieve"):
        assert snake_case(op_id) in _REPLACED_BY_SYNTHETIC
