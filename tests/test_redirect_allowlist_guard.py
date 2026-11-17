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

from urllib.parse import urlsplit

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
# remote attacker. Plaintext http is acceptable for exactly this reason and no
# other. Note `::1` and not `[::1]`: urlsplit strips the brackets.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Custom schemes that dispatch to a locally registered APP handler, enumerated on
# purpose. ⛔ The first version accepted EVERY non-http scheme on the grounds that
# "a custom scheme needs a local handler" — true of `cursor://`, false of network
# protocols: `ftp://attacker.example/cb` and `wss://attacker.example/cb` both
# classified as safe (SPECHT S2, 2/3). Adding a scheme here is a review decision,
# the same as adding a trusted domain.
ALLOWED_CUSTOM_SCHEMES = frozenset({"cursor"})

# ⛔ PARSER DIFFERENTIAL. The authority (between `//` and the next `/`) may contain
# ONLY these characters. Not because urlsplit mis-parses the rest, but because the
# BROWSER is what follows the redirect, and it does not parse the way Python does:
#
#     https://evil.example\@claude.ai/cb
#         Python urlsplit  -> hostname 'claude.ai'      (classified SAFE)
#         browser (WHATWG) -> hostname 'evil.example'   (where the code GOES)
#
# Round 1 replaced a hand-rolled parser with urlsplit as "the validated parser" —
# validated against the wrong spec. Picking a better parser does not close this:
# whichever one we pick, the decision is made by a different one. Restricting
# inputs to the subset where all parsers AGREE does. Every shipped pattern fits;
# userinfo (`@`), backslash, percent-encoding and whitespace all fall outside it.
_AUTHORITY_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-*:[]")


def classify(pattern: str) -> str:
    """``'safe:<reason>'`` or ``'UNSAFE:<reason>'``. The whole point of this file.

    ⛔ THE FIRST VERSION HAND-ROLLED THIS WITH A REGEX AND SPECHT BROKE IT TWICE
    (S2 + S3, 3/3 passes), which is the lesson rather than the bug:

        https://claude.ai:443@evil.example/cb  -> "safe: trusted 'claude.ai'"
        https://attacker.example?next=.claude.ai -> "safe: under trusted"

    Userinfo and a query string each defeated it, because `[^/]*` for the host
    plus `rsplit(':', 1)` is not a URL parser. **Eight adversarial shapes were
    already controlled and both misses were shapes I had not thought of** — so the
    remedy is NOT more cases, it is to stop hand-parsing and use a parser that was
    validated by someone else. `PROCESS.md` Phase 3.5 §9: the hand-written
    component is an unvalidated instrument until it is measured like a model.

    `urlsplit().hostname` is that parser for the shapes we ship — measured, not
    assumed. ⚠ NOT for every shape: SPECHT round 3 found one where it disagrees
    with the browser (see _AUTHORITY_ALPHABET), so it is only trusted AFTER the
    authority has been restricted to characters all parsers read the same way: it strips userinfo
    (`...@evil.example` -> `evil.example`), excludes query and fragment,
    lowercases (so `CLAUDE.AI.attacker.example` cannot pass as trusted), strips
    IPv6 brackets (`[::1]:*` -> `::1`), and leaves `*` intact in the host so the
    wildcard entries still classify.

    ⚠ Never touch `.port` here: `localhost:*` is not a valid port and `.port`
    raises ValueError on it. `.hostname` is fine.
    """
    try:
        parts = urlsplit(pattern)
    except ValueError as exc:
        return f"UNSAFE:unparseable ({exc}), so its reach is unknown"

    scheme, hostname = parts.scheme, parts.hostname
    authority = parts.netloc.lower()
    bad = sorted(set(authority) - _AUTHORITY_ALPHABET)
    if bad:
        return (
            f"UNSAFE:authority {parts.netloc!r} contains {bad} — characters where "
            "Python's parser and the browser's can disagree about the host"
        )
    if not scheme:
        return "UNSAFE:no scheme — a protocol-relative target inherits the page's"
    if not hostname:
        return f"UNSAFE:no host in {pattern!r}, so its reach is unknown"

    if scheme not in ("http", "https"):
        if scheme in ALLOWED_CUSTOM_SCHEMES:
            # An app-registered scheme dispatches to a local handler. Claiming it
            # requires code already running on the victim's machine, a strictly
            # larger compromise than this control defends against.
            return f"safe:app scheme {scheme!r} needs a local handler"
        return (
            f"UNSAFE:scheme {scheme!r} is not an enumerated app scheme — it may be a "
            "network protocol that reaches a remote host"
        )

    # A single trailing dot is the DNS root and names the SAME host, so normalise
    # it rather than rejecting it — otherwise the guard is accidentally strict and
    # someone will "fix" it by loosening the comparison.
    host = hostname.rstrip(".") or hostname

    if host in LOOPBACK_HOSTS:
        return "safe:loopback, unreachable from a remote attacker"
    if scheme == "http":
        return f"UNSAFE:plaintext http to non-loopback host {host!r}"

    if host.startswith("*."):
        base = host[2:]
        if base in TRUSTED_REGISTRABLE_DOMAINS:
            return f"safe:wildcard subdomain of trusted {base!r}"
        return (
            f"UNSAFE:wildcard subdomain of UNTRUSTED {base!r} — any host under it "
            "could receive an auth code"
        )
    if "*" in host:
        return (
            f"UNSAFE:wildcard spans the registrable domain in {host!r} — this "
            "matches hosts nobody has vetted"
        )

    if host in TRUSTED_REGISTRABLE_DOMAINS:
        return f"safe:exact trusted host {host!r}"
    if any(host.endswith("." + d) for d in TRUSTED_REGISTRABLE_DOMAINS):
        return f"safe:exact host under trusted {host!r}"
    return f"UNSAFE:exact but UNTRUSTED host {host!r}"


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
    # ⛔ The two SPECHT found in the hand-rolled parser (S2 + S3, 3/3 passes).
    # Both were "safe" before. Kept FIRST in spirit: they are the reason this
    # classifier uses urlsplit at all.
    ("https://claude.ai:443@evil.example/cb", "USERINFO — trusted name before the @, attacker host after"),
    ("https://attacker.example?next=.claude.ai", "QUERY STRING carrying a trusted suffix"),
    # Implied by those two, and none of them occurred to me before the review.
    ("https://attacker.example#.claude.ai", "FRAGMENT carrying a trusted suffix"),
    ("https://CLAUDE.AI.attacker.example/cb", "UPPERCASE trusted prefix — case must not help"),
    (r"https://claude.ai\@evil.example/cb", "backslash userinfo separator"),
    ("//claude.ai/cb", "no scheme — a protocol-relative target inherits the page's"),
    ("https:///cb", "scheme but no host"),
    # ⛔ SPECHT round 2: network protocols were waved through as "custom schemes".
    ("ftp://attacker.example/cb", "FTP is a network protocol, not a local app handler"),
    ("wss://attacker.example/cb", "WebSocket to a remote host"),
    ("vscode://attacker.example/cb", "an app scheme we have NOT reviewed"),
    # ⛔ SPECHT round 3: Python reads 'claude.ai', the BROWSER reads 'evil.example'.
    # The backslash case above (claude.ai\@evil.example) is the REVERSE direction —
    # the one where the parsers disagree in our favour — so it never caught this.
    (r"https://evil.example\@claude.ai/cb", "PARSER DIFFERENTIAL: browser host is evil.example"),
    ("https://evil.example%2F@claude.ai/cb", "percent-encoded slash inside userinfo"),
    ("https://user@claude.ai/cb", "any userinfo at all — never legitimate in a redirect pattern"),
    ("https://claude.ai%2Eevil.example/cb", "percent-encoding in the host"),
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
    "http://127.0.0.1:*",
    "http://[::1]:*",          # urlsplit strips the brackets -> '::1'
    "https://claude.ai./cb",   # trailing dot is the DNS root: the SAME host
])
def test_the_classifier_ACCEPTS_the_shapes_we_actually_ship(pattern) -> None:
    """The other control. A classifier that rejected everything would pass the test
    above and make the suite unmaintainable on the first legitimate addition."""
    verdict = classify(pattern)
    assert verdict.startswith("safe"), f"{pattern!r} was rejected: {verdict}"


