"""429 classification: burst vs quota vs spend caps (issue #73).

The upstream builds four distinct 429 bodies (`users/exceptions.py` in the
monolith), discriminated by a `type` field, and the quota-exhaustion cases carry
their own remediation copy — including an absolute `payg_url` the monolith
deliberately makes absolute *because* it travels through this proxy. Collapsing
all of them to "wait a moment and retry" is actively wrong: a credit allowance
resets at the start of next month, not in a moment.

Pins:
  1. classification keyed on the upstream `type` field (never on `detail` —
     paid-tier quota and burst share a byte-identical DRF `detail` string).
  2. quota/spend-cap remediation copy is forwarded verbatim, so pricing wording
     stays single-sourced in the monolith.
  3. an unparseable/unknown 429 falls back to retry advice, never to quota copy.
  4. forwarded upstream text is redacted and length-capped before it reaches
     the model.
  5. `Retry-After` is surfaced when present and numeric (#40 §5).
  6. text tools take the same path as structured tools.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

PAYG_URL = "https://financialreports.eu/accounts/payg/"

# --- upstream body fixtures (shapes verified against monolith origin/master) --

FREE_QUOTA_BODY = {
    "error": "Too Many Requests",
    "detail": (
        "You have used all 500 API credits included with your plan this month. "
        "Your free allowance resets at the start of next month. To keep going "
        f"today, enable pay-as-you-go billing at {PAYG_URL} — you only pay for "
        "what you use."
    ),
    "retry_after_seconds": 1209600,
    "type": "quota_limit_exceeded",
    "upgrade_url": "/pricing/",
    "limit": 500,
    "interval": "monthly",
    "message": "You have used all 500 API credits included with your plan this month.",
    "payg_url": PAYG_URL,
    "resolution": (
        "Your free allowance resets at the start of next month. To keep going "
        f"today, enable pay-as-you-go billing at {PAYG_URL} — you only pay for "
        "what you use."
    ),
}

PAID_QUOTA_BODY = {
    "error": "Too Many Requests",
    # NOTE: DRF's generic string — byte-identical to the burst case. This is why
    # classification must key on `type`, not on `detail`.
    "detail": "Request was throttled. Expected available in 1209600 seconds.",
    "retry_after_seconds": 1209600,
    "type": "quota_limit_exceeded",
    "upgrade_url": "/pricing/",
    "limit": 100000,
    "interval": "monthly",
    "message": "You have used all 100000 API requests included with your plan this month.",
    "resolution": (
        "Your allowance resets at the start of next month. For a higher or "
        "unmetered allowance, see our API and Enterprise plans at /pricing/."
    ),
}

DAILY_CAP_BODY = {
    "error": "Too Many Requests",
    "detail": "Daily pay-as-you-go spend cap reached ($250/day). It resets at midnight UTC.",
    "retry_after_seconds": 34200,
    "type": "daily_spend_cap_reached",
    "message": "Daily pay-as-you-go spend cap reached ($250/day). It resets at midnight UTC.",
}

MONTHLY_CEILING_BODY = {
    "error": "Too Many Requests",
    "detail": (
        "Monthly self-serve spending ceiling reached ($1,000). The ceiling "
        "resets on the 1st (UTC). Contact sales@financialreports.eu to lift it."
    ),
    "retry_after_seconds": 1296000,
    "type": "monthly_spend_ceiling_reached",
    "message": (
        "Monthly self-serve spending ceiling reached ($1,000). The ceiling "
        "resets on the 1st (UTC). Contact sales@financialreports.eu to lift it."
    ),
    "contact": "sales@financialreports.eu",
}

BURST_BODY = {
    "error": "Too Many Requests",
    "detail": "Request was throttled. Expected available in 47 seconds.",
    "retry_after_seconds": 47,
    "type": "burst_limit_exceeded",
    "message": "You are sending requests too quickly.",
    "resolution": "Implement exponential backoff or reduce concurrency.",
}


def _structured_tool(mcp_module, name="companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _text_tool(mcp_module, name="filing_types_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


async def _raise_on_429(mcp_module, monkeypatch, fake_access_token, respx_router, **resp):
    """Drive companies_list against a mocked 429 and return the raised error."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(429, **resp)
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _structured_tool(mcp_module)()
    return ei.value


# --- 1. classification + forwarded copy --------------------------------------


@pytest.mark.asyncio
async def test_free_tier_quota_429_forwards_payg_upsell(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The whole point of #73: the free-tier user must get the PAYG link."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=FREE_QUOTA_BODY
    )
    msg = str(exc)
    assert exc.error_kind == "quota_exhausted"
    assert PAYG_URL in msg
    assert "pay-as-you-go" in msg.lower()
    # The old, actively-wrong advice must be gone for this case.
    assert "wait a moment" not in msg.lower()


@pytest.mark.asyncio
async def test_paid_tier_quota_429_forwards_pricing_resolution(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Paid-tier `detail` is DRF's generic string, so the copy must come from
    `message` + `resolution` — proving we don't just forward `detail`."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=PAID_QUOTA_BODY
    )
    msg = str(exc)
    assert exc.error_kind == "quota_exhausted"
    assert "/pricing/" in msg
    assert "100000 API requests" in msg
    assert "Expected available in" not in msg  # the generic DRF detail
    assert "wait a moment" not in msg.lower()


