# Convenience wrappers around docker compose + pytest.
# Run `make help` for a summary.

.PHONY: help install test test-unit test-e2e test-e2e-redis test-e2e-all \
        build up up-redis down logs probe regen

help:
	@echo "Targets:"
	@echo "  install         pip install runtime + dev/test dependencies"
	@echo "  test            unit tests only (fast, no docker)"
	@echo "  test-unit       alias for 'test'"
	@echo "  test-e2e        e2e against the DiskStore variant (docker required)"
	@echo "  test-e2e-redis  e2e against the Redis variant (docker required)"
	@echo "  test-e2e-all    both variants + the across-restart persistence test"
	@echo "  build           docker compose build"
	@echo "  up              boot the DiskStore stack on :8000"
	@echo "  up-redis        boot the Redis-backed stack on :8001 (+ redis sidecar)"
	@echo "  down            tear down the stack"
	@echo "  logs            follow the mcp container logs"
	@echo "  probe           hit /health, /icon.png, /.well-known/* against :8000"
	@echo "  regen           re-render src/financial_reports_mcp.py from the live OpenAPI"

install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio respx

test test-unit:
	pytest tests/test_*.py -v

test-e2e:
	./scripts/test-e2e.sh default

test-e2e-redis:
	./scripts/test-e2e.sh redis

test-e2e-all:
	./scripts/test-e2e.sh both

build:
	docker compose -f docker-compose.test.yml build mcp

up:
	docker compose -f docker-compose.test.yml up -d mcp

up-redis:
	docker compose -f docker-compose.test.yml --profile redis up -d redis mcp-with-redis

down:
	docker compose -f docker-compose.test.yml --profile redis down --volumes --remove-orphans

logs:
	docker compose -f docker-compose.test.yml logs -f mcp

probe:
	@echo "::: /health"        && curl -fsS http://localhost:8000/health | head -c 200; echo
	@echo "::: /icon.png"      && curl -sS -o /dev/null -w "HTTP %{http_code} %{content_type} %{size_download}B\n" http://localhost:8000/icon.png
	@echo "::: /.well-known/oauth-protected-resource (bare)" && curl -fsS http://localhost:8000/.well-known/oauth-protected-resource | head -c 300; echo
	@echo "::: /.well-known/oauth-protected-resource/mcp"    && curl -fsS http://localhost:8000/.well-known/oauth-protected-resource/mcp | head -c 300; echo

regen:
	python scripts/generate_mcp_tools.py