def _consent_args_in_generated_module() -> list:
    """``[(provider_call_name, value)]`` for every provider construction, by AST.

    ⛔ The first version asserted ``"require_authorization_consent=False" in
    source`` — and the comment this same PR added at the allowlist CONTAINS that
    exact string (generator line ~1016). So flipping BOTH real arguments to True
    left it green: a check satisfied by its own documentation (SPECHT S3, both
    phrasings). A mention is not an occurrence. Reading the call keywords from
    the AST of the GENERATED module cannot be satisfied by a comment, and it reads
    what actually ships rather than the template that produces it."""
    import ast
    import pathlib
    gen = pathlib.Path(__file__).parent.parent / "src" / "financial_reports_mcp.py"
    tree = ast.parse(gen.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name not in ("_LoggingOAuthProxy", "_LoggingAWSCognitoProvider"):
            continue
        val = next(
            (kw.value.value for kw in node.keywords
             if kw.arg == "require_authorization_consent" and isinstance(kw.value, ast.Constant)),
            "<absent or non-literal>",
        )
        found.append((name, val))
    return found


def test_consent_is_off_so_this_control_is_LOAD_BEARING(mcp_module) -> None:
    """Ties the two together, so the next reader cannot miss why this file exists.

    If FastMCP's consent screen is turned on, or the pin moves to >=3.2.0, the
    allowlist stops being the SOLE mitigation and this file's framing needs
    revisiting. Until then it is — and that is now checked on the real arguments,
    not on any text that happens to contain them."""
    calls = _consent_args_in_generated_module()
    assert len(calls) == 2, (
        f"expected exactly the two provider branches, found {calls} — a new branch "
        "needs its consent setting reviewed against this control"
    )
    assert all(v is False for _n, v in calls), (
        f"consent is no longer off on every branch: {calls}. If that is intended, the "
        "allowlist may no longer be the sole confused-deputy control — revisit this "
        "file's docstring before relaxing it"
    )
    import pathlib
    reqs = (pathlib.Path(__file__).parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "fastmcp==2.14.7" in reqs, (
        "the fastmcp pin moved — if it is now >=3.2.0 the advisory is fixed upstream "
        "and this control is defence-in-depth rather than the only mitigation"
    )
