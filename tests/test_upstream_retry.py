"""One retry for transient upstream GETs (issue #75).

Contract pinned here:

  * 502/503/504 and transport failures get exactly ONE retry, so a persistent
    failure costs two requests, never three.
  * 429 defers to the #74 classifier: `burst_limit` / `rate_limited` retry,
    `quota_exhausted` / `spend_cap_daily` / `spend_ceiling_monthly` do not,
    because they cannot clear within the period.
  * `Retry-After` is honored only up to `_RETRY_AFTER_MAX`. The upstream hands
    out 47 s on burst and 1_209_600 s (14 days) on quota — both outlive every
    MCP client's tool timeout.
  * POST is never retried. The upstream POST surface is not idempotent.
  * 4xx other than 429 is never retried.

`_retry_sleep` is neutralised by an autouse fixture in conftest, so nothing here
waits on real time.
"""
from __future__ import annotations

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID
from .test_upstream_429 import BURST_BODY, FREE_QUOTA_BODY

OK_PAGE = {"count": 0, "results": []}


def _structured_tool(mcp_module, name="companies_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _text_tool(mcp_module, name="filing_types_list"):
    tool = mcp_module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _auth_as(mcp_module, monkeypatch, fake_access_token, token="real-access-token"):
    at = fake_access_token(client_id=TEST_CLIENT_ID, token=token)
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)


# --- transient 5xx and transport failures retry once -------------------------


@pytest.mark.asyncio
async def test_503_then_200_succeeds_with_two_requests(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The headline case from the issue's done-when."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=[
            httpx.Response(503, text="upstream blip"),
            httpx.Response(200, json=OK_PAGE),
        ]
    )

    assert await _structured_tool(mcp_module)() == OK_PAGE
    assert route.call_count == 2


@pytest.mark.parametrize("status", [502, 503, 504])
@pytest.mark.asyncio
async def test_gateway_family_retries(
    mcp_module, monkeypatch, fake_access_token, respx_router, status
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=[httpx.Response(status), httpx.Response(200, json=OK_PAGE)]
    )

    assert await _structured_tool(mcp_module)() == OK_PAGE
    assert route.call_count == 2


@pytest.mark.parametrize("status", [500, 501])
@pytest.mark.asyncio
async def test_500_and_501_are_not_retried(
    mcp_module, monkeypatch, fake_access_token, respx_router, status
) -> None:
    """Narrower than "any 5xx" deliberately: 500/501 are usually deterministic,
    so retrying only doubles the latency of a guaranteed failure."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(status, text="boom")
    )

    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _structured_tool(mcp_module)()
    assert route.call_count == 1


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("down")],
    ids=["ConnectTimeout", "ReadTimeout", "ConnectError"],
)
@pytest.mark.asyncio
async def test_transport_failure_then_200_succeeds(
    mcp_module, monkeypatch, fake_access_token, respx_router, exc
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=[exc, httpx.Response(200, json=OK_PAGE)]
    )

    assert await _structured_tool(mcp_module)() == OK_PAGE
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_persistent_503_makes_exactly_two_requests(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Bounds the retry at one. A regression to a loop shows up here."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(503, text="still down")
    )

    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _structured_tool(mcp_module)()
    assert route.call_count == 2


# --- 429 defers to the #74 classifier ---------------------------------------


@pytest.mark.asyncio
async def test_quota_429_is_not_retried(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """A quota 429 cannot clear within the period, so retrying is pure waste."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(429, json=FREE_QUOTA_BODY)
    )

    with pytest.raises(mcp_module.UpstreamHTTPError) as ei:
        await _structured_tool(mcp_module)()
    assert ei.value.error_kind == "quota_exhausted"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_burst_429_without_retry_after_is_retried_once(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    body = {k: v for k, v in BURST_BODY.items() if k != "retry_after_seconds"}
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=[httpx.Response(429, json=body), httpx.Response(200, json=OK_PAGE)]
    )

    assert await _structured_tool(mcp_module)() == OK_PAGE
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_burst_429_with_long_retry_after_is_not_retried(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Retry-After beyond the cap skips the retry rather than clamping to it.

    Clamping would guarantee a second request the upstream has already told us to
    hold off on. The upstream's real burst value is 47 s.
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(429, json=BURST_BODY, headers={"Retry-After": "47"})
    )

    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _structured_tool(mcp_module)()
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_unknown_429_type_is_retried(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Inherits #74's deliberate asymmetry: an unrecognised `type` classifies as
    `rate_limited`, the retryable bucket."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        side_effect=[
            httpx.Response(429, json={"type": "some_future_limit", "detail": "nope"}),
            httpx.Response(200, json=OK_PAGE),
        ]
    )

    assert await _structured_tool(mcp_module)() == OK_PAGE
    assert route.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
