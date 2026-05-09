# Security Policy

## Reporting a vulnerability

**Please don't open a public GitHub issue for security reports.**

Email: **security@financialreports.eu**

If you don't get an acknowledgement within **3 business days**, follow up via the contact form at https://financialreports.eu/contact/ noting that you sent a security report.

### What to include

- A description of the vulnerability and its potential impact
- Steps to reproduce (HTTP requests, sample payloads, or a minimal proof-of-concept)
- Whether the issue is in the MCP server itself, the upstream FinancialReports API, or the OAuth flow
- Your proposed fix, if you have one
- Whether you'd like to be credited in the public disclosure (and how)

### What to expect

| Phase | Timeline |
|---|---|
| Acknowledgement | within 3 business days |
| Initial triage and severity assessment | within 7 days |
| Fix development | varies by severity (critical: < 7 days, high: < 30 days) |
| Public disclosure (if patched) | coordinated with reporter |

### Scope

| In scope | Out of scope |
|---|---|
| This MCP server (`mcp.financialfilings.com` and the source in this repo) | The upstream API at `api.financialreports.eu` — report those to security@financialreports.eu noting it's an API issue |
| OAuth flow (Cognito proxy, PKCE, DCR) | DDoS or volumetric attacks against the public hosted server |
| Tool call handling, input validation | Issues in dependencies (FastMCP, FastAPI, Cognito, etc.) — please report to those projects upstream |
| OAuth-state persistence (DiskStore / Redis) | Vulnerabilities in MCP clients (Claude.ai, Cursor, etc.) — report to those vendors |
| Server-side icon proxy / asset routes | Social engineering, physical security |

### Safe-harbor

Good-faith security research that follows this policy will not result in legal action. We won't pursue claims under DMCA, CFAA, or equivalent legislation against researchers who:

- Make a good-faith effort to avoid privacy violations, service degradation, or destruction of data
- Stop testing once a vulnerability is identified and report it to us
- Don't access user data beyond the minimum necessary to demonstrate the issue
- Give us reasonable time to respond and patch before public disclosure

---

## Supported versions

This is a single-version production server. Security fixes are applied to `main` and deployed continuously. There are no maintained release branches.

---

## Server-side security guarantees

For reference when reporting issues, the server's security posture:

- **No persisted user data**: bearer tokens are proxied per-request to the upstream API; conversation content and tool outputs are never logged or cached server-side
- **HTTPS-only**: HTTP requests redirect to HTTPS at the edge
- **CSP enforced** on all HTML responses: `default-src 'none'`, only same-origin assets allowed
- **Origin validation**: requests from unrecognized origins are rejected with HTTP 403
- **OAuth 2.0**: PKCE S256 enforced, dynamic client registration per RFC 7591
- **Cognito-managed authentication**: no custom password handling
- **No custom crypto**: all cryptographic operations rely on Python standard library + AWS SDKs

---

## What we explicitly do NOT cover

- Security of MCP clients connecting to our server (Claude.ai, Claude Code, Cursor, etc.) — those are the vendors' responsibility
- Security of the underlying AWS Cognito service — see [AWS shared-responsibility model](https://aws.amazon.com/compliance/shared-responsibility-model/)
- Security of self-hosted forks — you are responsible for your own deployment

---

## Hall of fame

Reporters who have responsibly disclosed vulnerabilities will be credited here (with permission).

*No reports yet.*
