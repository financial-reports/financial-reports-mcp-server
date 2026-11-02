"""#174 — `ALLOWED_CLIENT_REDIRECT_URI_PATTERNS` is a SECURITY control, and it had no test.

We run FastMCP's `OAuthProxy` (pinned `fastmcp==2.14.7`) with
`require_authorization_consent=False`, deliberately: Claude/OpenAI collect their
own connect-consent and our downstream login is the identity gate. The code says
so at the construction site, and names what compensates:

    ALLOWED_CLIENT_REDIRECT_URI_PATTERNS is the confused-deputy control.

That matters because `OAuthProxy._handle_idp_callback` does **not** verify that the
browser presenting `state`+`code` is the one that consented — the published
high-severity advisory, fixed in `fastmcp >= 3.2.0`, which is a MAJOR upgrade this
repo has not taken (`requirements.txt`: *"the auth module is unstable across minor
versions ... 3.x exists — do not move without an audit"*).

⇒ So the attack needs ONE thing we still control: a redirect_uri the attacker can
receive the authorization code at. Dynamic client registration is on, so an
attacker can register a client freely — the allowlist is what stops them naming
their own callback. **It is the whole mitigation, and before this file the only
mention of it under `tests/` was a sentence inside a docstring.** A single
permissive entry added for a new integration would silently un-mitigate a CVE,
with CI green.

⚠ This test pins POLICY, not just shape. Structure alone is not enough: an exact
host with no wildcard, like `https://attacker.example/cb`, is structurally tidy and
is precisely the attack. So the trusted registrable domains are enumerated here on
purpose — onboarding a new client must edit this set, which forces the decision to
be explicit and reviewed rather than appended to a list nobody guards.
"""
from __future__ import annotations

import re

import pytest

# Registrable domains whose hosts may receive an authorization code. Adding one is
# a security decision: it means "we accept that anyone who can serve content on
# this domain can receive our users' auth codes."
TRUSTED_REGISTRABLE_DOMAINS = frozenset({
    "claude.ai", "claude.com", "anthropic.com",   # Anthropic
    "chatgpt.com", "openai.com",                  # OpenAI
    "cursor.sh", "cursor.com",                    # Cursor
})

# Loopback resolves on the VICTIM's machine, so a code sent there never reaches a
# remote attacker. Plaintext http is acceptable for exactly this reason and no other.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})

_PATTERN_RE = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?P<host>[^/]*)(?P<path>/.*)?$")


def classify(pattern: str) -> str:
    """``'safe:<reason>'`` or ``'UNSAFE:<reason>'``. The whole point of this file."""
    m = _PATTERN_RE.match(pattern)
    if not m:
        return f"UNSAFE:unparseable, so its reach is unknown: {pattern!r}"
    scheme, host = m.group("scheme"), m.group("host")

    if scheme not in ("http", "https"):
        # A custom scheme dispatches to a locally registered handler. Claiming it
        # requires code already running on the victim's machine, which is a
        # strictly larger compromise than this control defends against.
        return f"safe:custom scheme {scheme!r} needs a local handler"

    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"

    if hostname in LOOPBACK_HOSTS:
        if scheme == "http":
            return "safe:loopback, unreachable from a remote attacker"
        return "safe:loopback"

    if scheme == "http":
        return f"UNSAFE:plaintext http to non-loopback host {hostname!r}"

    if hostname.startswith("*."):
        base = hostname[2:]
        if base in TRUSTED_REGISTRABLE_DOMAINS:
            return f"safe:wildcard subdomain of trusted {base!r}"
        return (
            f"UNSAFE:wildcard subdomain of UNTRUSTED {base!r} — any host under it "
            "could receive an auth code"
        )

    if "*" in hostname:
        return (
            f"UNSAFE:wildcard spans the registrable domain in {hostname!r} — this "
            "matches hosts nobody has vetted"
        )

    if hostname in TRUSTED_REGISTRABLE_DOMAINS:
        return f"safe:exact trusted host {hostname!r}"
    if any(hostname.endswith("." + d) for d in TRUSTED_REGISTRABLE_DOMAINS):
        return f"safe:exact host under trusted {hostname!r}"

    return f"UNSAFE:exact but UNTRUSTED host {hostname!r}"