@pytest.mark.asyncio
async def test_client_errors_are_never_retried(
    mcp_module, monkeypatch, fake_access_token, respx_router, status
) -> None:
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/companies/").mock(
        return_value=httpx.Response(status, json={"detail": "no"})
    )

    with pytest.raises(mcp_module.UpstreamHTTPError):
        await _structured_tool(mcp_module)()
    assert route.call_count == 1


# --- streaming GETs retry too ------------------------------------------------


@pytest.mark.asyncio
async def test_stream_tool_retries_transient_status(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The markdown tools stream, so they need the context-manager helper rather
    than `_api_get`."""
    _auth_as(mcp_module, monkeypatch, fake_access_token)
    route = respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(
        side_effect=[
            httpx.Response(503, text="blip"),
            httpx.Response(200, text="# Filing body"),
        ]
    )

    out = await _text_tool(mcp_module, "filings_markdown_retrieve")(filing_id=1)
    assert "# Filing body" in out
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_stream_does_not_retry_a_mid_body_failure(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """Once the response is handed to the caller, a failure must not re-stream.

    Retrying here would re-download up to _MAX_FILING_BYTES (10 MB). The status
    line already succeeded, so the retry budget is spent.
    """
    _auth_as(mcp_module, monkeypatch, fake_access_token)

    def _fail_mid_body(_request):
        return httpx.Response(
            200, stream=_RaisingStream(httpx.ReadTimeout("died mid-body"))
        )

    route = respx_router.get(f"{TEST_API_BASE}/filings/1/markdown/").mock(
        side_effect=_fail_mid_body
    )

    out = await _text_tool(mcp_module, "filings_markdown_retrieve")(filing_id=1)

    # Exactly one request: the retry budget was spent on the status line, which
    # succeeded. This is the assertion that matters.
    assert route.call_count == 1
    # The tool's own `_safe_error` wrapper turns it into an opaque message rather
    # than letting the transport exception reach the model.
    assert "Error calling filings_markdown_retrieve" in out
    assert "# partial" not in out


class _RaisingStream(httpx.AsyncByteStream):
    """A body that yields one chunk then fails, to simulate a mid-body drop."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aiter__(self):
        yield b"# partial"
        raise self._exc


# --- structural guarantees ---------------------------------------------------


def test_client_timeout_is_split_not_flat(mcp_module) -> None:
    """A flat 60 s meant an unreachable upstream burned 60 s per call."""
    timeout = mcp_module._api_client.timeout
    assert timeout.connect == 5.0
    assert timeout.read == 60.0
    assert timeout.write == 10.0
    assert timeout.pool == 10.0


def test_transport_repasses_http2_and_limits(mcp_module) -> None:
    """httpx returns a caller-supplied transport verbatim and only uses its own
    http2/limits kwargs to build the DEFAULT one — so passing `transport=`
    without repeating them silently drops HTTP/2 and the explicit pool bounds."""
    pool = mcp_module._api_transport._pool
    assert pool._http2 is True
    assert pool._max_connections == 100
    assert pool._max_keepalive_connections == 20


def test_post_template_never_retries() -> None:
    """POST must stay on the plain client: the upstream POST surface (webhooks,
    watchlist) is not idempotent.

    Asserted at the source level because the default tool surface emits zero POST
    tools — all 7 live behind `MCP_FULL_SURFACE=1` — so there is no live POST tool
    to drive. Importing the generator is side-effect-free; the schema fetch is in
    `main()`.
    """
    import scripts.generate_mcp_tools as gen

    assert "_api_client.post(" in gen.POST_TOOL_TEMPLATE
    assert "_api_get(" not in gen.POST_TOOL_TEMPLATE
    assert "_api_stream_get(" not in gen.POST_TOOL_TEMPLATE


def test_retry_delay_rejects_non_retryable_and_long_waits(mcp_module) -> None:
    """Unit-level table for the decision function itself."""
    m = mcp_module
    # transient status, no Retry-After -> a short jittered backoff
    assert 0 < m._retry_delay(503, "", "") <= m._RETRY_BACKOFF + m._RETRY_JITTER
    # honored when within the cap
    assert m._retry_delay(503, "", "1") == 1.0
    # skipped, not clamped, beyond the cap
    assert m._retry_delay(503, "", "47") is None
    # non-transient statuses
    assert m._retry_delay(500, "", "") is None
    assert m._retry_delay(404, "", "") is None
    # 429 routed through the #74 classifier
    assert m._retry_delay(429, '{"type": "quota_limit_exceeded"}', "") is None
    assert m._retry_delay(429, '{"type": "burst_limit_exceeded"}', "") is not None
    # malformed 429 bodies fall into the retryable bucket by design
    assert m._retry_delay(429, "not json", "") is not None
