"""Hidden un-standardised facts tools (web#4964).

Four hand-written tools, 1:1 with the hidden REST endpoints
(/filings/{id}/facts/, /filings/{id}/statements/, /companies/{id}/series/,
/companies/{id}/series/{key}/). They are always emitted into the generated
module but registered only when MCP_UNSTD_FACTS_TOOLS=1, so the default
surface (prod, docs/token-budget.md, README) never lists them.

Upstream bodies below are trimmed copies of real responses from the web repo's
views over the facts corpus, not invented shapes. The series-history body has
no real sample yet; it follows `esef/facts_api.series_detail` field for field.
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
    "companies_series",
    "companies_series_retrieve",
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

_VESTAS_LATEST = {
    "value": "18822000000", "unit": "EUR",
    "period": {"start": "2025-01-01", "end": "2025-12-31", "fiscal_label": "FY2025"},
    "method": "xbrl", "status": "accepted", "decimals": -6,
    "source": {"filing_id": 14477798, "ref": "f0__s2__3__5"},
}
_VESTAS_HEAD = {
    "key": "x_2f857564b9033b20", "label": "Revenue", "concept": "ifrs-full:Revenue",
    "unit": "EUR", "scope": "consolidated", "length": "FY", "key_kind": "xbrl",
    "key_stable": True, "periods": 7, "first_period_end": "2019-12-31",
    "last_period_end": "2025-12-31", "continuity": {"current": True, "gaps": 0},
}
SERIES_BODY = {
    "count": 1, "next": None, "previous": None,
    "results": [{**_VESTAS_HEAD, "latest": _VESTAS_LATEST}],
}
SERIES_DETAIL_BODY = {
    **_VESTAS_HEAD,
    "members": [{"key": "x_2f857564b9033b20", "concept": "ifrs-full:Revenue",
                 "first_period_end": "2019-12-31", "last_period_end": "2025-12-31"}],
    "observations": [{**_VESTAS_LATEST, "version": 1}],
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
        "filings_facts": {"id", "statement", "method", "status", "page", "page_size"},
        "filings_statements": {"id", "statement", "method"},
        "companies_series": {"id", "period", "as_of", "search", "page", "page_size"},
        "companies_series_retrieve": {"id", "key", "period", "as_of"},
    }
    for name, params in expected_params.items():
        tool = tools[name]
        assert set(tool.inputSchema["properties"]) == params, name
        assert tool.annotations.readOnlyHint is True
    assert tools["companies_series_retrieve"].inputSchema["required"] == ["id", "key"]


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
        id=42817733, statement="IS", method="llm", page=2, page_size=500
    )
    assert route.called
    req = route.calls.last.request
    assert dict(req.url.params) == {
        "statement": "IS", "method": "llm", "page": "2", "page_size": "100",
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
async def test_companies_series_path_and_params(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/3390/series/").mock(
        return_value=httpx.Response(200, json=SERIES_BODY)
    )
    out = await _tool(unstd_module, "companies_series")(
        id=3390, period="annual", as_of="2026-01-31", search="revenue"
    )
    assert dict(route.calls.last.request.url.params) == {
        "period": "annual", "as_of": "2026-01-31", "search": "revenue",
    }
    assert out == _compact(SERIES_BODY)


@pytest.mark.asyncio
async def test_companies_series_retrieve_path_and_params(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(
        f"{TEST_API_BASE}/companies/3390/series/x_2f857564b9033b20/"
    ).mock(return_value=httpx.Response(200, json=SERIES_DETAIL_BODY))
    out = await _tool(unstd_module, "companies_series_retrieve")(
        id=3390, key="x_2f857564b9033b20", period="annual"
    )
    assert dict(route.calls.last.request.url.params) == {"period": "annual"}
    assert out == _compact(SERIES_DETAIL_BODY)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["x_2F857564B9033B20", "s_2f857564b9033b20", "x_../admin", ""])
async def test_series_retrieve_rejects_malformed_key_without_calling_upstream(
    unstd_module, monkeypatch, fake_access_token, respx_router, bad_key
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(url__regex=rf"^{TEST_API_BASE}/companies/.*").mock(
        return_value=httpx.Response(200, json={})
    )
    out = await _tool(unstd_module, "companies_series_retrieve")(id=3390, key=bad_key)
    assert not route.called
    assert "16 hex" in out


@pytest.mark.asyncio
async def test_page_below_one_is_rejected_without_calling_upstream(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/3390/series/").mock(
        return_value=httpx.Response(200, json=SERIES_BODY)
    )
    out = await _tool(unstd_module, "companies_series")(id=3390, page=0)
    assert not route.called
    assert "page must be >= 1" in out


# --- errors: same text-tool contract as the generated tools (#104, #132) -------


@pytest.mark.asyncio
async def test_upstream_400_raises_with_the_field_message(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/3390/series/").mock(
        return_value=httpx.Response(400, json={"period": "Must be one of: annual, quarterly."})
    )
    with pytest.raises(unstd_module.UpstreamHTTPError) as ei:
        await _tool(unstd_module, "companies_series")(id=3390, period="annual")
    assert ei.value.upstream_status == 400
    assert "Must be one of: annual, quarterly." in str(ei.value)


@pytest.mark.asyncio
async def test_upstream_404_raises_not_a_successful_string(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(unstd_module, monkeypatch, fake_access_token)
    respx_router.get(
        f"{TEST_API_BASE}/companies/29735/series/x_0000000000000000/"
    ).mock(
        return_value=httpx.Response(
            404, json={"detail": "No series with this key for this company."}
        )
    )
    with pytest.raises(unstd_module.UpstreamHTTPError) as ei:
        await _tool(unstd_module, "companies_series_retrieve")(
            id=29735, key="x_0000000000000000"
        )
    assert ei.value.upstream_status == 404


@pytest.mark.asyncio
async def test_upstream_403_for_non_staff_surfaces_as_an_error(
    unstd_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """With the flag on, a non-staff caller still gets the upstream 403 (the
    real gate is Django's IsAdminUser), as a tool error, never as data."""
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
