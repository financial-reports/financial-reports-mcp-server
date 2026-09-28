"""Guidance that matches today's API (#132 item 5, #107).

Since web#3031 (2026-09-18) an unknown filing-type code is a 400 naming the
code. The instructions and the filing-types resource still told the model it
"returns an EMPTY LIST", so a model that believed them read a hard error as
"nothing filed" or distrusted the error it got.
"""
from __future__ import annotations

import inspect

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _generated_source(mcp_module) -> str:
    return inspect.getsource(mcp_module)


def _description(mcp_module, name) -> str:
    return mcp_module.mcp._tool_manager._tools[name].description or ""


def test_no_guidance_claims_an_unknown_code_returns_an_empty_list(mcp_module) -> None:
    src = _generated_source(mcp_module)
    assert "EMPTY LIST" not in src
    assert "returns an EMPTY" not in src


def test_guidance_says_an_unknown_code_is_a_400(mcp_module) -> None:
    src = _generated_source(mcp_module)
    assert "an unknown code is rejected with a 400" in src


def test_filing_types_list_says_when_to_call_it(mcp_module) -> None:
    desc = _description(mcp_module, "filing_types_list")
    assert "not in the" in desc and "source_filing_type" in desc


@pytest.mark.parametrize(
    "real_code", ["net_income_loss", "operating_income_loss", "total_debt_bs"]
)
def test_financials_names_real_codes_for_the_most_invented_ones(mcp_module, real_code) -> None:
    """Measured prod 400s (30 days to 2026-09-28): net_income 39, total_debt 23,
    operating_income 21. The hint maps each to the code that exists."""
    assert real_code in _description(mcp_module, "companies_financials_retrieve")


# --- #107(b): page_size=0 fails legibly, before the request -----------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -5])
async def test_page_size_below_one_is_rejected_legibly_without_a_request(
    mcp_module, monkeypatch, fake_access_token, respx_router, bad
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)
    route = respx_router.get(f"{TEST_API_BASE}/filings/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    tool = mcp_module.mcp._tool_manager._tools["filings_list"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    with pytest.raises(Exception) as ei:
        await fn(page_size=bad)
    assert "page_size must be >= 1" in str(ei.value)
    assert "structured_content" not in str(ei.value)
    assert not route.called


# --- #107(c): past-EOF header does not print an inverted range --------------


@pytest.mark.asyncio
async def test_markdown_offset_past_end_header_is_not_an_inverted_range(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)
    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(
        return_value=httpx.Response(200, text="x" * 500)
    )
    tool = mcp_module.mcp._tool_manager._tools["filings_markdown_retrieve"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)
    out = await fn(filing_id=1, offset=600)
    assert "chars 600 to 500" not in out
    assert "offset 600 is past the end" in out
    assert "500 chars" in out
