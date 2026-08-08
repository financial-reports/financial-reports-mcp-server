"""Env-gated pytest wrapper around the prod OAuth probe (oauth_probe.py).

This is the #32 regression guard on the LIVE OAuth path — the path DEV_MODE
bypasses, which is why #32 was untestable from CI by construction.

It is gated on `FR_E2E_OAUTH_PROBE` and skips at module level otherwise, so it
NEVER runs in default CI or the docker e2e sweep (`pytest tests/e2e` /
`scripts/test-e2e.sh`). The deterministic classifier it relies on is unit-tested
separately in `tests/test_oauth_probe.py` (no network, runs in CI).

Run it:
    FR_E2E_OAUTH_PROBE=1 FR_E2E_INTERACTIVE=1 pytest tests/e2e/test_prod_oauth_probe.py -s
        # mints a token via browser login (-s shows the authorize URL)
    FR_E2E_OAUTH_PROBE=1 FR_E2E_TOKEN=<jwt> pytest tests/e2e/test_prod_oauth_probe.py
        # bring your own token — the mode the scheduled synthetic probe (#40 §3 item 2) uses
    FR_E2E_BASE_URL=https://staging…  # optional; defaults to prod
"""
from __future__ import annotations

import os

import pytest

if not os.environ.get("FR_E2E_OAUTH_PROBE"):
    pytest.skip(
        "prod OAuth probe — set FR_E2E_OAUTH_PROBE=1 (+ FR_E2E_USERNAME/"
        "FR_E2E_PASSWORD, FR_E2E_TOKEN, or FR_E2E_INTERACTIVE=1) to run",
        allow_module_level=True,
    )

from tests.e2e import oauth_probe  # noqa: E402  (after the gate by design)


@pytest.fixture(scope="module")
def probe_report() -> dict:
    """Acquire a token, then drive the probe.

    Three modes, in precedence order:

      1. FR_E2E_USERNAME + FR_E2E_PASSWORD — headless password login. **This is the
         scheduled-probe mode.** It is the only one that works unattended: a FastMCP
         proxy token lives ~60 minutes and its refresh token rotates on every use, so
         no token can be stored as a secret and reused across cron runs.
      2. FR_E2E_TOKEN — bring your own, for a one-off manual run inside that hour.
      3. FR_E2E_INTERACTIVE=1 — mint via a real browser login. Blocks.
    """
    base = os.environ.get("FR_E2E_BASE_URL", oauth_probe.PROD_BASE)
    username = os.environ.get("FR_E2E_USERNAME")
    password = os.environ.get("FR_E2E_PASSWORD")
    token = os.environ.get("FR_E2E_TOKEN")

    if username and password:
        token = oauth_probe.mint_token_headless(username, password, base)
    elif not token:
        if os.environ.get("FR_E2E_INTERACTIVE"):
            token = oauth_probe.mint_token(base)
        else:
            pytest.skip(
                "set FR_E2E_USERNAME + FR_E2E_PASSWORD (scheduled mode), or "
                "FR_E2E_TOKEN, or FR_E2E_INTERACTIVE=1 to mint one via browser"
            )
    return oauth_probe.run_probe(token, base)


def test_session_initializes(probe_report: dict) -> None:
    """The OAuth token authenticates and the MCP session comes up with the
    full pruned surface (15 tools)."""
    assert probe_report["tool_count"] >= 14, probe_report


def test_structured_tools_never_leak_upstream_403(probe_report: dict) -> None:
    """#32 contract: every structured tool returns data OR the typed reconnect
    error — NEVER a raw `upstream … returned 403` (the kid-less-token leak #32 was)."""
    results = probe_report["results"]
    assert results, "no structured-tool results returned"

    forbidden = [r for r in results if r["classification"] == "forbidden"]
    assert not forbidden, "#32 REGRESSION — raw upstream-403 leaked to the client:\n" + "\n".join(
        f"  {r['tool']}: {r['detail']}" for r in forbidden
    )

    unexpected = [r for r in results if r["classification"] not in ("data", "reconnect")]
    assert not unexpected, "structured tool(s) returned neither data nor a reconnect hint:\n" + "\n".join(
        f"  {r['tool']} -> {r['classification']}: {r['detail']}" for r in unexpected
    )
