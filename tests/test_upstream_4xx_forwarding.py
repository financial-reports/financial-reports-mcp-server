"""Forward REST 4xx bodies to the model (#132, part of web#4123).

Before this, every upstream 400 reached the model as "check the arguments",
while the REST body already named the bad argument and (after web#4138/#4139)
suggested the fix. In prod (2026-08-29 -> 09-28) that cost 165 invented-KPI
400s, 83 unknown-filing-type 400s and 71 page_size 400s, most of them repeated
because the model never saw why.

Body shapes below are copied from the monolith, not invented:
  * field-keyed message, bare string (prod master today):  {"types": "..."}
  * the same plus web#4185's additive keys: detail / error_type /
    invalid_codes / did_you_mean / valid_codes_url
  * DRF list-valued field errors: {"page_size": ["..."]}
  * web#4189's tagged 403s: {"detail": ..., "type": "plan_level_insufficient",
    "resolution": ..., "upgrade_url": ...}
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID


def _tool(mcp_module, name):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


TYPES_MSG = (
    "Unknown filing type code(s): 10-Q, 8-K. These are FinancialFilings "
    "taxonomy codes, not regulator form names."
)
BODY_4185 = {
    "types": TYPES_MSG,
    "detail": "Unknown filing type code(s): 10-Q, 8-K. See did_you_mean for "
    "replacements and valid_codes_url for the valid codes.",
    "error_type": "unknown_filing_type",
    "invalid_codes": ["10-Q", "8-K"],
    "did_you_mean": {
        "10-Q": ["types=IR", "source_filing_type=10-Q"],
        "8-K": ["source_filing_type=8-K"],
    },
    "valid_codes_url": "https://api.financialreports.eu/filing-types/",
}


async def _raise_from_filings_list(mcp_module, respx_router, status, **resp):
    respx_router.get(f"{TEST_API_BASE}/filings/").mock(
        return_value=httpx.Response(status, **resp)
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _tool(mcp_module, "filings_list")(types="10-Q,8-K")
    return ei.value


# --- 400: the field message and did_you_mean reach the model -----------------


@pytest.mark.asyncio
async def test_400_field_keyed_body_forwards_field_message_and_did_you_mean(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(mcp_module, respx_router, 400, json=BODY_4185)
    msg = str(exc)
    assert exc.upstream_status == 400
    assert "Unknown filing type code(s): 10-Q, 8-K" in msg          # field message
    assert "types=IR" in msg and "source_filing_type=10-Q" in msg   # did_you_mean
    assert "source_filing_type=8-K" in msg
    # Metadata keys are not dumped verbatim as if they were argument errors.
    assert "invalid_codes:" not in msg and "error_type:" not in msg
    # It must tell the model an identical retry is pointless.
    assert "retry" in msg.lower()


@pytest.mark.asyncio
async def test_400_bare_field_body_as_served_by_prod_today_is_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Master's body has no detail and no did_you_mean — only the field key.
    Forwarding must not depend on the web PRs landing first."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(
        mcp_module, respx_router, 400, json={"types": TYPES_MSG}
    )
    assert "types: " + TYPES_MSG in str(exc)


@pytest.mark.asyncio
async def test_400_list_valued_drf_errors_are_flattened(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={"page_size": ["A valid integer is required.", "Second problem."]},
    )
    msg = str(exc)
    assert "page_size: A valid integer is required.; Second problem." in msg
    assert "[" not in msg.split("returned 400")[1]  # no raw list repr


@pytest.mark.asyncio
async def test_400_tagged_body_forwards_detail_and_resolution(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """web#4189's page_size 400: `type` is a TAG here, not a field message."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={
            "detail": "The maximum allowed page size is 100.",
            "type": "page_size_too_large",
            "resolution": "Request page_size=100 or less and follow the `next` link for more.",
            "max_page_size": 100,
        },
    )
    msg = str(exc)
    assert "The maximum allowed page size is 100." in msg
    assert "follow the `next` link" in msg
    assert "type: page_size_too_large" not in msg


@pytest.mark.asyncio
async def test_400_type_param_message_is_kept_even_though_type_is_also_a_tag_key(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """On /filings/ the top-level `type` key holds the `type=` PARAM's message
    (web#4185 names its tag `error_type` for exactly this reason)."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={"type": "Unknown filing type code(s): 20-F.", "did_you_mean": {"20-F": ["type=10-K"]}},
    )
    msg = str(exc)
    assert "type: Unknown filing type code(s): 20-F." in msg
    assert "type=10-K" in msg


@pytest.mark.asyncio
async def test_400_non_json_body_is_not_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """An HTML error page is not argument guidance; keep the generic hint."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(
        mcp_module, respx_router, 400, text="<html><body>Bad Request</body></html>"
    )
    msg = str(exc)
    assert "<html" not in msg
    assert "check the arguments" in msg


