"""End-to-end test fixtures.

Unlike `tests/conftest.py`, these tests probe a real container over real HTTP
on `localhost:8000` (DiskStore variant) and `localhost:8001` (Redis variant).
The `scripts/test-e2e.sh` runner brings the containers up before pytest runs
and tears them down after.
"""
from __future__ import annotations

import os
import subprocess
import time

import httpx
import pytest

DEFAULT_BASE = "http://localhost:8000"
REDIS_BASE = "http://localhost:8001"


def _is_target_enabled(name: str) -> bool:
    """Pick targets via MCP_E2E_TARGETS=default,redis (set by the runner).

    Defaults to running only the `default` (DiskStore) suite when the env
    var isn't set, so an ad-hoc `pytest tests/e2e -k smoke` works against
    a manually-started `docker compose up mcp`.
    """
    targets = os.environ.get("MCP_E2E_TARGETS", "default")
    return name in {t.strip() for t in targets.split()}


@pytest.fixture(scope="session")
def default_base_url() -> str:
    if not _is_target_enabled("default"):
        pytest.skip("MCP_E2E_TARGETS does not include 'default'")
    return DEFAULT_BASE


@pytest.fixture(scope="session")
def redis_base_url() -> str:
    if not _is_target_enabled("redis"):
        pytest.skip("MCP_E2E_TARGETS does not include 'redis'")
    return REDIS_BASE


@pytest.fixture(scope="session")
def http() -> httpx.Client:
    """Synchronous httpx client. E2E tests don't benefit from async."""
    with httpx.Client(timeout=10.0) as client:
        yield client


def _compose(*args: str) -> None:
    cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.test.yml",
        "--profile",
        "redis",
        *args,
    ]
    subprocess.run(cmd, check=True)


@pytest.fixture()
def restart_redis_target():
    """Cycle the `mcp-with-redis` container and wait for /health.

    The OAuth-state-persistence test calls this between a /register and a
    follow-up /token check.
    """

    def _do() -> None:
        _compose("restart", "mcp-with-redis")
        for _ in range(60):
            try:
                r = httpx.get(f"{REDIS_BASE}/health", timeout=2.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        pytest.fail("mcp-with-redis did not come back healthy after restart")

    return _do
