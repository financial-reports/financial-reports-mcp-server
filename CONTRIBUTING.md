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
- ❌ **Code-style-only changes** — please run `black`/`ruff` locally before submitting; PRs that only reformat existing code generally aren't merged
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

- **Black** for formatting (`black src tests scripts`)
- **isort** for imports (`isort src tests scripts`)
- **Ruff** for linting (`ruff check src tests scripts`)
- **Type hints required** on all new function signatures (PEP 484)
- **Match existing patterns** in adjacent code over introducing new ones — consistency beats personal preference

## License

By submitting a contribution, you agree that your code will be released under the [MIT License](LICENSE). You retain copyright to your contribution.

## Questions

For development questions: open a GitHub issue.
For security issues: see [SECURITY.md](SECURITY.md) — don't open a public issue.
For questions about the FinancialReports API itself: https://financialreports.eu/contact/.