@pytest.mark.asyncio
async def test_forwarded_copy_redacts_credentials_and_is_capped(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlc2lnbmF0dXJl"
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={"types": f"bad token {jwt} " + "x" * 5000},
    )
    msg = str(exc)
    assert jwt not in msg
    assert len(msg) < 1200


# --- 404 ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_404_detail_is_forwarded(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/123/").mock(
        return_value=httpx.Response(404, json={"detail": "No Filing matches the given query."})
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _tool(mcp_module, "filings_retrieve")(id=123)
    msg = str(ei.value)
    assert "does not exist upstream" in msg
    assert "No Filing matches the given query." in msg


# --- text tools take the same path -------------------------------------------


@pytest.mark.asyncio
async def test_text_tool_400_forwards_body(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(400, json={"page_size": ["Ensure this value is at most 100."]})
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _tool(mcp_module, "filing_types_list")()
    assert "page_size: Ensure this value is at most 100." in str(ei.value)


# --- 403: plan gating is not a credentials problem ---------------------------

PLAN_403 = {
    "detail": "Your plan does not include this data level.",
    "type": "plan_level_insufficient",
    "resolution": "This endpoint needs a higher data level than your plan includes. "
    "Upgrade at https://financialfilings.com/pricing/",
    "upgrade_url": "https://financialfilings.com/pricing/",
}


@pytest.mark.asyncio
async def test_plan_403_forwards_resolution_not_reconnect(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    exc = await _raise_from_filings_list(mcp_module, respx_router, 403, json=PLAN_403)
    msg = str(exc)
    assert exc.error_kind == "plan_restricted"
    assert "needs a higher data level" in msg
    # No reconnect ADVICE (the text may say reconnecting will not help).
    assert "disconnect and reconnect" not in msg.lower()
    assert "reconnecting will not help" in msg


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tag",
    ["webhooks_not_in_plan", "mcp_only_account", "endpoint_not_in_plan", "api_root_not_available"],
)
async def test_every_plan_tag_is_classified_plan_restricted(
    mcp_module, monkeypatch, fake_access_token, respx_router, tag
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = {"detail": "Denied.", "type": tag, "resolution": "Contact us to enable it."}
    exc = await _raise_from_filings_list(mcp_module, respx_router, 403, json=body)
    assert exc.error_kind == "plan_restricted"
    assert "Contact us to enable it." in str(exc)


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["authentication_required", "invalid_api_key", "some_future_tag"])
async def test_credential_and_unknown_403_tags_keep_reconnect_advice(
    mcp_module, monkeypatch, fake_access_token, respx_router, tag
) -> None:
    """Only the known plan tags change behaviour. A credential tag (whose
    resolution talks about X-API-Key, meaningless to an OAuth user) and any tag
    the monolith adds later keep the existing credentials path."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = {"detail": "Denied.", "type": tag, "resolution": "Send X-API-Key."}
    exc = await _raise_from_filings_list(mcp_module, respx_router, 403, json=body)
    assert exc.error_kind == "invalid_credentials"
    assert "reconnect" in str(exc).lower()
    assert "X-API-Key" not in str(exc)


@pytest.mark.asyncio
async def test_profile_missing_detail_still_wins_over_a_plan_tag(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The existing detail-substring classification is kept, and runs first."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = {"detail": "User profile not found for the provided token.", "type": "plan_level_insufficient"}
    exc = await _raise_from_filings_list(mcp_module, respx_router, 403, json=body)
    assert exc.error_kind == "missing_profile"


# --- page_size is clamped, not rejected upstream -----------------------------


@pytest.mark.asyncio
async def test_page_size_over_100_is_clamped_before_the_request(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    await _tool(mcp_module, "filings_list")(page_size=500)
    assert route.calls.last.request.url.params["page_size"] == "100"


@pytest.mark.asyncio
async def test_page_size_within_range_is_untouched(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )
    await _tool(mcp_module, "filings_list")(page_size=37)
    assert route.calls.last.request.url.params["page_size"] == "37"


# --- specht #135 findings ------------------------------------------------------


def _big_body():
    codes = [f"BAD{i:03d}" for i in range(250)]
    return {
        "types": "Unknown filing type code(s): " + ", ".join(codes) + ".",
        "did_you_mean": {"10-Q": ["types=IR", "source_filing_type=10-Q"]},
    }


@pytest.mark.asyncio
async def test_a_body_over_1000_chars_is_still_parsed(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The body used to be sliced to 1,000 chars BEFORE json parsing, so a long
    list of invalid codes produced invalid JSON and the generic hint."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    import json as _json

    assert len(_json.dumps(_big_body())) > 1000
    exc = await _raise_from_filings_list(mcp_module, respx_router, 400, json=_big_body())
    msg = str(exc)
    assert "types=IR" in msg
    assert "The API rejected the arguments" in msg


@pytest.mark.asyncio
async def test_text_tool_body_over_1000_chars_is_still_parsed(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filing-types/").mock(
        return_value=httpx.Response(400, json=_big_body())
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _tool(mcp_module, "filing_types_list")()
    assert "types=IR" in str(ei.value)


@pytest.mark.asyncio
async def test_opaque_key_shapes_are_redacted_but_codes_survive(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    key = "frk9sQ2mX7pL4vT8zW1nB6cD3eF5gH0jK"
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={
            "types": f"Unknown filing type code(s): {key}, 10-Q.",
            "did_you_mean": {"10-Q": ["types=IR", "source_filing_type=10-Q"]},
        },
    )
    msg = str(exc)
    assert key not in msg
    assert "10-Q" in msg and "types=IR" in msg and "source_filing_type=10-Q" in msg


@pytest.mark.asyncio
async def test_key_after_long_prose_is_redacted_not_truncated_to_a_prefix(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    # #135 review: a cut at the per-part cap used to shorten the key below the
    # redaction threshold, so its prefix leaked. Redaction now runs first.
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    key = "frk9sQ2mX7pL4vT8zW1nB6cD3eF5gH0jK"
    prose = "word " * 51  # 255 chars, so the key straddles the 280-char cap
    exc = await _raise_from_filings_list(
        mcp_module, respx_router, 400, json={"types": prose + key}
    )
    msg = str(exc)
    assert key[:10] not in msg


@pytest.mark.asyncio
async def test_aws_access_key_id_is_redacted(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    akid = "AKIAIOSFODNN7EXAMPLE"  # AWS's documented example ID, 20 chars
    exc = await _raise_from_filings_list(
        mcp_module,
        respx_router,
        400,
        json={"types": f"Unknown filing type code(s): {akid}, 10-Q."},
    )
    msg = str(exc)
    assert akid not in msg and "10-Q" in msg


async def _markdown_404(mcp_module, monkeypatch, fake_access_token, respx_router, body, headers=None):
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(
        return_value=httpx.Response(404, json=body, headers=headers or {})
    )
    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _tool(mcp_module, "filings_markdown_retrieve")(filing_id=1)
    return ei.value


_NOT_FOUND = "Processed content not found for this filing."


@pytest.mark.asyncio
async def test_markdown_conversion_in_progress_is_retryable_not_missing(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    # #135 review: web's ConversionInProgress 404 is retryable; "does not
    # exist" made the model give up on a filing readable minutes later.
    exc = await _markdown_404(
        mcp_module, monkeypatch, fake_access_token, respx_router,
        {"detail": _NOT_FOUND, "processing_status": "QUEUED",
         "reason": "not_processed", "retryable": True},
        headers={"Retry-After": "120"},
    )
    msg = str(exc)
    assert exc.error_kind == "markdown_pending"
    assert "does not exist" not in msg
    assert "Retry after 120 seconds" in msg


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,retryable,kind",
    [("not_processed", False, "markdown_not_scheduled"),
     ("no_narrative_content", False, "markdown_no_content")],
)
async def test_markdown_404_without_text_says_do_not_retry(
    mcp_module, monkeypatch, fake_access_token, respx_router, reason, retryable, kind
) -> None:
    exc = await _markdown_404(
        mcp_module, monkeypatch, fake_access_token, respx_router,
        {"detail": _NOT_FOUND, "reason": reason, "retryable": retryable},
    )
    msg = str(exc)
    assert exc.error_kind == kind
    assert "raw document" in msg and "does not exist upstream" not in msg
    if kind == "markdown_not_scheduled":
        # not "never": the filing may be scheduled later (#135 review round 3)
        assert "do not retry now" in msg and "later" in msg
        assert "retrying will not change that" not in msg
    else:
        assert "retrying will not change that" in msg


@pytest.mark.asyncio
async def test_plain_404_keeps_the_missing_resource_hint(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    exc = await _markdown_404(
        mcp_module, monkeypatch, fake_access_token, respx_router, {"detail": "Not found."}
    )
    assert exc.error_kind == "unknown"
    assert "does not exist upstream" in str(exc)


@pytest.mark.asyncio
async def test_long_field_errors_leave_room_for_the_suggestion(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    # #135 review: three near-cap field errors used to fill the 800-char copy
    # before did_you_mean was appended.
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    long = "invalid value " * 25
    exc = await _raise_from_filings_list(
        mcp_module, respx_router, 400,
        json={"types": long, "category": long, "countries": long,
              "did_you_mean": {"10-Q": ["types=IR", "source_filing_type=10-Q"]}},
    )
    msg = str(exc)
    assert "types=IR" in msg and "source_filing_type=10-Q" in msg
    assert "types:" in msg  # field prose shortened, name kept
