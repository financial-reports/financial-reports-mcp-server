"""x402 pay-per-call MCP at /mcp-pay (MCP_X402_ENABLED=1).

The pay server relays each tool call as ONE keyless GET to the API: the
caller's `_meta["x402/payment"]` goes up as `PAYMENT-SIGNATURE`, the API's 402
comes back as an isError result carrying the PaymentRequired, and its
`PAYMENT-RESPONSE` comes back in `_meta["x402/payment-response"]`.
"""
from __future__ import annotations

import base64
import importlib
import json
import sys

import httpx
import pytest
from fastmcp import Client
from starlette.routing import Mount

from tests.conftest import TEST_API_BASE

REQUIRED = {
    "x402Version": 2,
    "error": "payment required",
    "resource": {"url": f"{TEST_API_BASE}/filing-types/", "description": "d", "mimeType": "application/json"},
    "accepts": [{
        "scheme": "exact", "network": "eip155:8453", "amount": "10000",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "payTo": "0x966F7dD98beBC2d90a5E0F6E11C59e229435Ed06",
        "maxTimeoutSeconds": 60, "extra": {"name": "USD Coin", "version": "2"},
    }],
    "extensions": {"financialfilings-license": {"info": {"termsVersion": "keyless-1.0"}}},
}
PAYMENT = {
    "x402Version": 2,
    "accepted": REQUIRED["accepts"][0],
    "payload": {"signature": "0xabc", "authorization": {"from": "0x" + "1" * 40, "nonce": "0x" + "2" * 64}},
    "extensions": REQUIRED["extensions"],
}
SETTLED = {"success": True, "transaction": "0x" + "3" * 64, "network": "eip155:8453", "payer": "0x" + "1" * 40}


def _b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _unb64(value: str):
    return json.loads(base64.b64decode(value))


def _reload(monkeypatch, enabled: bool):
    if enabled:
        monkeypatch.setenv("MCP_X402_ENABLED", "1")
    else:
        monkeypatch.delenv("MCP_X402_ENABLED", raising=False)
    sys.modules.pop("src.financial_reports_mcp", None)
    import src.financial_reports_mcp as m  # type: ignore

    importlib.reload(m)
    return m


@pytest.fixture()
def pay(respx_router, monkeypatch):
    return _reload(monkeypatch, enabled=True)


async def _call(m, name, args=None, payment=None):
    async with Client(m.mcp_pay) as client:
        meta = {"x402/payment": payment} if payment is not None else None
        return await client.call_tool_mcp(name, args or {}, meta=meta)


# --- off by default: /mcp untouched ------------------------------------------

def test_disabled_by_default_mounts_the_mcp_app_exactly(respx_router, monkeypatch) -> None:
    m = _reload(monkeypatch, enabled=False)
    assert m.MCP_X402_ENABLED is False
    assert m._pay_http_app is None
    root = [r for r in m.app.routes if isinstance(r, Mount) and r.path == ""]
    assert len(root) == 1 and root[0].app is m.mcp_app


def test_enabled_routes_only_the_pay_path_to_the_pay_app(pay) -> None:
    root = [r for r in pay.app.routes if isinstance(r, Mount) and r.path == ""]
    assert len(root) == 1 and root[0].app is pay._root_app
    assert pay._is_pay_path("/mcp-pay") and pay._is_pay_path("/mcp-pay/")
    assert not pay._is_pay_path("/mcp") and not pay._is_pay_path("/mcp-payx")


@pytest.mark.asyncio
async def test_the_pay_server_sells_exactly_the_priced_get_tools(pay) -> None:
    async with Client(pay.mcp_pay) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "companies_list", "companies_retrieve", "companies_financials_retrieve",
        "companies_next_annual_report_retrieve", "filing_categories_list",
        "filing_types_list", "filings_list", "filings_retrieve",
        "filings_markdown_retrieve", "isins_list", "isins_retrieve",
    }


def test_the_pay_client_carries_no_credential_hook(pay) -> None:
    assert pay._pay_client is not pay._api_client
    assert pay._inject_auth not in pay._pay_client.event_hooks["request"]


# --- relay ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unpaid_call_returns_the_payment_required_as_an_error_result(pay, respx_router) -> None:
    route = respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(402, json={"error": "payment_required"},
                                    headers={"PAYMENT-REQUIRED": _b64(REQUIRED)}))
    result = await _call(pay, "filing_types_list", {"search": "annual"})
    assert result.isError is True
    assert result.structuredContent == REQUIRED
    assert json.loads(result.content[0].text) == REQUIRED
    sent = route.calls.last.request
    assert "payment-signature" not in sent.headers
    assert "authorization" not in sent.headers and "x-api-key" not in sent.headers
    assert sent.url.params["search"] == "annual"


@pytest.mark.asyncio
async def test_paid_call_forwards_the_payment_and_returns_the_settlement(pay, respx_router) -> None:
    route = respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": [{"code": "AR"}]},
                                    headers={"PAYMENT-RESPONSE": _b64(SETTLED)}))
    result = await _call(pay, "filing_types_list", payment=PAYMENT)
    assert result.isError is False
    assert result.meta == {"x402/payment-response": SETTLED}
    assert '"code": "AR"' in result.content[0].text
    sent = route.calls.last.request
    assert _unb64(sent.headers["payment-signature"]) == PAYMENT
    assert "authorization" not in sent.headers
    assert sent.headers["user-agent"].startswith("FinancialReports-MCP-Server/")