@pytest.mark.asyncio
async def test_daily_spend_cap_429_is_classified_and_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=DAILY_CAP_BODY
    )
    assert exc.error_kind == "spend_cap_daily"
    assert "midnight UTC" in str(exc)


@pytest.mark.asyncio
async def test_monthly_ceiling_429_is_classified_and_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The fourth `type` the issue's sketch omitted."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=MONTHLY_CEILING_BODY
    )
    assert exc.error_kind == "spend_ceiling_monthly"
    assert "sales@financialreports.eu" in str(exc)


@pytest.mark.asyncio
async def test_burst_429_keeps_retry_advice(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=BURST_BODY
    )
    assert exc.error_kind == "burst_limit"
    msg = str(exc).lower()
    assert "retry" in msg
    assert "payg" not in msg and "pay-as-you-go" not in msg


# --- 2. defensive fallback ----------------------------------------------------


@pytest.mark.asyncio
async def test_unparseable_429_falls_back_to_retry_never_quota(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A wrong guess must be harmless: never tell a burst-limited user their
    allowance is gone until next month."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, text="not json at all {{{"
    )
    assert exc.error_kind == "rate_limited"
    msg = str(exc).lower()
    assert "retry" in msg
    assert "next month" not in msg
    assert "pay-as-you-go" not in msg


@pytest.mark.asyncio
async def test_empty_429_body_falls_back_to_retry(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, text=""
    )
    assert exc.error_kind == "rate_limited"
    assert "retry" in str(exc).lower()


@pytest.mark.asyncio
async def test_unknown_429_type_falls_back_to_retry(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A `type` the monolith adds later must not be misread as quota."""
    exc = await _raise_on_429(
        mcp_module,
        monkeypatch,
        fake_access_token,
        respx_router,
        json={"type": "some_future_limit", "detail": "nope"},
    )
    assert exc.error_kind == "rate_limited"
    assert "retry" in str(exc).lower()


# --- 3. safety of the verbatim forward ---------------------------------------


@pytest.mark.asyncio
async def test_forwarded_quota_copy_is_length_capped(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    body = dict(FREE_QUOTA_BODY, resolution="x" * 5000, message="y" * 5000)
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=body
    )
    assert len(str(exc)) < 1000, "unbounded upstream copy reached the model"


@pytest.mark.asyncio
async def test_forwarded_quota_copy_redacts_token_shaped_text(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Upstream text is not trusted: a gateway echoing a credential into the
    body must not have it forwarded into the model's context."""
    leak = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
    body = dict(FREE_QUOTA_BODY, resolution=f"Enable PAYG at {PAYG_URL} {leak}")
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=body
    )
    msg = str(exc)
    assert "eyJhbGciOiJIUzI1NiJ9" not in msg
    assert PAYG_URL in msg  # redaction must not eat the useful part


# --- 4. Retry-After (#40 §5) --------------------------------------------------


@pytest.mark.asyncio
async def test_burst_429_surfaces_numeric_retry_after(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module,
        monkeypatch,
        fake_access_token,
        respx_router,
        json=BURST_BODY,
        headers={"Retry-After": "47"},
    )
    assert "47" in str(exc)


@pytest.mark.asyncio
async def test_429_without_retry_after_has_no_dangling_text(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=BURST_BODY
    )
    assert "Retry after" not in str(exc)


@pytest.mark.asyncio
async def test_non_numeric_retry_after_is_ignored(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """DRF always emits integer seconds; an HTTP-date form must not be
    interpolated into a sentence that reads as seconds."""
    exc = await _raise_on_429(
        mcp_module,
        monkeypatch,
        fake_access_token,
        respx_router,
        json=BURST_BODY,
        headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
    )
    assert "Retry after" not in str(exc)
    assert "Oct 2026" not in str(exc)


# --- 5. text tools take the same path ----------------------------------------


@pytest.mark.asyncio
async def test_text_tool_quota_429_gets_upsell_not_raw_body(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Text tools are 9 of 15 and currently dump the raw upstream body straight
    to the model. They must get the same classified copy — and no raw JSON."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(429, json=FREE_QUOTA_BODY)
    )

    with pytest.raises(mcp_module.UpstreamHTTPError) as excinfo:

        await _text_tool(mcp_module)()

    out = str(excinfo.value)  # #104: raised, not returned; message unchanged

    assert isinstance(out, str)
    assert PAYG_URL in out
    assert "wait a moment" not in out.lower()
    assert '"retry_after_seconds"' not in out, "raw upstream JSON leaked to the model"


@pytest.mark.asyncio
async def test_text_tool_429_records_error_kind_for_analytics(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    from src import usage_analytics

    usage_analytics._tool_error.set(None)
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(429, json=FREE_QUOTA_BODY)
    )

    # #104: raises now instead of returning the error as a normal result. The
    # analytics recording this test guards must still happen on the raise path.
    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _text_tool(mcp_module)()

    recorded = usage_analytics._tool_error.get()
    assert recorded is not None
    assert recorded["upstream_status"] == 429
    assert recorded["error_kind"] == "quota_exhausted"
