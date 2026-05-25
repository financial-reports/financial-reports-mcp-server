# Convenience wrappers around docker compose + pytest.
# Run `make help` for a summary.

.PHONY: help dev check-env install test test-unit test-e2e test-e2e-redis test-e2e-all \
        build up up-redis down logs probe regen audit eval eval-fast

VENV ?= .venv
PY := $(VENV)/bin/python

help:
	@echo "Targets:"
	@echo "  dev             one-shot: venv -> install -> check-env -> regen -> serve on :8000"
	@echo "  check-env       fail fast if required Cognito env vars are unset"
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

dev: check-env
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements.txt -r requirements-test.txt
	set -a; [ -f .env ] && . ./.env; set +a; $(PY) scripts/generate_mcp_tools.py
	set -a; [ -f .env ] && . ./.env; set +a; \
		$(PY) -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000

check-env:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	missing=""; \
	for v in COGNITO_USER_POOL_ID COGNITO_CLIENT_ID COGNITO_CLIENT_SECRET; do \
		eval "val=\$$$$v"; [ -n "$$val" ] || missing="$$missing $$v"; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "ERROR: missing required env var(s):$$missing"; \
		echo "Copy .env.example to .env and fill in the Cognito values (see docs/SELF-HOSTING.md)."; \
		exit 1; \
	fi; \
	echo "check-env: all required Cognito vars present."

install:
	pip install -r requirements.txt
	pip install -r requirements-test.txt

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

audit:
	./venv/bin/python scripts/audit_token_budget.py > docs/token-budget.md
	@echo "Baseline written to docs/token-budget.md"

# Fast, deterministic prompt-registration tests. Run on every PR.
eval-fast:
	./venv/bin/python -m pytest tests/eval/ -v

# LLM-backed eval against the local MCP. Requires:
#   - DEV_MODE_API_KEY set in .env and the local server running on :8000
#   - A sibling checkout of financial-reports/mcp-evals at ../mcp-evals
#     (override with EVALS_DIR=/path/to/mcp-evals)
#   - ANTHROPIC_API_KEY in the environment
EVALS_DIR ?= ../mcp-evals
eval:
	@if [ ! -d "$(EVALS_DIR)" ]; then \
	  echo "ERROR: $(EVALS_DIR) not found. Clone financial-reports/mcp-evals or pass EVALS_DIR=..."; \
	  exit 1; \
	fi
	cd $(EVALS_DIR) && \
	  FR_MCP_URL=http://localhost:8000/mcp \
	  FR_MCP_TOKEN=dev-mode-bypass \
	  python run_eval.py --models claude --runs 3