@pytest.mark.asyncio
async def test_a_served_call_without_a_settlement_header_has_no_meta(pay, respx_router) -> None:
    # The API serves without PAYMENT-RESPONSE when the settle outcome is unknown.
    respx_router.get(f"{TEST_API_BASE}/filings/7/").mock(return_value=httpx.Response(200, json={"id": 7}))
    result = await _call(pay, "filings_retrieve", {"id": 7}, payment=PAYMENT)
    assert result.isError is False
    assert result.meta is None


@pytest.mark.asyncio
async def test_a_definite_settle_failure_is_an_error_a_client_will_not_pay_again(pay, respx_router) -> None:
    failed = {"success": False, "errorReason": "insufficient_funds", "transaction": ""}
    respx_router.get(f"{TEST_API_BASE}/filings/7/").mock(return_value=httpx.Response(
        402, json={"error": "settlement_failed", "detail": "Nothing was charged."},
        headers={"PAYMENT-RESPONSE": _b64(failed)}))
    result = await _call(pay, "filings_retrieve", {"id": 7}, payment=PAYMENT)
    assert result.isError is True
    assert "accepts" not in result.structuredContent and "x402Version" not in result.structuredContent
    assert result.structuredContent["settlement"] == failed
    assert result.meta == {"x402/payment-response": failed}


@pytest.mark.asyncio
async def test_an_api_refusal_is_an_error_with_its_detail(pay, respx_router) -> None:
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(return_value=httpx.Response(
        429, json={"error": "x402_payer_daily_limit", "detail": "This wallet has reached the daily limit."},
        headers={"Retry-After": "120"}))
    result = await _call(pay, "companies_list", payment=PAYMENT)
    assert result.isError is True
    text = result.content[0].text
    assert "429" in text and "daily limit" in text and "120" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    httpx.Response(503, json={"detail": "busy"}),
    httpx.ConnectTimeout("t"),
    httpx.ReadTimeout("t"),
])
async def test_a_paid_call_is_never_retried(pay, respx_router, answer) -> None:
    # A retry would send the same signed payment twice.
    kwargs = {"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(**kwargs)
    result = await _call(pay, "companies_list", payment=PAYMENT)
    assert result.isError is True
    assert route.call_count == 1
    if isinstance(answer, Exception):
        assert "may still settle" in result.content[0].text


@pytest.mark.asyncio
async def test_a_payment_that_is_not_an_object_is_refused_without_calling_the_api(pay, respx_router) -> None:
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(return_value=httpx.Response(200, json={}))
    result = await _call(pay, "companies_list", payment="0xdeadbeef")
    assert result.isError is True
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_bad_input_is_an_error_and_is_not_sent(pay, respx_router) -> None:
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(return_value=httpx.Response(200, json={}))
    result = await _call(pay, "companies_list", {"page": 0}, payment=PAYMENT)
    assert result.isError is True and "page must be >= 1" in result.content[0].text
    assert route.call_count == 0


# --- markdown windows -----------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("limit, sent", [(None, "100000"), (500_000, "140000"), (2_000, "2000")])
async def test_markdown_always_asks_for_a_window_that_fits_one_result(pay, respx_router, limit, sent) -> None:
    route = respx_router.get(f"{TEST_API_BASE}/filings/9/markdown/").mock(return_value=httpx.Response(
        200, text="# Annual report", headers={"content-type": "text/markdown",
                                              "X-Total-Chars": "250000", "X-Offset": "0",
                                              "X-Next-Offset": "100000"}))
    args = {"id": 9} if limit is None else {"id": 9, "limit": limit}
    result = await _call(pay, "filings_markdown_retrieve", args, payment=PAYMENT)
    assert route.calls.last.request.url.params["limit"] == sent
    text = result.content[0].text
    assert "of 250000" in text and "offset=100000" in text and text.endswith("# Annual report")


# --- the HTTP mount -------------------------------------------------------------

def _rpc(client, body, **headers):
    return client.post("/mcp-pay", json=body, headers={
        "Accept": "application/json, text/event-stream", **headers})


def _rpc_result(resp):
    text = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        text = next(line[5:].strip() for line in text.splitlines() if line.startswith("data:"))
    return json.loads(text)


def test_the_pay_endpoint_needs_no_auth_and_relays_over_http(pay, respx_router) -> None:
    from starlette.testclient import TestClient

    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(return_value=httpx.Response(
        402, headers={"PAYMENT-REQUIRED": _b64(REQUIRED)}))
    with TestClient(pay.app) as client:
        init = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"}}})
        assert init.status_code == 200, init.text
        call = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "filing_types_list", "arguments": {}}})
        assert call.status_code == 200, call.text
        result = _rpc_result(call)["result"]
        assert result["isError"] is True and result["structuredContent"] == REQUIRED
        # The /mcp app still demands its OAuth bearer.
        assert client.post("/mcp", json={}).status_code == 401


def test_the_pay_endpoint_rejects_a_foreign_browser_origin(pay, respx_router) -> None:
    from starlette.testclient import TestClient

    with TestClient(pay.app) as client:
        resp = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    Origin="https://evil.example")
    assert resp.status_code == 403