def test_every_shipped_pattern_is_safe(mcp_module) -> None:
    """The assertion that actually guards the CVE."""
    patterns = mcp_module.ALLOWED_CLIENT_REDIRECT_URI_PATTERNS
    assert patterns, "the allowlist is empty — the confused-deputy control is GONE"

    verdicts = {p: classify(p) for p in patterns}
    unsafe = {p: v for p, v in verdicts.items() if v.startswith("UNSAFE")}
    assert not unsafe, (
        "ALLOWED_CLIENT_REDIRECT_URI_PATTERNS is the ONLY control mitigating the "
        "FastMCP OAuthProxy confused-deputy advisory (high; fixed in fastmcp>=3.2.0, "
        "we pin 2.14.7) while require_authorization_consent=False. A permissive entry "
        "here lets an attacker who registered their own client receive a victim's "
        "authorization code.\n"
        + "\n".join(f"  {p!r} -> {v}" for p, v in unsafe.items())
        + "\n\nIf a new client is legitimate, add its registrable domain to "
        "TRUSTED_REGISTRABLE_DOMAINS in this file — deliberately, so the decision "
        "is reviewed rather than appended."
    )


@pytest.mark.parametrize("pattern,why", [
    ("https://*", "wildcard host"),
    ("https://*/*", "wildcard host with path"),
    ("https://*.com/*", "wildcard at the registrable-domain level"),
    ("https://attacker.example/cb", "exact but untrusted — structurally tidy, still the attack"),
    ("https://*.attacker.example/*", "wildcard under an untrusted domain"),
    ("http://evil.example/cb", "plaintext to a remote host"),
    ("https://claude.ai.attacker.example/cb", "trusted name as a PREFIX of an untrusted host"),
    ("not a url", "unparseable"),
])
def test_the_classifier_REJECTS_the_dangerous_shapes(pattern, why) -> None:
    """⭐ The positive control, and the reason this file is not self-congratulatory.

    A test that only checks the current list passes just as well with a classifier
    that returns "safe" for everything. These cases prove it can say no — including
    the suffix-confusion case, where a trusted name appears as a prefix of a host
    the attacker owns."""
    verdict = classify(pattern)
    assert verdict.startswith("UNSAFE"), f"{pattern!r} ({why}) was accepted: {verdict}"


@pytest.mark.parametrize("pattern", [
    "https://claude.ai/api/mcp/auth_callback",
    "https://*.claude.ai/*",
    "cursor://*",
    "http://localhost:*",
    "http://[::1]:*",
])
def test_the_classifier_ACCEPTS_the_shapes_we_actually_ship(pattern) -> None:
    """The other control. A classifier that rejected everything would pass the test
    above and make the suite unmaintainable on the first legitimate addition."""
    verdict = classify(pattern)
    assert verdict.startswith("safe"), f"{pattern!r} was rejected: {verdict}"


def test_consent_is_off_so_this_control_is_LOAD_BEARING(mcp_module) -> None:
    """Ties the two together, so the next reader cannot miss why this file exists.

    If FastMCP's consent screen were ever turned on, or the pin moved to >=3.2.0,
    the allowlist would stop being the sole mitigation and this file's framing would
    need revisiting. Until then it is, and that is checkable rather than asserted."""
    import pathlib
    gen = pathlib.Path(__file__).parent.parent / "scripts" / "generate_mcp_tools.py"
    source = gen.read_text(encoding="utf-8")
    assert "require_authorization_consent=False" in source, (
        "consent appears to be ON now — if so, re-read this file's docstring: the "
        "allowlist may no longer be the sole confused-deputy control"
    )
    reqs = (pathlib.Path(__file__).parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "fastmcp==2.14.7" in reqs, (
        "the fastmcp pin moved — if it is now >=3.2.0 the advisory is fixed upstream "
        "and this control is defence-in-depth rather than the only mitigation"
    )
