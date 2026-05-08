"""Subscription verification path: cache state machine, stampede, error branches."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from .conftest import TEST_VERIFY_URL


@pytest.mark.asyncio
async def test_verify_200_caches_authorized(mcp_module, respx_router) -> None:
    route = respx_router.get(TEST_VERIFY_URL).mock(
        return_value=httpx.Response(200, json={"plan": "analyst", "user_id": 7})
    )

    first = await mcp_module._check_subscription("tok", "sub-aaa")
    second = await mcp_module._check_subscription("tok", "sub-aaa")

    assert first == {"authorized": True, "plan": "analyst", "user_id": 7}
    assert second == first
    assert route.call_count == 1, "second call should hit the cache, not the API"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_verify_denied_caches_negative(mcp_module, respx_router, status: int) -> None:
    route = respx_router.get(TEST_VERIFY_URL).mock(
        return_value=httpx.Response(
            status,
            json={
                "reason": "subscription_required",
                "upgrade_url": "https://up.example",
            },
        )
    )

    first = await mcp_module._check_subscription("tok", f"sub-{status}")
    second = await mcp_module._check_subscription("tok", f"sub-{status}")

    assert first["authorized"] is False
    assert first["upgrade_url"] == "https://up.example"
    assert second == first
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_verify_5xx_does_not_cache(mcp_module, respx_router) -> None:
    route = respx_router.get(TEST_VERIFY_URL).mock(
        return_value=httpx.Response(503, text="upstream blip")
    )

    first = await mcp_module._check_subscription("tok", "sub-5xx")
    second = await mcp_module._check_subscription("tok", "sub-5xx")

    assert first["authorized"] is False
    assert first["reason"] == "verification_failed"
    assert second["authorized"] is False
    assert route.call_count == 2, (
        "transient failures must not be cached: a brief Django blip "
        "should not lock paid users out for the full TTL"
    )


@pytest.mark.asyncio
async def test_verify_network_error_does_not_cache(mcp_module, respx_router) -> None:
    route = respx_router.get(TEST_VERIFY_URL).mock(
        side_effect=httpx.ConnectError("boom")
    )

    first = await mcp_module._check_subscription("tok", "sub-net")
    second = await mcp_module._check_subscription("tok", "sub-net")

    assert first["authorized"] is False
    assert first["reason"] == "verification_error"
    assert second["authorized"] is False
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_verify_stampede_collapses_to_single_call(
    mcp_module, respx_router
) -> None:
    """Parallel calls from the same sub must collapse to one verify request."""
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await proceed.wait()
        return httpx.Response(200, json={"plan": "enterprise", "user_id": 1})

    route = respx_router.get(TEST_VERIFY_URL).mock(side_effect=slow_handler)

    async def do() -> dict:
        return await mcp_module._check_subscription("tok", "sub-stampede")

    tasks = [asyncio.create_task(do()) for _ in range(8)]
    await started.wait()
    proceed.set()
    results = await asyncio.gather(*tasks)

    assert all(r == results[0] for r in results)
    assert results[0]["authorized"] is True
    assert route.call_count == 1, (
        "stampede: 8 concurrent calls should collapse to a single verify"
    )


@pytest.mark.asyncio
async def test_verify_inflight_lock_released_on_cancel(
    mcp_module, respx_router
) -> None:
    """A CancelledError mid-verify must NOT leave a permanently-held lock."""
    proceed = asyncio.Event()

    async def hang(request: httpx.Request) -> httpx.Response:
        await proceed.wait()
        return httpx.Response(200, json={})

    respx_router.get(TEST_VERIFY_URL).mock(side_effect=hang)

    task = asyncio.create_task(
        mcp_module._check_subscription("tok", "sub-cancel")
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Inflight entry must be cleared so the next call from this sub
    # doesn't deadlock on a never-released lock.
    assert "sub-cancel" not in mcp_module._subscription_inflight

    # Reset the route so a fresh call goes through.
    respx_router.get(TEST_VERIFY_URL).mock(
        return_value=httpx.Response(200, json={"plan": "analyst"})
    )
    proceed.set()
    result = await mcp_module._check_subscription("tok", "sub-cancel")
    assert result["authorized"] is True
