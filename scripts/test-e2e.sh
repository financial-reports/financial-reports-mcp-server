#!/usr/bin/env bash
# End-to-end test runner.
#
# Boots the full image via docker compose, waits for /health, then runs the
# pytest suite under tests/e2e/ which probes the live container exactly the
# way Claude / ChatGPT / Cursor do.
#
# Designed to catch the class of bug that broke production in v1.4.37-audit2:
# unit tests passed (TestClient app routing), but the actual OAuth /register
# call against the real Redis backend errored at runtime. Everything in this
# script runs against real HTTP — TestClient is bypassed.
#
# Usage:
#   scripts/test-e2e.sh           # DiskStore variant only (fast)
#   scripts/test-e2e.sh redis     # Redis-backed variant only
#   scripts/test-e2e.sh both      # both, plus the persistence-across-restart test
#
# Exit code 0 = all checks passed. Anything else = a regression you should
# treat as blocking before deploy.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PROFILE="${1:-default}"

cleanup() {
    echo "::: tearing down docker compose stack"
    docker compose -f docker-compose.test.yml --profile redis down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "::: building image"
docker compose -f docker-compose.test.yml build mcp

if [[ "$PROFILE" == "redis" || "$PROFILE" == "both" ]]; then
    echo "::: starting mcp + redis sidecar (Redis-backed OAuth state)"
    docker compose -f docker-compose.test.yml --profile redis up -d redis mcp-with-redis
fi
if [[ "$PROFILE" == "default" || "$PROFILE" == "both" ]]; then
    echo "::: starting mcp (DiskStore OAuth state)"
    docker compose -f docker-compose.test.yml up -d mcp
fi

wait_health() {
    local url="$1" name="$2"
    for _ in $(seq 1 60); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "::: ERROR: $name never came up. Container logs follow:" >&2
    docker compose -f docker-compose.test.yml logs --no-color || true
    return 1
}

if [[ "$PROFILE" == "default" || "$PROFILE" == "both" ]]; then
    wait_health "http://localhost:8000/health" "mcp"
fi
if [[ "$PROFILE" == "redis" || "$PROFILE" == "both" ]]; then
    wait_health "http://localhost:8001/health" "mcp-with-redis"
fi

echo "::: services up — running e2e probes"
TARGETS=()
[[ "$PROFILE" == "default" || "$PROFILE" == "both" ]] && TARGETS+=("default")
[[ "$PROFILE" == "redis" || "$PROFILE" == "both" ]] && TARGETS+=("redis")

MCP_E2E_TARGETS="${TARGETS[*]}" python -m pytest tests/e2e -v --tb=short
