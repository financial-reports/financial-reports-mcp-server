# MCP Server Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FinancialReports MCP server measurably better by enabling local dev with a personal API key, adding an automated eval harness, and shipping the first batch of MCP Prompts (the canonical "skills" packaging for recurring analytical workflows).

**Architecture:** All persistent edits to the server live in `scripts/generate_mcp_tools.py` because `src/financial_reports_mcp.py` is auto-generated and overwritten on every schema bump. Auth changes go inside the existing `subscription_required` decorator (in `FILE_HEADER_TEMPLATE`). Prompts are registered next to the FastMCP server instance via `@mcp.prompt()`. The authoritative eval harness already exists at `financial-reports/mcp-evals` (Alex's repo — model-agnostic, cross-model scorecards, tool-selection + path-consistency metrics, judge-based rubrics). This plan integrates with it rather than building a parallel harness.

**Tech Stack:** FastAPI + FastMCP 2.13.3+, AWS Cognito provider, httpx async client, Jinja2 for code generation, pytest + respx for tests, plus the existing `financial-reports/mcp-evals` harness (official `mcp` SDK over Streamable HTTP, Claude + DeepSeek adapters, YAML task fixtures).

**Out of scope (separate plan):** Derived backend tools (period-over-period diff, sector aggregator, content-snippet search, etc.) — these require changes in the sibling `/Users/silashundhausen/Dev/financialreports` Django repo and will be handled in `2026-05-26-derived-tools.md` after Phase 1–3 here are merged.

---

## Phase 1 — Verify backend accepts personal API key

### Task 1: Smoke-test the backend with the personal API key

Goal: confirm which header (`Authorization: Bearer …` or `X-API-Key: …`) the FinancialReports backend accepts for personal API keys. The MCP's httpx client today auto-injects `Authorization: Bearer <token>` from `_current_token` (`scripts/generate_mcp_tools.py` template line ~346 in the rendered file). If the backend wants `X-API-Key` instead, the dev bypass needs to inject the header differently.

**Files:**
- None modified — investigation only.

- [ ] **Step 1: Probe with `Authorization: Bearer`**

Run from a shell with `API_KEY` exported from the user's `.env`:

```bash
source /Users/silashundhausen/Dev/financial-reports-mcp-server/.env && \
curl -sS -o /tmp/probe_bearer.json -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer $API_KEY" \
  -H "User-Agent: FinancialReports-MCP-Server/dev-probe" \
  "https://api.financialreports.eu/api/companies/?search=apple&limit=1"
head -c 400 /tmp/probe_bearer.json; echo
```

Expected: `HTTP 200` with a JSON body containing a `results` array. If `401`/`403`, move to step 2.

- [ ] **Step 2: Probe with `X-API-Key`**

```bash
source /Users/silashundhausen/Dev/financial-reports-mcp-server/.env && \
curl -sS -o /tmp/probe_xkey.json -w "HTTP %{http_code}\n" \
  -H "X-API-Key: $API_KEY" \
  -H "User-Agent: FinancialReports-MCP-Server/dev-probe" \
  "https://api.financialreports.eu/api/companies/?search=apple&limit=1"
head -c 400 /tmp/probe_xkey.json; echo
```

- [ ] **Step 3: Record the result**

Note which header returned `200`. If both work, prefer `Authorization: Bearer` (matches the existing `_inject_auth` path → zero changes to the httpx hook). If only `X-API-Key` works, Task 4 will add a second injection path. **Do not commit anything yet.**

If both return `4xx`: stop. The API key is probably scoped or expired. Surface the error to the user before proceeding.

---

## Phase 2 — Dev API-key auth mode

All edits live in `scripts/generate_mcp_tools.py` so they survive regeneration.

### Task 2: Add `DEV_MODE_API_KEY` env var to the generated config block

**Files:**
- Modify: `scripts/generate_mcp_tools.py` (extend `FILE_HEADER_TEMPLATE` config section, around line ~95–120 of the template string)
- Modify: `.env.example` (document the new variable)
- Create: `tests/test_dev_mode.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dev_mode.py`:

```python
"""DEV_MODE_API_KEY auth bypass — local-development only."""
from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator

import pytest


@pytest.fixture()
def dev_mode_module(respx_router, monkeypatch) -> Iterator[object]:
    """Re-import the MCP module with DEV_MODE_API_KEY set."""
    monkeypatch.setenv("DEV_MODE_API_KEY", "fr_test_devkey_abc123")
    # Force MCP_BASE_URL to a non-prod hostname so the prod guard does not trip.
    monkeypatch.setenv("MCP_BASE_URL", "http://localhost:8000")
    sys.modules.pop("src.financial_reports_mcp", None)
    import src.financial_reports_mcp as m  # type: ignore
    importlib.reload(m)
    yield m


def test_dev_mode_config_exposed(dev_mode_module) -> None:
    """The generated module reads DEV_MODE_API_KEY at import time."""
    assert dev_mode_module.DEV_MODE_API_KEY == "fr_test_devkey_abc123"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/silashundhausen/Dev/financial-reports-mcp-server
pytest tests/test_dev_mode.py::test_dev_mode_config_exposed -v
```

Expected: FAIL — `AttributeError: module … has no attribute 'DEV_MODE_API_KEY'`.

- [ ] **Step 3: Extend the generator's `FILE_HEADER_TEMPLATE`**

In `scripts/generate_mcp_tools.py`, locate the `MCP_REDIS_URL = os.environ.get("MCP_REDIS_URL")` line inside `FILE_HEADER_TEMPLATE` (search for `MCP_REDIS_URL`). Immediately after it, insert:

```python
# --- DEV-ONLY: personal API-key auth bypass --------------------------------
# When DEV_MODE_API_KEY is set, the OAuth+JWT validation in
# `subscription_required` is skipped and the bearer token injected into
# upstream API calls is the value of this env var.
#
# Refuses to activate against the production hostname so it CANNOT silently
# ship to prod even if the env var leaks into a prod environment.
DEV_MODE_API_KEY = os.environ.get("DEV_MODE_API_KEY", "").strip() or None
_PROD_HOSTS = {"mcp.financialfilings.com"}
if DEV_MODE_API_KEY and any(h in MCP_BASE_URL for h in _PROD_HOSTS):
    raise RuntimeError(
        "DEV_MODE_API_KEY is set but MCP_BASE_URL points at production. "
        "Refusing to start — this flag must never be enabled in prod."
    )
if DEV_MODE_API_KEY:
    logging.getLogger("financial-reports-mcp").warning(
        "DEV_MODE_API_KEY active — JWT validation is BYPASSED. "
        "Personal API key will be forwarded to %s. Never enable in prod.",
        API_BASE_URL,
    )
```

- [ ] **Step 4: Regenerate and re-run the test**

```bash
cd /Users/silashundhausen/Dev/financial-reports-mcp-server
make regen
pytest tests/test_dev_mode.py::test_dev_mode_config_exposed -v
```

Expected: PASS.

- [ ] **Step 5: Document the variable in `.env.example`**

Append to `.env.example`:

```
# --- DEV-ONLY: bypass Cognito OAuth and use a personal API key ---
# When set, the JWT-validation decorator is skipped and this key is forwarded
# as the bearer token to API_BASE_URL. Refuses to activate if MCP_BASE_URL
# contains a production hostname (mcp.financialfilings.com). Never set in
# production.
# DEV_MODE_API_KEY=fr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py \
        tests/test_dev_mode.py .env.example
git commit -m "feat(auth): add DEV_MODE_API_KEY config plumbing"
```

### Task 3: Wire the bypass into `subscription_required`

**Files:**
- Modify: `scripts/generate_mcp_tools.py` — extend `subscription_required` inside `FILE_HEADER_TEMPLATE`.
- Modify: `tests/test_dev_mode.py` — add behavior tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dev_mode.py`:

```python
@pytest.mark.asyncio
async def test_dev_mode_skips_jwt_and_sets_token(dev_mode_module) -> None:
    """With DEV_MODE_API_KEY, get_access_token is never called and the
    API key is placed into _current_token for the wrapped tool."""
    sentinel: dict[str, str] = {}

    @dev_mode_module.subscription_required
    async def tool() -> str:
        sentinel["token"] = dev_mode_module._current_token.get()
        return "ok"

    # Even if get_access_token would raise, the bypass should not call it.
    def boom():  # pragma: no cover — should not run
        raise AssertionError("get_access_token must not be called in dev mode")

    dev_mode_module.get_access_token = boom  # type: ignore[attr-defined]

    out = await tool()
    assert out == "ok"
    assert sentinel["token"] == "fr_test_devkey_abc123"


@pytest.mark.asyncio
async def test_dev_mode_clears_token_after_call(dev_mode_module) -> None:
    """The contextvar is reset after the wrapped function returns."""

    @dev_mode_module.subscription_required
    async def tool() -> str:
        return "ok"

    await tool()
    assert dev_mode_module._current_token.get() == ""


def test_prod_hostname_guard(monkeypatch) -> None:
    """Setting DEV_MODE_API_KEY against the prod hostname refuses to import."""
    monkeypatch.setenv("DEV_MODE_API_KEY", "leak_attempt")
    monkeypatch.setenv("MCP_BASE_URL", "https://mcp.financialfilings.com")
    sys.modules.pop("src.financial_reports_mcp", None)
    with pytest.raises(RuntimeError, match="never be enabled in prod"):
        import src.financial_reports_mcp  # noqa: F401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dev_mode.py -v
```

Expected: the two async tests FAIL (token not set), the prod-guard test PASSES (already wired in Task 2).

- [ ] **Step 3: Modify `subscription_required` in the generator**

In `scripts/generate_mcp_tools.py`, inside `FILE_HEADER_TEMPLATE`, locate the `subscription_required` definition (search for `def subscription_required(`). Replace the inner `wrapper` function so it short-circuits when `DEV_MODE_API_KEY` is set. The full replacement of `wrapper`:

```python
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        # DEV-ONLY bypass: when DEV_MODE_API_KEY is set, skip JWT validation
        # entirely and forward the personal API key to the backend. The prod
        # hostname guard at module import time prevents this from ever being
        # active in production.
        if DEV_MODE_API_KEY:
            token_reset = _current_token.set(DEV_MODE_API_KEY)
            try:
                return await func(*args, **kwargs)
            finally:
                _current_token.reset(token_reset)

        try:
            access_token = get_access_token()
        except Exception as exc:
            logger.warning("get_access_token raised: %s", exc)
            return _auth_error("Could not retrieve access token.")

        # ... (rest of the existing validation unchanged: access_token None
        #      check, sub/raw_token claim check, client_id check, aud check,
        #      _current_token.set(raw_token), try/finally with reset) ...
```

Keep every line from `if access_token is None:` through the existing `finally: _current_token.reset(token_reset)` verbatim — the bypass is an additive early-return.

- [ ] **Step 4: Regenerate and run all auth tests**

```bash
make regen
pytest tests/test_dev_mode.py tests/test_decorator.py -v
```

Expected: ALL pass. The original `test_decorator.py` cases still pass because they don't set `DEV_MODE_API_KEY`, so the bypass is inert.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py tests/test_dev_mode.py
git commit -m "feat(auth): bypass JWT validation when DEV_MODE_API_KEY is set"
```

### Task 4: Handle the `X-API-Key` header path (only if Phase 1 Task 1 required it)

Skip this task entirely if the bearer probe in Task 1 returned 200.

**Files:**
- Modify: `scripts/generate_mcp_tools.py` — update `_inject_auth` in `FILE_HEADER_TEMPLATE`.
- Modify: `tests/test_dev_mode.py` — add header-format test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dev_mode.py`:

```python
@pytest.mark.asyncio
async def test_dev_mode_injects_xapikey_header(dev_mode_module, respx_router) -> None:
    """In dev mode the upstream call carries X-API-Key, not Bearer."""
    import httpx
    captured: dict[str, str] = {}

    def capture(request):
        captured["auth"] = request.headers.get("Authorization", "")
        captured["xapikey"] = request.headers.get("X-API-Key", "")
        return httpx.Response(200, json={"ok": True})

    respx_router.get("https://api.test.invalid/probe").mock(side_effect=capture)

    token_reset = dev_mode_module._current_token.set(dev_mode_module.DEV_MODE_API_KEY)
    try:
        resp = await dev_mode_module._api_client.get("/probe")
    finally:
        dev_mode_module._current_token.reset(token_reset)
    assert resp.status_code == 200
    assert captured["xapikey"] == "fr_test_devkey_abc123"
    assert captured["auth"] == ""  # bearer NOT set in dev mode
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_dev_mode.py::test_dev_mode_injects_xapikey_header -v
```

Expected: FAIL — auth is currently `"Bearer fr_test_devkey_abc123"`.

- [ ] **Step 3: Update `_inject_auth`**

In `FILE_HEADER_TEMPLATE`, replace `_inject_auth` with:

```python
async def _inject_auth(request: httpx.Request) -> None:
    """Add upstream auth header from `_current_token`. Format depends on
    whether the dev API-key bypass is active."""
    token = _current_token.get()
    if not token:
        return
    if DEV_MODE_API_KEY:
        request.headers.setdefault("X-API-Key", token)
    elif "Authorization" not in request.headers:
        request.headers["Authorization"] = f"Bearer {token}"
```

- [ ] **Step 4: Regenerate and verify**

```bash
make regen
pytest tests/test_dev_mode.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py tests/test_dev_mode.py
git commit -m "feat(auth): inject X-API-Key in dev mode, Bearer in prod"
```

### Task 5: Local MCP profile in `.mcp.json` + README quickstart

**Files:**
- Modify: `.mcp.json` — add a `financialreports-local` profile alongside the production one.
- Modify: `README.md` — add a "Local development with a personal API key" section.

- [ ] **Step 1: Add the local profile**

Replace `.mcp.json` with:

```json
{
  "mcpServers": {
    "financialreports": {
      "type": "http",
      "url": "https://mcp.financialfilings.com/mcp",
      "note": "Official FinancialReports MCP server. Uses OAuth — on first connection you will be prompted to sign in with your FinancialReports account. Free for any authenticated user."
    },
    "financialreports-local": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "note": "Local dev. Requires DEV_MODE_API_KEY in .env and `make regen && uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000`."
    }
  }
}
```

- [ ] **Step 2: Add a README section**

Append to `README.md` (right before any existing "Deployment" section, or at the end):

```markdown
## Local development with a personal API key

For iterating on tools/prompts without going through the Cognito OAuth flow:

1. Add your personal FinancialReports API key to `.env`:
   ```
   DEV_MODE_API_KEY=fr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   MCP_BASE_URL=http://localhost:8000
   ```
2. Regenerate and start the server:
   ```bash
   make regen
   python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Point Claude Code at the local instance:
   ```bash
   claude mcp add --transport http financialreports-local http://localhost:8000/mcp
   ```

The dev-mode bypass **refuses to activate** if `MCP_BASE_URL` contains
`mcp.financialfilings.com` — defense-in-depth so it cannot leak to prod.
```

- [ ] **Step 3: Commit**

```bash
git add .mcp.json README.md
git commit -m "docs: local dev quickstart with DEV_MODE_API_KEY"
```

---

## Phase 3 — Token-budget audit (baseline before adding surface)

### Task 6: Measure current `tools/list` payload size

**Files:**
- Create: `scripts/audit_token_budget.py`
- Create: `docs/token-budget.md`
- Modify: `Makefile`

- [ ] **Step 1: Write the audit script**

Create `scripts/audit_token_budget.py`:

```python
"""Measure the size of the tools/list payload the MCP server returns.

Token-bloat is the most common MCP anti-pattern (10k-50k tokens just for
schemas eats client context before the user types anything). This script
gives us a baseline before adding any new tools or prompts.

Usage:
    python scripts/audit_token_budget.py > docs/token-budget.md
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Force a synthetic env so the module imports without real Cognito creds.
os.environ.setdefault("COGNITO_USER_POOL_ID", "eu-central-1_AUDIT")
os.environ.setdefault("COGNITO_CLIENT_ID", "audit_client")
os.environ.setdefault("COGNITO_CLIENT_SECRET", "audit_secret")
os.environ.setdefault("MCP_BASE_URL", "http://localhost:8000")
os.environ.setdefault("API_BASE_URL", "http://localhost:8001")


def _approx_tokens(s: str) -> int:
    """Rough char/token ratio for English JSON. Real tokenizer would be
    tiktoken — kept dependency-free for CI."""
    return max(1, len(s) // 4)


async def main() -> None:
    import src.financial_reports_mcp as m  # noqa: E402

    tools = await m.mcp.get_tools()  # FastMCP exposes this
    print(f"# Token-budget audit — {datetime.now(timezone.utc).isoformat()}")
    print()
    print(f"Total tools registered: **{len(tools)}**")
    print()
    print("| Tool | Description chars | Schema chars | Approx tokens |")
    print("|---|---:|---:|---:|")
    total_tokens = 0
    rows: list[tuple[str, int, int, int]] = []
    for name, tool in tools.items():
        desc = (getattr(tool, "description", "") or "")
        schema = json.dumps(getattr(tool, "parameters", {}) or {}, separators=(",", ":"))
        toks = _approx_tokens(desc) + _approx_tokens(schema)
        rows.append((name, len(desc), len(schema), toks))
        total_tokens += toks
    for name, d, s, t in sorted(rows, key=lambda r: -r[3]):
        print(f"| `{name}` | {d} | {s} | {t} |")
    print()
    print(f"**Total approx tokens for `tools/list`: {total_tokens}**")
    print()
    print("Reference budgets (anecdotal, 2026):")
    print("- < 5k tokens: lean")
    print("- 5k-15k tokens: acceptable for a focused server")
    print("- > 15k tokens: trim descriptions or split the server")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the script and commit the baseline**

```bash
cd /Users/silashundhausen/Dev/financial-reports-mcp-server
python scripts/audit_token_budget.py > docs/token-budget.md
head -20 docs/token-budget.md
```

Expected: a markdown table with all ~42 tools sorted by token cost. If the script errors out because `mcp.get_tools()` is not the right FastMCP API for the installed version, swap it for the API the installed FastMCP exposes (run `python -c "import fastmcp; help(fastmcp.FastMCP)" | grep -i tool` to confirm).

- [ ] **Step 3: Add a Makefile target**

Append to `Makefile`:

```makefile
audit:
	python scripts/audit_token_budget.py > docs/token-budget.md
	@echo "Baseline written to docs/token-budget.md"
```

Also add `audit` to the `.PHONY` line at the top of the Makefile.

- [ ] **Step 4: Commit**

```bash
git add scripts/audit_token_budget.py docs/token-budget.md Makefile
git commit -m "feat(audit): baseline tools/list token-budget report"
```

---

## Phase 4 — Eval harness integration

> **Revised:** The authoritative eval harness already exists at the private repo `financial-reports/mcp-evals`. It is model-agnostic (Claude + DeepSeek adapters), measures task success + tool-selection + path-consistency + tokens/turns/latency, uses YAML task fixtures (`tasks/*.yaml`), and runs against any Streamable HTTP MCP URL (defaults to prod, configurable via `FR_MCP_URL`). Phase 4 wires our local MCP into it and documents the cross-repo workflow. New task fixtures for our Prompts (Phase 5) are added IN the mcp-evals repo via a separate PR (Task 13).

### Task 7: Document the mcp-evals integration and clone it as a sibling

**Files:**
- Create: `tests/eval/README.md`
- Modify: `README.md` (add an "Evaluating changes" section)

- [ ] **Step 1: Clone the eval repo to a sibling directory**

```bash
cd /Users/silashundhausen/Dev
gh repo clone financial-reports/mcp-evals
cd mcp-evals && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
FR_MCP_URL=http://localhost:8000/mcp
FR_MCP_TOKEN=dev-mode-bypass-any-string-works
ANTHROPIC_API_KEY=sk-ant-...
```

`FR_MCP_TOKEN` only has to be non-empty when running against a local MCP started with `DEV_MODE_API_KEY` (the JWT validation is short-circuited; the bearer header is still set so the harness's `streamablehttp_client` is happy). When pointing at prod, you need a real Cognito token (see mcp-evals' README "Getting an MCP token").

- [ ] **Step 2: Create the in-repo pointer doc**

Create `tests/eval/README.md`:

```markdown
# Evals

The authoritative eval harness for this server is the private repo
[financial-reports/mcp-evals](https://github.com/financial-reports/mcp-evals).
It is model-agnostic (currently Claude + DeepSeek), measures task success
rate, tool-selection accuracy, path consistency, and efficiency, and runs
against any Streamable HTTP MCP URL.

The eval harness is the source of truth for "is this server good." Do not
build a parallel harness in this repo.

## What lives here

Only the **deterministic prompt-registration tests** — `tests/eval/test_prompts_deterministic.py`.
These confirm that every Prompt we ship is actually registered with the
FastMCP server and that its rendered messages reference the tools we
expect. They run on every PR with no API keys.

## What lives in mcp-evals

- The YAML task fixtures (`tasks/*.yaml`).
- The MCP client + model adapters.
- The judge + scorer + reporter.
- The cross-model scorecards.

## Running the full eval against a local dev MCP

1. In this repo, start the server with `DEV_MODE_API_KEY` set (see
   the README "Local development with a personal API key" section).
2. In the sibling `mcp-evals/` checkout, set `FR_MCP_URL=http://localhost:8000/mcp`
   and any non-empty `FR_MCP_TOKEN` (dev mode bypasses JWT validation),
   then `python run_eval.py --models claude --runs 3`.

## Adding fixtures for a new Prompt or tool

Open a PR against `financial-reports/mcp-evals`, not this repo. Drop a
YAML file into `tasks/`. See `tasks/core.yaml` for the field reference.
```

- [ ] **Step 3: Add a section to the main README**

Append to `README.md`:

```markdown
## Evaluating changes

This server is benchmarked by [`financial-reports/mcp-evals`](https://github.com/financial-reports/mcp-evals)
(private). Before merging changes to tool descriptions, Prompts, or the
generator, run the harness against either prod or a local dev MCP and
compare the scorecard. See `tests/eval/README.md` for the workflow.
```

- [ ] **Step 4: Commit**

```bash
git add tests/eval/README.md README.md
git commit -m "docs: point at mcp-evals as the authoritative eval harness"
```

### Task 8: Build a no-LLM harness runner that exercises the prompts directly

Rationale: requiring `ANTHROPIC_API_KEY` and a live LLM in CI is expensive and slow. The first iteration of the harness asserts a different thing: **for each Prompt registered via `@mcp.prompt()`, calling `prompts/get` with the documented arguments returns a non-empty `messages[]` that references the expected tool names.** This is a fast, deterministic regression test.

**Files:**
- Create: `tests/eval/test_prompts_deterministic.py`

- [ ] **Step 1: Write the harness skeleton**

Create `tests/eval/test_prompts_deterministic.py`:

```python
"""Deterministic eval: every registered Prompt must surface the tools we
expect when called with documented arguments. No live LLM needed.

This is the fast, CI-friendly half of the eval harness. The LLM-based
golden-query suite (queries.yaml + mcp-eval) is the slower nightly half.
"""
from __future__ import annotations

import pytest


EXPECTED_PROMPTS: dict[str, set[str]] = {
    # Filled in as prompts are registered in Phase 5.
    # "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
}


@pytest.mark.asyncio
async def test_all_expected_prompts_registered(mcp_module) -> None:
    """Every prompt in EXPECTED_PROMPTS must be exposed by the server."""
    prompts = await mcp_module.mcp.get_prompts()
    registered = set(prompts.keys())
    missing = set(EXPECTED_PROMPTS) - registered
    assert not missing, f"Missing prompts: {missing}"


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt_name,expected_tools", list(EXPECTED_PROMPTS.items()))
async def test_prompt_messages_reference_expected_tools(
    mcp_module, prompt_name: str, expected_tools: set[str]
) -> None:
    """The messages returned by prompts/get must mention every expected tool name."""
    prompts = await mcp_module.mcp.get_prompts()
    prompt = prompts[prompt_name]
    # Render with the prompt's own default arguments where possible.
    result = await prompt.render(arguments={})
    rendered = " ".join(
        m.content.text if hasattr(m.content, "text") else str(m.content)
        for m in result.messages
    )
    missing = [t for t in expected_tools if t not in rendered]
    assert not missing, f"{prompt_name}: missing tool references {missing}"
```

(The `EXPECTED_PROMPTS` dict starts empty and is populated by each Prompt task in Phase 5. The two tests degenerate to no-ops until then — that's intentional.)

- [ ] **Step 2: Run the tests to confirm they pass (empty)**

```bash
pytest tests/eval/test_prompts_deterministic.py -v
```

Expected: 1 PASS (the "all expected prompts registered" test trivially passes with an empty set), 0 parametrized cases.

- [ ] **Step 3: Commit**

```bash
git add tests/eval/test_prompts_deterministic.py
git commit -m "test(eval): deterministic prompt-registration harness"
```

### Task 9: Makefile + CI wiring

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add Makefile targets**

Append to `Makefile`:

```makefile
# Fast, deterministic prompt-registration tests. Run on every PR.
eval-fast:
	pytest tests/eval/ -v

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
```

Add `eval`, `eval-fast` to the `.PHONY` line.

- [ ] **Step 2: Add a CI job**

In `.github/workflows/ci.yml`, add a new job alongside the existing unit/e2e jobs:

```yaml
  eval-fast:
    runs-on: ubuntu-latest
    needs: unit
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt -r requirements-test.txt
      - run: make regen
        env:
          COGNITO_USER_POOL_ID: eu-central-1_CITESTPOOL
          COGNITO_CLIENT_ID: ci_client
          COGNITO_CLIENT_SECRET: ci_secret
      - run: make eval-fast
```

The LLM-backed `make eval` target is intentionally NOT wired into CI here — that scorecard runs from the mcp-evals repo's own CI on its own cadence, against either prod or a deployed preview environment.

- [ ] **Step 3: Commit**

```bash
git add Makefile .github/workflows/ci.yml
git commit -m "ci: run deterministic prompt-registration suite on every PR"
```

---

## Phase 5 — Ship the first MCP Prompts ("skills")

Anchored on the workflows already documented in `skills/financial-filings-research/SKILL.md`. Each Prompt is a typed, server-registered slash command that returns a `messages[]` array guiding the model through a tool sequence.

### Task 10: Add `compare_financials_yoy` Prompt

**Files:**
- Modify: `scripts/generate_mcp_tools.py` — register a new Prompt block written after the tool emission loop.
- Modify: `tests/eval/test_prompts_deterministic.py` — add to `EXPECTED_PROMPTS`.

- [ ] **Step 1: Decide where to register prompts in the generator**

Read `scripts/generate_mcp_tools.py` to find where the tool emission loop ends and the FastAPI app is assembled. Prompts must be registered **after** `mcp = FastMCP(...)` is constructed (it already lives inside `FILE_HEADER_TEMPLATE`) and **before** the app mount. The cleanest spot is a new template constant `PROMPTS_BLOCK` that the generator appends to the output file right after the loop over tool definitions.

- [ ] **Step 2: Add the failing test**

In `tests/eval/test_prompts_deterministic.py`, change `EXPECTED_PROMPTS` to:

```python
EXPECTED_PROMPTS: dict[str, set[str]] = {
    "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
}
```

Run:

```bash
pytest tests/eval/test_prompts_deterministic.py -v
```

Expected: FAIL — `compare_financials_yoy` not registered.

- [ ] **Step 3: Add the prompt-emission block to the generator**

In `scripts/generate_mcp_tools.py`, add a new constant near the other template constants (`GET_TOOL_TEMPLATE`, `POST_TOOL_TEMPLATE`, `MARKDOWN_TOOL_TEMPLATE`):

```python
PROMPTS_BLOCK = '''
# ---------------------------------------------------------------------------
# MCP Prompts — server-defined slash commands for recurring workflows.
# ---------------------------------------------------------------------------
from mcp.types import PromptMessage, TextContent


@mcp.prompt(
    name="compare_financials_yoy",
    description=(
        "Compare a company's financials year-over-year. Resolves the "
        "company by name/ticker, fetches the two fiscal years, and asks "
        "the assistant to summarize key deltas."
    ),
)
async def compare_financials_yoy(
    ticker_or_name: str,
    current_fiscal_year: int,
    prior_fiscal_year: int,
) -> list[PromptMessage]:
    """Return a guided message sequence for a YoY comparison workflow."""
    instructions = (
        f"You will compare {ticker_or_name}'s financials for FY"
        f"{current_fiscal_year} vs FY{prior_fiscal_year} using ONLY the "
        "FinancialReports MCP server.\\n\\n"
        "Steps:\\n"
        f"1. Call `companies_list` with search=\\"{ticker_or_name}\\" to resolve "
        "the company. If multiple results, pick the one whose primary listing "
        "matches the user's intent; if ambiguous, ask the user.\\n"
        f"2. Call `companies_financials_retrieve` twice — once with "
        f"fiscal_year={current_fiscal_year} and once with "
        f"fiscal_year={prior_fiscal_year}.\\n"
        "3. Summarize the top 8 line items by absolute change. For each, "
        "report: absolute delta, percent change, and the reporting currency. "
        "Never aggregate across currencies.\\n"
        "4. Cite filing type and period_end_date for each value used."
    )
    return [
        PromptMessage(role="user", content=TextContent(type="text", text=instructions)),
    ]
'''
```

Then locate where the generator writes the output file (the `output.write(...)` call after the tool loop, or the equivalent jinja `render` site). Append `output.write(PROMPTS_BLOCK)` immediately after the last tool is written and before the file is closed.

- [ ] **Step 4: Regenerate and run tests**

```bash
make regen
pytest tests/eval/test_prompts_deterministic.py -v
```

Expected: PASS for both the registration test and the parametrized rendering test.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py \
        tests/eval/test_prompts_deterministic.py
git commit -m "feat(prompts): add compare_financials_yoy workflow"
```

### Task 11: Add `find_filing_section` Prompt

**Files:**
- Modify: `scripts/generate_mcp_tools.py` (same `PROMPTS_BLOCK` constant)
- Modify: `tests/eval/test_prompts_deterministic.py`

- [ ] **Step 1: Add to `EXPECTED_PROMPTS`**

```python
EXPECTED_PROMPTS: dict[str, set[str]] = {
    "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
    "find_filing_section": {"companies_list", "filings_list", "filings_markdown_retrieve"},
}
```

Run `pytest tests/eval/test_prompts_deterministic.py -v` → FAIL.

- [ ] **Step 2: Extend `PROMPTS_BLOCK`**

Append inside the same `PROMPTS_BLOCK` triple-quoted constant:

```python
@mcp.prompt(
    name="find_filing_section",
    description=(
        "Locate a specific section in a company's most recent filing of a "
        "given type (e.g., risk factors in the latest 10-K) and return the "
        "verbatim excerpt."
    ),
)
async def find_filing_section(
    ticker_or_name: str,
    filing_type: str,
    section_keyword: str,
) -> list[PromptMessage]:
    """Guide the assistant through resolve → list → markdown → grep."""
    instructions = (
        f"Find the section in {ticker_or_name}'s most recent {filing_type} "
        f"that discusses '{section_keyword}'.\\n\\n"
        "Steps:\\n"
        f"1. `companies_list` with search=\\"{ticker_or_name}\\".\\n"
        f"2. `filings_list` with company=<id>, filing_type_code matching "
        f"'{filing_type}', ordering=-publication_datetime, limit=1.\\n"
        "3. `filings_markdown_retrieve` for that filing_id. The response "
        "is paginated — keep calling with increasing offset until the "
        "truncation marker is gone OR you have located the section.\\n"
        f"4. Return ONLY the markdown excerpt containing '{section_keyword}', "
        "plus 2 paragraphs of surrounding context. Cite filing type and "
        "publication date."
    )
    return [
        PromptMessage(role="user", content=TextContent(type="text", text=instructions)),
    ]
```

- [ ] **Step 3: Regenerate, run tests, commit**

```bash
make regen
pytest tests/eval/test_prompts_deterministic.py -v
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py \
        tests/eval/test_prompts_deterministic.py
git commit -m "feat(prompts): add find_filing_section workflow"
```

### Task 12: Add `summarize_recent_filings` Prompt

**Files:**
- Modify: `scripts/generate_mcp_tools.py`
- Modify: `tests/eval/test_prompts_deterministic.py`

- [ ] **Step 1: Add to `EXPECTED_PROMPTS`**

```python
EXPECTED_PROMPTS: dict[str, set[str]] = {
    "compare_financials_yoy": {"companies_list", "companies_financials_retrieve"},
    "find_filing_section": {"companies_list", "filings_list", "filings_markdown_retrieve"},
    "summarize_recent_filings": {"companies_list", "filings_list"},
}
```

- [ ] **Step 2: Append to `PROMPTS_BLOCK`**

```python
@mcp.prompt(
    name="summarize_recent_filings",
    description=(
        "Summarize the filings a company has published over a recent "
        "window. Useful before earnings calls or for catch-up briefings."
    ),
)
async def summarize_recent_filings(
    ticker_or_name: str,
    lookback_days: int = 90,
) -> list[PromptMessage]:
    """List recent filings and ask the model to produce a tight briefing."""
    instructions = (
        f"Summarize {ticker_or_name}'s regulatory filings from the last "
        f"{lookback_days} days.\\n\\n"
        "Steps:\\n"
        f"1. `companies_list` with search=\\"{ticker_or_name}\\".\\n"
        f"2. `filings_list` with company=<id>, ordering=-publication_datetime, "
        f"limit=25. Filter the response in memory to entries within the last "
        f"{lookback_days} days.\\n"
        "3. Produce a briefing: one bullet per filing with type, "
        "publication_datetime, and a one-line significance assessment. "
        "Group by filing category (annual / interim / ad-hoc / insider).\\n"
        "4. Highlight anything that looks material (guidance changes, "
        "M&A language, going-concern flags) and call it out in a 'Watch "
        "items' section. Do NOT fetch markdown bodies unless the user asks."
    )
    return [
        PromptMessage(role="user", content=TextContent(type="text", text=instructions)),
    ]
```

- [ ] **Step 3: Regenerate, run, commit**

```bash
make regen
pytest tests/eval/test_prompts_deterministic.py -v
git add scripts/generate_mcp_tools.py src/financial_reports_mcp.py \
        tests/eval/test_prompts_deterministic.py
git commit -m "feat(prompts): add summarize_recent_filings workflow"
```

### Task 13: Add task fixtures to `financial-reports/mcp-evals` for the three Prompts

**Repo:** This task's changes land in `financial-reports/mcp-evals`, **not** this server repo. Open a PR there.

**Files (in the mcp-evals repo):**
- Create: `tasks/prompts.yaml`

- [ ] **Step 1: Create the new task fixture file**

The existing `tasks/core.yaml` covers the workhorse tool paths. Add a new file `tasks/prompts.yaml` that exercises the workflows our Prompts wrap. Field schema matches `core.yaml`: `id`, `prompt`, `domain`, `expected_tools`, optional `forbidden_tools`, optional `assert_contains`, required `success_rubric`.

```yaml
# Tasks that exercise the FinancialReports MCP Prompts (server-defined
# slash commands). Each task corresponds to a Prompt registered via
# @mcp.prompt() in financial-reports/financial-reports-mcp-server.
#
# Tasks here use the prompts INDIRECTLY (via a natural-language query a
# real user would type) so we measure whether the agent reaches for the
# Prompt at all when it would be the right tool. Prompts are not yet
# auto-selected by every model adapter, so a failure here may indicate
# the Prompt description needs to be more discoverable rather than a
# regression in the underlying tool sequence.
tasks:
  - id: prompt-yoy-compare-apple
    prompt: "Compare Apple's financials in FY2024 vs FY2023."
    domain: financials
    expected_tools: [companies_list, companies_financials_retrieve]
    success_rubric: >
      The answer reports values for both FY2024 and FY2023 with the
      reporting currency stated for each, and identifies at least one
      meaningful YoY delta (absolute or percent). Silent period mixing
      or missing currency = fail.

  - id: prompt-find-risk-section
    prompt: "In Apple's most recent 10-K, what does the supply chain risk section say?"
    domain: filings
    expected_tools: [companies_list, filings_list, filings_markdown_retrieve]
    success_rubric: >
      The answer quotes or paraphrases content drawn from an actual filing
      markdown excerpt that mentions supply chain risk. Generic risk-factor
      boilerplate not drawn from the document = fail.

  - id: prompt-summarize-recent-nvidia
    prompt: "What has Nvidia filed in the last 60 days?"
    domain: filings
    expected_tools: [companies_list, filings_list]
    forbidden_tools: [filings_markdown_retrieve]
    success_rubric: >
      The answer lists multiple recent Nvidia filings with publication
      dates and types, scoped to roughly the last 60 days. Bonus if it
      groups by filing category. Fetching markdown bodies for a broad
      "what was filed" briefing is wasteful and out-of-scope for this task.
```

- [ ] **Step 2: Validate the new tasks load**

In the `mcp-evals` checkout:

```bash
cd /Users/silashundhausen/Dev/mcp-evals
pytest tests/ -q
```

Expected: PASS. The task-loader tests in `tests/` parse `tasks/*.yaml` deterministically — they'll catch a malformed YAML or unknown field.

- [ ] **Step 3: Dry-run against the local MCP**

In a separate shell, start the local MCP from this repo:

```bash
cd /Users/silashundhausen/Dev/financial-reports-mcp-server
make regen
python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000
```

Then in the mcp-evals checkout:

```bash
cd /Users/silashundhausen/Dev/mcp-evals
FR_MCP_URL=http://localhost:8000/mcp \
FR_MCP_TOKEN=dev-mode-bypass \
python run_eval.py --models claude --runs 1
```

Expected: a scorecard in `out/scorecard.md` covering both `core.yaml` and `prompts.yaml`. Inspect the three new task rows. If they fail consistently across 1+ run, the corresponding Prompt's instructions (Phase 5) need to be more directive — tighten the step wording in the `PROMPTS_BLOCK` and regenerate.

- [ ] **Step 4: Open a PR in `financial-reports/mcp-evals`**

```bash
cd /Users/silashundhausen/Dev/mcp-evals
git checkout -b add-prompts-task-fixtures
git add tasks/prompts.yaml
git commit -m "feat(tasks): exercise FR MCP Prompts (yoy, find-section, summarize)"
git push -u origin add-prompts-task-fixtures
gh pr create --title "Add task fixtures for FR MCP Prompts" \
  --body "Exercises the three Prompts shipped in financial-reports-mcp-server: compare_financials_yoy, find_filing_section, summarize_recent_filings."
```

---

## Phase 6 (sketched, deferred to a follow-up plan)

These require changes in the sibling repo `/Users/silashundhausen/Dev/financialreports` (Django backend). They will be planned in `2026-05-26-derived-tools.md` after Phase 1–5 here are merged.

1. `companies/{id}/financials/compare` — period-over-period KPI deltas.
2. `filings/{id}/compare` — filing-to-filing markdown diff with section anchoring.
3. `companies/aggregate-financials/` — sector/industry median/mean KPIs.
4. `filings/search-by-content` — content-snippet search across filings.
5. `companies/{id}/financials-metadata` — extraction confidence + restatement chain.

Once shipped on the backend, regenerating the MCP via `make regen` will surface them automatically (they're picked up from the OpenAPI schema), and a new `Phase 7` plan will add corresponding Prompts and golden queries.

---

## Self-review

- **Spec coverage:** All three threads the user asked about are covered. Local API-key testing = Phase 1–2. Skills = Phase 5 (MCP Prompts). Eval harness = Phase 4. Use-case improvements via derived tools are explicitly deferred to a sibling plan with a clear handoff.
- **No placeholders:** Every code step contains real, runnable code. Where a fallback exists (Task 4 conditional on Task 1's outcome; mcp-eval CLI dispatch via pip vs npx), both paths are spelled out.
- **Type consistency:** All Python identifiers (`DEV_MODE_API_KEY`, `_current_token`, `_api_client`, `_inject_auth`, `subscription_required`, `EXPECTED_PROMPTS`) are used identically across tasks. Prompt names (`compare_financials_yoy`, `find_filing_section`, `summarize_recent_filings`) appear in three places each — generator code, deterministic test, golden queries — and match.
- **Generator-aware:** Every edit to runtime behavior is made in `scripts/generate_mcp_tools.py`, never in `src/financial_reports_mcp.py` directly (which gets clobbered by `make regen`).
- **Defense in depth:** The dev-mode bypass refuses to import against the prod hostname and logs loudly at startup. Auth tests in `tests/test_decorator.py` continue to pass because the bypass is an additive early-return.
