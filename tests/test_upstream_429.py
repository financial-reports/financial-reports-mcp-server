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

PAYG_URL = "https://financialfilings.com/accounts/payg/?src=mcp"

# --- upstream body fixtures (shapes verified against monolith origin/master) --

# Free tier, credits mode, as the monolith builds it since web#8459.
FREE_QUOTA_BODY = {
    "error": "Too Many Requests",
    "detail": (
        "You've used this month's 500 free credits. Continue now: adding a card "
        "takes about a minute, then you pay only for what you use at "
        f"$0.01/credit: {PAYG_URL} Or wait for the reset on 2026-11-01 (UTC)."
    ),
    "retry_after_seconds": 1209600,
    "scope": "quota",
    "type": "quota_limit_exceeded",
    "upgrade_url": PAYG_URL,
    "resets_on": "2026-11-01",
    "limit": 500,
    "interval": "monthly",
    "message": "You've used this month's 500 free credits.",
    "payg_url": PAYG_URL,
    "resolution": (
        "Continue now: adding a card takes about a minute, then you pay only for "
        f"what you use at $0.01/credit: {PAYG_URL} Or wait for the reset on "
        "2026-11-01 (UTC)."
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
    assert "adding a card" in msg.lower()
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


@pytest.mark.asyncio
@pytest.mark.parametrize("body_name", ["FREE_QUOTA_BODY", "PAID_QUOTA_BODY", "DAILY_CAP_BODY", "MONTHLY_CEILING_BODY"])
async def test_non_retryable_429_tells_the_agent_to_stop_and_relay(
    mcp_module, monkeypatch, fake_access_token, respx_router, body_name
) -> None:
    """Agents kept calling tools after an account limit (prod telemetry: ~89% of
    follow-up calls hit the same tool). The message must say the limit is
    account-wide, not retryable, and that the remediation is for the user."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=globals()[body_name]
    )
    msg = str(exc).lower()
    assert "not a temporary error" in msg
    assert "other tools that fetch financialfilings data" in msg
    # Names no specific tool: the guide tools are absent on MCP_FULL_SURFACE=1.
    assert "get_fr_" not in msg
    assert "stop and tell the user" in msg


@pytest.mark.asyncio
async def test_free_tier_stop_instruction_still_carries_the_payg_link(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=FREE_QUOTA_BODY
    )
    msg = str(exc)
    # The relay sentence must come AFTER the instruction, whole, with the link.
    assert msg.index("Stop and tell the user") < msg.index(PAYG_URL)


@pytest.mark.asyncio
async def test_free_tier_cap_tells_the_agent_to_show_the_link_and_stop_calling(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """web#8459: 575 of 582 capped free users who never added a card came
    through MCP, and the old copy never asked the assistant to SHOW the link.
    The instruction must name the link, the one-sentence relay, and the
    no-more-calls rule, which points at the upstream copy (it names the card)."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=FREE_QUOTA_BODY
    )
    msg = str(exc)
    assert "every URL in that message as a clickable link, exactly as written" in msg
    assert "in one sentence" in msg
    assert (
        "Do not call any tool that fetches FinancialFilings data again until the "
        "user has followed the message below or the limit resets." in msg
    )
    # The card is named by the upstream copy, not invented by the wrapper.
    assert "adding a card" in FREE_QUOTA_BODY["resolution"]
    # The whole upstream sentence survives the 400-char cap, link and reset date.
    assert msg.endswith(FREE_QUOTA_BODY["message"] + " " + FREE_QUOTA_BODY["resolution"])
    assert msg.index("clickable link") < msg.index(PAYG_URL)


@pytest.mark.asyncio
async def test_paid_quota_cap_is_not_told_to_add_a_card(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """`quota_limit_exceeded` also covers paid plans, whose remedy is a plan
    change or the reset (specht on #169). The wrapper must not name a card."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=PAID_QUOTA_BODY
    )
    msg = str(exc)
    assert exc.error_kind == "quota_exhausted"
    assert "card" not in msg
    assert "stop and tell the user" in msg.lower()


@pytest.mark.asyncio
async def test_spend_cap_without_a_link_gets_no_link_instruction(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A daily spend cap belongs to a user who already has a card, and its copy
    carries no URL: asking the assistant to show 'the exact URL' would make it
    invent one."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=DAILY_CAP_BODY
    )
    msg = str(exc)
    assert "clickable link" not in msg
    assert "card" not in msg
    assert "until the user has followed the message below or the limit resets" in msg


@pytest.mark.asyncio
async def test_spend_cap_with_links_gets_the_link_instruction_but_no_card_wording(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The default daily-cap copy carries two absolute URLs (spend dashboard and
    contact form, `_add_spend_limit_links` in the monolith). Both are shown;
    the user already has a card, so the wait condition must not mention one."""
    body = dict(
        DAILY_CAP_BODY,
        resolution=(
            "See your current spend at https://financialfilings.com/api/dashboard/. "
            "To raise the limit, talk to us at https://financialfilings.com/contact/."
        ),
    )
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=body
    )
    msg = str(exc)
    assert "every URL in that message as a clickable link" in msg
    assert "card" not in msg
    assert "https://financialfilings.com/contact/" in msg


@pytest.mark.asyncio
async def test_burst_429_is_not_told_to_stop(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A burst limit IS retryable after a short wait (and on the MCP channel it
    is a flat per-minute rate that no plan change lifts), so it must not get the
    stop-and-relay framing."""
    exc = await _raise_on_429(
        mcp_module, monkeypatch, fake_access_token, respx_router, json=BURST_BODY
    )
    msg = str(exc).lower()
    assert "stop and tell the user" not in msg
    assert "retry" in msg


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


# --- SPECHT round 7: a CAPPED 429 body is a prefix, not a malformed body -----

def test_a_truncated_quota_body_still_classifies_as_quota(mcp_module) -> None:
    """`_api_stream_get` caps its classification read at `_MAX_ERROR_BODY`, and a
    capped valid JSON document no longer parses. Inheriting the malformed-body
    fallback would route an ACCOUNT-WIDE quota error to "wait a moment and retry"
    — advice that cannot work, for ~90% of all upstream errors.

    The comment this replaces claimed classification "only needs a prefix". It
    did not: `_classify_upstream_429` parses the WHOLE document, so the prefix was
    treated as garbage. Now the prefix really is enough.
    """
    truncated = '{"type": "quota_limit_exceeded", "detail": "' + "x" * 200
    assert mcp_module._parse_upstream_json(truncated) is None, "must be unparseable"
    assert mcp_module._classify_upstream_429(truncated) == "quota_exhausted"


def test_a_truncated_burst_body_still_classifies_as_burst(mcp_module) -> None:
    """Both directions, or the fix would just move which 429 is misread: a burst
    limit must stay retryable even when its body is capped."""
    truncated = '{"type": "burst_limit_exceeded", "detail": "' + "x" * 200
    assert mcp_module._classify_upstream_429(truncated) == "burst_limit"


def test_a_truncated_body_with_no_known_type_still_falls_back_to_retry(
    mcp_module,
) -> None:
    """NEGATIVE CONTROL for the two above. The deliberate asymmetry survives:
    telling a burst-limited caller their allowance is gone until next month is
    worse than telling a quota-exhausted caller to retry, so an unrecognised
    prefix must still render as retry advice rather than guessing quota."""
    assert mcp_module._classify_upstream_429('{"type": "something_new", ') == "rate_limited"
    assert mcp_module._classify_upstream_429("<html>429 Too Many Requests") == "rate_limited"
    assert mcp_module._classify_upstream_429("") == "rate_limited"


# --- SPECHT round 8: my round-7 fix widened the prefix path too far ----------

def test_a_complete_but_malformed_body_is_not_read_as_quota(mcp_module) -> None:
    """The prefix path exists for a body CAPPED mid-document. A body that is
    malformed because something WRAPPED or replaced it — a proxy error page that
    echoes our JSON — is not a prefix, and reading our four `type` tokens out of
    it hands a burst-limited caller "your allowance is gone until next month".

    That is the exact direction `_classify_upstream_429`'s asymmetry exists to
    prevent, and my round-7 fix broke it while claiming in its own commit message
    that the asymmetry survived. It survived for UNRECOGNISED prefixes; this is a
    RECOGNISED token in a body that was never truncated.

    ⚠ My round-7 negative control used `<html>429 Too Many Requests` — no token —
    so it could not have failed. Third round running that I wrote a control blind
    to the case it was guarding.
    """
    assert mcp_module._classify_upstream_429(
        '<html>{"type": "quota_limit_exceeded"}</html>'
    ) == "rate_limited"
    assert mcp_module._classify_upstream_429(
        'Error page: type is "quota_limit_exceeded" today'
    ) == "rate_limited"


def test_a_truncated_body_with_leading_whitespace_still_classifies(mcp_module) -> None:
    """CONTROL for the above: the discriminator is "does this look like the START
    of a JSON object", so insignificant leading whitespace must not defeat it."""
    assert mcp_module._classify_upstream_429(
        '\n  {"type": "quota_limit_exceeded", "detail": "' + "x" * 200
    ) == "quota_exhausted"
