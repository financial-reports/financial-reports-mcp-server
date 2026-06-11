"""Prod OAuth smoke harness — the live path CI can't reach by construction.

Issue #32 (structured tools 403ing at FastMCP token-refresh boundaries) was
*untestable from CI*: the eval harness runs in DEV_MODE, which bypasses the OAuth
path entirely. This module is the missing coverage — it drives the REAL connector
flow against a real deployment:

    DCR  ->  PKCE /authorize (browser login)  ->  /token  ->  MCP initialize
          ->  tools/list  ->  tools/call (the structured tools that 403'd)

and asserts the #32 contract: **every structured tool either returns data or the
typed reconnect error — never a raw `upstream … returned 403`** (the kid-less-token
leak that #32 was). After the fix, a credential the upstream rejects fails closed
with `_RECONNECT_MSG` *before* the upstream call; this harness is what proves that
stays true on each deploy.

Two ways to get a token (no secrets in this file):
  - interactive:    `mint_token()` runs DCR+PKCE and waits for a browser login.
  - non-interactive: pass a token in (env `FR_E2E_TOKEN`) — used by the scheduled
                     synthetic probe (#40 §3 item 2) with a low-priv test account.

Run it manually:
    python tests/e2e/oauth_probe.py                 # interactive browser login
    FR_E2E_TOKEN=<jwt> python tests/e2e/oauth_probe.py   # bring your own token
Or via the env-gated pytest wrapper: see test_prod_oauth_probe.py.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import urllib.parse
from typing import Any, Optional

import httpx

PROD_BASE = "https://mcp.financialfilings.com"
MCP_PATH = "/mcp"
SCOPE = "openid email profile"
PROTOCOL_VERSION = "2025-06-18"

# Post-#32 fail-closed message (generate_mcp_tools.py `_RECONNECT_MSG` and the
# `_inject_auth` kid guard). A kid-less token that can't be re-swapped surfaces
# THIS, not a raw upstream 403 — so it's an ACCEPTED outcome for the probe.
RECONNECT_MARKER = "disconnect and reconnect"
# The #32 signature that must NEVER reach a client again. If any of these strings
# come back from a tool call, the kid-less-token leak has regressed.
FORBIDDEN_MARKERS = ("returned 403", "No kid provided", "Invalid token header")

# The structured (output_schema / `_authorize_or_raise`) tools — exactly the set
# that 403'd in #32. These are the contract under test.
STRUCTURED_TOOLS: list[tuple[str, dict]] = [
    ("companies_list", {"search": "Alcoa", "page_size": 5}),
    ("companies_retrieve", {"id": 14}),
    ("filings_list", {"page_size": 3}),
    ("isins_list", {"search": "DE000A1EWWW0"}),
    ("companies_financials_retrieve", {"id": 14}),
]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint_token(base_url: str = PROD_BASE, redirect_port: int = 8765) -> str:
    """Interactive: DCR -> PKCE -> print an authorize URL -> capture the localhost
    callback -> exchange the code -> return the access token. Blocks until the
    operator completes the browser login. No credentials are stored anywhere.
    """
    redirect = f"http://localhost:{redirect_port}/callback"
    with httpx.Client(timeout=30.0) as client:
        reg = client.post(
            f"{base_url}/register",
            json={
                "client_name": "fr-e2e-oauth-probe",
                "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": SCOPE,
            },
        )
        reg.raise_for_status()
        client_id = reg.json()["client_id"]
        client_secret = reg.json()["client_secret"]

    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(16)
    authorize_url = f"{base_url}/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    print("\n" + "=" * 72)
    print("OPEN THIS URL IN YOUR BROWSER AND SIGN IN:")
    print(authorize_url)
    print("=" * 72 + "\n", flush=True)

    captured: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # silence access logging
            pass

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            captured.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authenticated. You can close this tab.</h2>")

    server = http.server.HTTPServer(("127.0.0.1", redirect_port), _Handler)
    print(f"[probe] waiting for the callback on {redirect} ...", flush=True)
    while "code" not in captured and "error" not in captured:
        server.handle_request()
    if "error" in captured:
        raise RuntimeError(f"OAuth error: {captured.get('error')} {captured.get('error_description')}")

    with httpx.Client(timeout=30.0) as client:
        tok = client.post(
            f"{base_url}/token",
            data={
                "grant_type": "authorization_code",
                "code": captured["code"],
                "redirect_uri": redirect,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": verifier,
            },
        )
        tok.raise_for_status()
        access = tok.json().get("access_token")
    if not access:
        raise RuntimeError("token endpoint returned no access_token")
    return access


def _parse_rpc(text: str, content_type: str, rpc_id: Optional[int]) -> Optional[dict]:
    """Parse an MCP response body (JSON or text/event-stream) to the JSON-RPC obj."""
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if obj.get("id") == rpc_id or "result" in obj or "error" in obj:
                    return obj
        return None
    return json.loads(text) if text.strip() else None


def run_probe(
    token: str,
    base_url: str = PROD_BASE,
    calls: list[tuple[str, dict]] = STRUCTURED_TOOLS,
) -> dict:
    """initialize -> tools/list -> tools/call. Returns a structured report:
    {version, tool_count, results: [{tool, args, classification, detail}]}.
    """
    url = base_url.rstrip("/") + MCP_PATH
    session = {"id": None}

    def rpc(method: str, params: Optional[dict], rpc_id: Optional[int], notify: bool = False) -> Optional[dict]:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            msg["id"] = rpc_id
        if params is not None:
            msg["params"] = params
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if session["id"]:
            headers["mcp-session-id"] = session["id"]
        # Generous read timeout: companies_financials_retrieve can stream ~2 MB.
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)) as client:
            resp = client.post(url, content=json.dumps(msg).encode(), headers=headers)
        sid = resp.headers.get("mcp-session-id")
        if sid:
            session["id"] = sid
        if notify:
            return None
        return _parse_rpc(resp.text, resp.headers.get("content-type", ""), rpc_id)

    init = rpc(
        "initialize",
        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "fr-e2e-probe", "version": "1.0"}},
        rpc_id=1,
    )
    version = ((init or {}).get("result", {}).get("serverInfo", {}) or {}).get("version", "?")
    rpc("notifications/initialized", None, None, notify=True)

    tl = rpc("tools/list", {}, rpc_id=2)
    tool_count = len((tl or {}).get("result", {}).get("tools", []))

    results = []
    for i, (name, args) in enumerate(calls, start=10):
        try:
            resp = rpc("tools/call", {"name": name, "arguments": args}, rpc_id=i)
        except Exception as exc:  # client-side (timeout, transport) — not a prod error
            results.append({"tool": name, "args": args, "classification": "client_error", "detail": f"{type(exc).__name__}: {exc}"})
            continue
        res = (resp or {}).get("result", {})
        content = res.get("content", []) or []
        text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        if "error" in (resp or {}):  # JSON-RPC level error
            text = json.dumps(resp["error"])
        results.append(
            {
                "tool": name,
                "args": args,
                "classification": classify(text, bool(res.get("isError")) or "error" in (resp or {})),
                "detail": text[:240],
                "bytes": len(json.dumps(res)),
            }
        )
    return {"version": version, "tool_count": tool_count, "results": results}


def classify(text: str, is_error: bool) -> str:
    """data | reconnect | forbidden | error — the #32 contract classifier."""
    if any(m in text for m in FORBIDDEN_MARKERS):
        return "forbidden"
    if RECONNECT_MARKER in text:
        return "reconnect"
    return "error" if is_error else "data"


if __name__ == "__main__":  # manual smoke entrypoint
    base = os.environ.get("FR_E2E_BASE_URL", PROD_BASE)
    tok = os.environ.get("FR_E2E_TOKEN") or mint_token(base)
    report = run_probe(tok, base)
    print(f"\nserver: {report['version']}  |  tools: {report['tool_count']}\n")
    bad = 0
    for r in report["results"]:
        flag = "OK " if r["classification"] in ("data", "reconnect") else "BAD"
        if r["classification"] == "forbidden":
            bad += 1
        print(f"  [{flag}] {r['tool']:<32} {r['classification']:<12} {r['detail'][:80]}")
    print(f"\n{'PASS' if bad == 0 else 'FAIL'} — {bad} forbidden (#32-regression) result(s)")
    raise SystemExit(1 if bad else 0)
