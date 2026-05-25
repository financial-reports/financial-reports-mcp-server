"""Measure the size of the tools/list payload the MCP server returns.

Token-bloat is the most common MCP anti-pattern (10k-50k tokens just for
schemas eats client context before the user types anything). This script
gives us a baseline before adding any new tools or prompts.

Usage:
    ./venv/bin/python scripts/audit_token_budget.py > docs/token-budget.md

Implementation note: the generated `src.financial_reports_mcp` module
instantiates `AWSCognitoProvider` at import time, which performs a live
OIDC-discovery HTTP call. We intercept that single request with respx so
the audit runs offline (same pattern used by tests/conftest.py).
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
# Values mirror tests/conftest.py so the respx intercepts line up.
_AUDIT_POOL_ID = "eu-central-1_AUDITPOOL"
_AUDIT_REGION = "eu-central-1"
_AUDIT_ISSUER = (
    f"https://cognito-idp.{_AUDIT_REGION}.amazonaws.com/{_AUDIT_POOL_ID}"
)

os.environ.setdefault("COGNITO_USER_POOL_ID", _AUDIT_POOL_ID)
os.environ.setdefault("COGNITO_CLIENT_ID", "audit_client")
os.environ.setdefault("COGNITO_CLIENT_SECRET", "audit_secret")
os.environ.setdefault("COGNITO_REGION", _AUDIT_REGION)
os.environ.setdefault("MCP_BASE_URL", "http://localhost:8000")
os.environ.setdefault("API_BASE_URL", "http://localhost:8001")


_OIDC_DOCUMENT = {
    "issuer": _AUDIT_ISSUER,
    "authorization_endpoint": f"{_AUDIT_ISSUER}/oauth2/authorize",
    "token_endpoint": f"{_AUDIT_ISSUER}/oauth2/token",
    "userinfo_endpoint": f"{_AUDIT_ISSUER}/oauth2/userInfo",
    "jwks_uri": f"{_AUDIT_ISSUER}/.well-known/jwks.json",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
    "scopes_supported": ["openid", "email", "profile"],
    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
}


def _approx_tokens(s: str) -> int:
    """Rough char/token ratio for English JSON. Real tokenizer would be
    tiktoken — kept dependency-free for CI."""
    return max(1, len(s) // 4)


async def main() -> None:
    import httpx
    import respx

    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        router.get(
            f"{_AUDIT_ISSUER}/.well-known/openid-configuration"
        ).mock(return_value=httpx.Response(200, json=_OIDC_DOCUMENT))
        router.get(f"{_AUDIT_ISSUER}/.well-known/jwks.json").mock(
            return_value=httpx.Response(200, json={"keys": []})
        )

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
        schema = json.dumps(
            getattr(tool, "parameters", {}) or {}, separators=(",", ":")
        )
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
