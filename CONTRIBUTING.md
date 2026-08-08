# Contributing

Thanks for your interest. This server is the official MCP for the FinancialReports API, but the source is MIT-licensed and we welcome contributions.

## What we accept

- ✅ **Bug fixes** — anything from typos to OAuth-flow edge cases
- ✅ **Tests** — additional unit, integration, or end-to-end tests
- ✅ **Documentation** — README, `docs/SELF-HOSTING.md`, this file, the skill, code comments
- ✅ **Generator improvements** — `scripts/generate_mcp_tools.py` is hand-written and the right place for tool description tweaks, output-schema additions, or new annotation logic
- ✅ **CI improvements** — faster builds, additional checks, better error reporting
- ✅ **Skill content** — refinements to `skills/financial-filings-research/`

## What we won't merge

- ❌ **Hand-edits to `src/financial_reports_mcp.py`** — it's auto-generated. Edits there get overwritten on every build. Update the generator instead.
- ❌ **Speculative features** — new tools that aren't backed by an actual FR API endpoint, abstractions for hypothetical future use cases
- ❌ **Drive-by dependency bumps** — unless they fix a CVE or a real bug
- ❌ **Code-style-only changes** — please run the CI-gated `ruff`/`isort` commands from [Code style](#code-style) locally before submitting; PRs that only reformat existing code generally aren't merged
- ❌ **Branding changes** — colors, copy, icons. The hosted server is FinancialReports-owned; adapt your fork instead

## Development workflow

```bash
# Fork, then clone your fork
git clone https://github.com/YOUR_USERNAME/financial-reports-mcp-server.git
cd financial-reports-mcp-server

# Set up a venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# Make your changes — usually in:
#   scripts/generate_mcp_tools.py   (generator + landing HTML)
#   tests/                           (unit + integration tests)
#   skills/                          (companion Claude Skill)

# Regenerate the source module if you touched the generator
python scripts/generate_mcp_tools.py

# Run the test suite
pytest

# (Optional) Run the end-to-end test that brings up Redis via Docker Compose
make e2e

# Commit, push, open PR
```

## Testing requirements

- **Every PR must keep the test suite green.** CI runs `pytest` on every push.
- **New behavior should come with tests.** Look at `tests/test_app_routes.py` for the integration-test pattern (TestClient + respx for outbound mocks).
- **Regression tests for bug fixes are mandatory.** If you fix a bug, add a test that fails on the old code and passes on yours.

## Pull request process

1. **Open an issue first** for non-trivial changes. A 5-line fix doesn't need one; a new feature does.
2. **Branch off `main`**, name it descriptively (`fix/oauth-redirect-loop`, `feat/add-tool-foo`, `docs/clarify-self-hosting`).
3. **Keep PRs focused.** One logical change per PR. Multiple unrelated changes will be asked to split.
4. **Write a real PR description** — what changed, why, how you tested it. Reviewers shouldn't have to read the diff to understand the intent.
5. **CI must pass before review.** If CI is red, we won't look until it's green.
6. **Be patient.** Maintainer responsiveness varies; expect 3–7 business days for a first response.

## Commit messages

We follow conventional commits informally:

```
feat: add new endpoint for X
fix: handle Y edge case in OAuth refresh
docs: clarify self-hosting Cognito setup
test: add regression for Z
refactor: extract subscription cache to its own module
chore: bump foo to 1.2.3
ci: add coverage reporting
```

The body should explain **why** the change is needed, not just **what** changed. The diff already shows what changed.

## Code style

**Gated in CI** — the `lint` job in `.github/workflows/ci.yml` runs exactly these, and a PR stays red until they pass:

```bash
ruff check src tests scripts --select E4,E7,E9,F --exclude src/financial_reports_mcp.py
isort --check-only --profile black src tests scripts
```

Both tools are pinned **exactly** in `requirements-test.txt` (`ruff==0.16.2`, `isort==8.0.1`), and `pyproject.toml` carries the same `select` and `profile`, so a local run returns the same verdict as CI. Drop `--check-only` to have isort fix your imports in place.

Two things worth knowing about that command line:

- **The `--select` is pinned as deliberately as the version.** Ruff's default rule set expands between releases; under 0.16.2's defaults this repo reports 48 findings (mostly `UP045` annotation modernization and `BLE001` blind-except). Widening the selection is welcome, but as its own PR — several of those blind-excepts are intentional fail-closed handlers in the auth path and need individual review, not a bulk fix.
- **`src/financial_reports_mcp.py` is excluded.** It's generated and git-ignored, but it exists on disk after `make regen`, and linting ~218 KB of emitted code is noise: the only real fix would be editing template strings in `scripts/generate_mcp_tools.py`.

**Not gated yet:**

- **Black** (`black src tests scripts`) — the repo is not black-clean at black's default 88 columns: 27 of 33 files would be reformatted, about 866 diff lines. That reformat lands as its own whitespace-only PR, reviewable at a glance, and gets gated here afterwards. Until then, please **don't** run `black` over files your change doesn't otherwise touch — it buries the diff reviewers need to read.

Also:

- **Type hints required** on all new function signatures (PEP 484)
- **Match existing patterns** in adjacent code over introducing new ones — consistency beats personal preference

## License

By submitting a contribution, you agree that your code will be released under the [MIT License](LICENSE). You retain copyright to your contribution.

## Questions

For development questions: open a GitHub issue.
For security issues: see [SECURITY.md](SECURITY.md) — don't open a public issue.
For questions about the FinancialReports API itself: https://financialreports.eu/contact/.
