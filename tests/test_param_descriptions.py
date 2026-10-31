"""Tool parameters carry the schema's descriptions (#132 item 3).

The generator emitted bare `type: str | None`, so the model saw no guidance on
the parameter itself — while the REST schema's `type`/`types` descriptions
already say "taxonomy codes, not regulator form names". 83 unknown-filing-type
400s in 30 days of prod traffic were models passing form names there.
"""
from __future__ import annotations

import pytest


def _generator():
    """The generator module. Some facts — like whether a parameter EARNED its
    wider cap — are generator-time state and simply are not present in the
    emitted module; asking the artifact for them is the wrong question."""
    import importlib
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    return importlib.import_module("generate_mcp_tools")


def _snapshot_desc(tool_name: str, param: str) -> str:
    """The snapshot's own description for a parameter, by tool."""
    import json
    import os

    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    for item in snap["paths"].values():
        for op in item.values():
            if not isinstance(op, dict):
                continue
            if op.get("operationId") != tool_name:
                continue
            for p in op.get("parameters", []) or []:
                if p.get("name") == param:
                    return " ".join((p.get("description") or "").split())
    return ""


def _input_schema(mcp_module, tool_name):
    tool = mcp_module.mcp._tool_manager._tools[tool_name]
    return tool.parameters


# ⚠ THESE STRINGS PIN *UPSTREAM'S* PROSE, NOT THIS GENERATOR'S BEHAVIOUR. A
# failure here means the REST schema reworded a description — re-read the new
# text and confirm the distinction below still survives, then update the string.
# It does NOT mean the generator stopped plumbing descriptions through; that is
# what `test_params_without_a_schema_description_get_none` and the non-empty
# assertion in the test body cover.
#
# The distinction being guarded, which is the thing that must survive any
# rewording: a model must be able to tell a FinancialFilings taxonomy code
# (`type`/`types`) from the source's own form name (`source_filing_type`).
# Re-pointed 2026-10-30 with the #154 snapshot refresh: upstream replaced the
# NEGATION ("taxonomy codes, not regulator form names") with a POSITIVE
# CROSS-REFERENCE ("for the source's own form name, use `source_filing_type`"),
# which is better for an LLM — a negation tells it what the field is not.
@pytest.mark.parametrize(
    "tool_name,param,must_contain",
    [
        ("filings_list", "types", "use `source_filing_type`"),
        ("filings_list", "type", "use `source_filing_type`"),
        ("filings_list", "source_filing_type", "exactly as the source publishes it"),
        ("companies_financials_retrieve", "line_items", "Unknown codes return"),
    ],
)
def test_param_description_reaches_the_input_schema(
    mcp_module, tool_name, param, must_contain
) -> None:
    props = _input_schema(mcp_module, tool_name)["properties"]
    assert param in props, sorted(props)
    described = props[param].get("description", "")
    # Plumbing first, prose second: a param that arrives with NO description is
    # the generator failing, and that is a different diagnosis from upstream
    # having reworded one. Asserting them separately keeps the two apart.
    assert described, f"{tool_name}.{param} reached the input schema with no description at all"
    assert must_contain in described, (
        f"{tool_name}.{param} no longer contains {must_contain!r}. If upstream reworded it, "
        f"confirm the code-vs-source-form distinction still survives, then update the string. "
        f"Current text: {described!r}"
    )


def test_params_without_a_schema_description_get_none(mcp_module) -> None:
    """No invented text: a param the schema leaves undescribed stays so."""
    import json
    import os

    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    op = snap["paths"]["/filings/"]["get"]
    undescribed = [
        p["name"] for p in op["parameters"] if p.get("in") == "query" and not p.get("description")
    ]
    props = _input_schema(mcp_module, "filings_list")["properties"]
    for name in undescribed:
        if name in props:
            assert "description" not in props[name], name


def test_only_allowlisted_params_are_described(mcp_module) -> None:
    """Token cost: every description is sent on every session. Emitting all of
    them measured +2,774 tokens on tools/list; only the allowlist is emitted."""
    allowed = mcp_module_allowlist()
    for name in ("filings_list", "companies_list", "companies_financials_retrieve"):
        for pname, prop in _input_schema(mcp_module, name)["properties"].items():
            if "description" in prop:
                assert pname in allowed, (name, pname)


def mcp_module_allowlist():
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_mcp_tools.py")
    spec = importlib.util.spec_from_file_location("_gen_for_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._DESCRIBED_PARAMS


def _generator():
    """The generator module. Whether a parameter EARNED a wider cap is
    generator-time state; the emitted module does not carry it, and asking the
    artifact for it is the wrong instrument — I made exactly that mistake in
    round 4 by emitting a test accessor into the generated module where the
    state it read did not exist."""
    import importlib
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    return importlib.import_module("generate_mcp_tools")


def _snapshot_param_desc(param: str) -> str:
    """The snapshot's own description for a parameter, by name."""
    import json
    import os

    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    for item in snap["paths"].values():
        for op in item.values():
            if not isinstance(op, dict):
                continue
            for p in op.get("parameters", []) or []:
                if p.get("name") == param and p.get("description"):
                    return " ".join(p["description"].split())
    return ""


def test_descriptions_are_capped(mcp_module) -> None:
    """320 by default, widened ONLY for a parameter carrying derived failure
    rules — those need room for the rules AND the instruction that tells a
    caller what to send.

    The widening was deleted in round 4 because three mutations against it
    survived. That was the wrong inference: surviving mutations showed it was
    UNTESTED, not unneeded. Round 5 found the case the tests could not see —
    `cursor` needs 326 chars for its rules plus its first-page instruction,
    against a 320 cap.

    So the widening must be EARNED, which is what the three mutations were
    missing and what this now pins: exceeding the base cap requires the
    parameter to actually carry derived rules. Without that clause, a cap that
    had simply been removed would pass."""
    gen = _generator()
    for name in ("filings_list", "companies_list", "companies_financials_retrieve"):
        for pname, prop in _input_schema(mcp_module, name)["properties"].items():
            desc = prop.get("description", "")
            assert len(desc) <= 3 * 320, (name, pname, len(desc))
            if len(desc) > 320:
                assert gen._operative_sentences(_snapshot_param_desc(pname)), (
                    f"{name}.{pname} exceeded the base cap with no derived rules "
                    "to justify it — the cap may simply have been removed"
                )


# --- SPECHT #170: a schema enum that is a MEMBER vocabulary, not a value one ---

def test_comma_separated_include_is_not_a_single_value_enum(mcp_module) -> None:
    """`include` on companies_financials_retrieve says "Comma-separated." in its own
    description and its enum lists the five MEMBERS, not the legal whole values.

    The #154 refresh is what made this wrong: before it, the enum held exactly one
    value (`revisions`), so a `Literal` was correct and "comma-separated" was moot.
    With five members a `Literal` rejects `include="revisions,preliminary"` — the
    documented usage — inside MCP validation, before the request can reach the API
    that would accept it. A client cannot work around a type that will not serialise."""
    props = _input_schema(mcp_module, "companies_financials_retrieve")["properties"]
    inc = props["include"]
    # Asserted on the SCHEMA, not on str() of it. The first version of this test
    # read `"enum" not in rendered or "anyOf" in rendered`, which is true for the
    # BROKEN shape too — the type is `anyOf: [{enum:[...]}, {null}]`, so the `or`
    # short-circuited and the test passed in the RED phase. A test that passes
    # before the fix is testing nothing.
    def _has_enum(node):
        if isinstance(node, dict):
            return "enum" in node or any(_has_enum(v) for v in node.values())
        if isinstance(node, list):
            return any(_has_enum(v) for v in node)
        return False
    assert not _has_enum(inc), (
        f"include is still a closed enum, so combinations cannot be expressed: {inc}"
    )


def test_unknown_include_members_are_still_rejected(mcp_module) -> None:
    """Widening the type must not stop validating. Each comma-separated member is
    checked against the vocabulary; an unknown one is a ToolInputError, not a 400
    round-trip and not silence."""
    assert hasattr(mcp_module, "_validate_csv_enum")
    allowed = ("as_reported", "preliminary", "revisions", "split_adjusted", "standalone_quarters")
    assert mcp_module._validate_csv_enum("revisions,preliminary", allowed, "include") == \
        "revisions,preliminary"
    assert mcp_module._validate_csv_enum(" revisions , preliminary ", allowed, "include") == \
        "revisions,preliminary"
    assert mcp_module._validate_csv_enum(None, allowed, "include") is None
    for bad in ("nonsense", "revisions,nonsense", "revisions,,preliminary"):
        try:
            mcp_module._validate_csv_enum(bad, allowed, "include")
        except mcp_module.ToolInputError as exc:
            assert "include" in str(exc)
        else:
            raise AssertionError(f"{bad!r} was accepted")


def test_the_new_cursor_param_carries_its_description(mcp_module) -> None:
    """`_DESCRIBED_PARAMS` is an ALLOWLIST, so a new upstream parameter arrives with
    its description silently discarded — the same denylist/allowlist asymmetry as
    `_PRUNED_EXCLUDE`, pointing the other way. `cursor` is unusable without its text:
    the first page needs an EMPTY `cursor=`, which no model will guess."""
    props = _input_schema(mcp_module, "filings_list")["properties"]
    assert "cursor" in props, sorted(props)
    desc = props["cursor"].get("description", "")
    assert desc, "cursor reached the schema with its description discarded"
    assert "empty" in desc.lower(), f"the first-page rule is missing: {desc!r}"


@pytest.mark.asyncio
async def test_the_generated_tool_actually_calls_the_validator(
    mcp_module, monkeypatch, fake_access_token, respx_router
) -> None:
    """The INTEGRATION half, and the one mutation testing demanded.

    `_validate_csv_enum` being correct says nothing about the generated tool
    body calling it, or using what it returns. Mutation S5 rewired the template
    to call it and throw the result away, and every other test here stayed
    green — the isolated-constant failure mode PROCESS.md was written for after
    PR #75.

    So this asserts both halves at the boundary: an unknown member never leaves
    the process, and a valid combination reaches the wire CANONICALISED, which
    is only true if the return value is the thing assigned to the query param."""
    import httpx

    from .conftest import TEST_API_BASE, TEST_CLIENT_ID

    at = fake_access_token(client_id=TEST_CLIENT_ID, token="real-access-token")
    monkeypatch.setattr(mcp_module, "get_access_token", lambda: at)

    seen = {}

    def _capture(request):
        seen["include"] = dict(request.url.params).get("include")
        return httpx.Response(200, json={"results": []})

    respx_router.get(f"{TEST_API_BASE}/companies/1/financials/").mock(side_effect=_capture)
    tool = mcp_module.mcp._tool_manager._tools["companies_financials_retrieve"]
    fn = getattr(tool, "fn", None) or getattr(tool, "function", None)

    # Valid combination, deliberately with whitespace the caller might type.
    await fn(id=1, include=" revisions , preliminary ")
    assert seen["include"] == "revisions,preliminary", (
        f"the validator's return value never reached the request: {seen['include']!r}"
    )

    # Unknown member: must not reach the wire at all. These generated tools
    # RAISE on bad input rather than returning a safe-error string — the
    # contract test_guidance_132 already pins for `page_size`. My first version
    # of this test expected a returned string, which is the hand-built tools'
    # contract, not this one's.
    seen.clear()
    with pytest.raises(Exception) as ei:
        await fn(id=1, include="revisions,nonsense")
    assert "nonsense" in str(ei.value) and "include" in str(ei.value)
    assert not seen, "an invalid include was sent upstream anyway"


# --- SPECHT #170 round 2: the 320-char cap eats the operative tail ----------

def test_every_include_member_is_discoverable(mcp_module) -> None:
    """Round 1 removed `include`'s enum because the enum was a VALUE vocabulary and
    the parameter is comma-separated. The enum was also the only way a client could
    DISCOVER the five members — and the description that replaced it is 1388 chars,
    so `_MAX_PARAM_DESCRIPTION` cuts it mid-`preliminary`: `as_reported`,
    `split_adjusted` and `standalone_quarters` became unreachable. A model asked for
    split-adjusted EPS cannot ask for it.

    The members are DERIVED from the schema enum, not hand-typed, so they cannot
    drift from upstream."""
    props = _input_schema(mcp_module, "companies_financials_retrieve")["properties"]
    desc = props["include"].get("description", "")
    for member in ("as_reported", "preliminary", "revisions", "split_adjusted",
                   "standalone_quarters"):
        assert member in desc, f"{member} is not discoverable: {desc!r}"


def test_primary_annual_report_keeps_its_400_condition(mcp_module) -> None:
    """The same cap, the same direction, a different parameter. This one's operative
    sentence — it 400s unless combined with one of eight other filters — is the LAST
    sentence of a 562-char description, so adding the param to `_DESCRIBED_PARAMS`
    alone would have truncated precisely the part that stops a failing call."""
    props = _input_schema(mcp_module, "filings_list")["properties"]
    assert "primary_annual_report" in props, sorted(props)
    desc = props["primary_annual_report"].get("description", "")
    assert desc, "description discarded by the _DESCRIBED_PARAMS allowlist"
    assert "400" in desc, f"the failure condition was truncated away: {desc!r}"
    assert "fiscal_year" in desc or "company" in desc, (
        f"the companion filters are not named: {desc!r}"
    )


def test_the_hand_written_lead_still_matches_upstream(mcp_module) -> None:
    """ANTI-ROT, and the reason a hand-written lead-in is acceptable at all.

    `include`'s lead is derived from the schema, so it cannot drift. The
    `primary_annual_report` lead is prose I wrote, which CAN drift from upstream
    silently — exactly the comment-rot class. So this asserts my lead's claim is
    still what the snapshot says: if upstream changes which filters satisfy the
    requirement, this fails instead of shipping a confident wrong instruction."""
    import json
    import os

    snap = json.load(
        open(os.path.join(os.path.dirname(__file__), "..", "scripts", "openapi.snapshot.json"))
    )
    op = snap["paths"]["/filings/"]["get"]
    upstream = " ".join(
        (next(p for p in op["parameters"] if p["name"] == "primary_annual_report")
         .get("description") or "").split()
    )
    assert "otherwise returns 400" in upstream, (
        "upstream no longer states the 400 condition — re-read it and update the lead"
    )
    for f in ("company", "company_isin", "lei", "countries", "source", "sources",
              "fiscal_year"):
        assert f in upstream, f"upstream dropped {f} from the satisfying filters"


# --- SPECHT #170 round 3: hand-picked leads lose a race they cannot win ----

def test_every_hard_failure_rule_survives_the_cap(mcp_module) -> None:
    """Round 2 front-loaded `include`'s member list and `primary_annual_report`'s
    400 condition BY HAND. Round 3 found the next two facts the cap was eating:
    `include`'s "Not served with `as_known_at`" (twice) and `cursor`'s "Adding
    `page`, or changing `ordering` mid-walk, returns 400 `invalid_cursor`".

    Measured before fixing: 5 operative sentences across 3 parameters, 0 of them
    inside the 320-char cap. Hand-picking caught 1 of 5 and would have been
    overtaken again next round — a fixed cap plus a human choosing what matters
    is a race the human loses, because upstream keeps writing.

    So they are DERIVED: any sentence stating a hard failure (4xx/503) or an
    incompatibility ("Not served with") is front-loaded mechanically. No
    judgement, nothing to keep in sync, and a new one is picked up for free."""
    checks = {
        ("companies_financials_retrieve", "include"): ["as_known_at"],
        ("filings_list", "cursor"): ["400", "ordering"],
        ("filings_list", "primary_annual_report"): ["400"],
    }
    for (tool, param), musts in checks.items():
        desc = _input_schema(mcp_module, tool)["properties"][param].get("description", "")
        for must in musts:
            assert must in desc, f"{tool}.{param} lost {must!r} to the cap: {desc!r}"


def test_the_derivation_is_a_rule_not_a_lookup_table(mcp_module) -> None:
    """The point of deriving rather than listing: a parameter nobody hand-curated
    still gets its failure rule. `cursor` has no entry anywhere — it is covered
    only because its text matches the rule."""
    assert not hasattr(mcp_module, "_PARAM_LEADS") or "cursor" not in getattr(
        mcp_module, "_PARAM_LEADS", {}
    ), "cursor is hand-listed, so this test proves nothing about the rule"
    desc = _input_schema(mcp_module, "filings_list")["properties"]["cursor"].get("description", "")
    assert "invalid_cursor" in desc or "400" in desc, (
        f"the derived rule did not reach an un-curated parameter: {desc!r}"
    )


def test_the_value_list_still_survives_alongside_the_rules(mcp_module) -> None:
    """Control: adding the failure rules must not push the member list back out.
    Both have to fit, and if they ever cannot, that is a cap decision to take
    deliberately rather than discover."""
    desc = _input_schema(mcp_module, "companies_financials_retrieve")["properties"][
        "include"
    ].get("description", "")
    for member in ("as_reported", "preliminary", "revisions", "split_adjusted",
                   "standalone_quarters"):
        assert member in desc, f"{member} was displaced by the failure rules: {desc!r}"


def test_an_operative_sentence_keeps_the_value_it_binds_to(mcp_module) -> None:
    """Found by reading the generated output as prose, not by a reviewer.

    Upstream states "Not served with `as_known_at`." TWICE — once after
    `as_reported` and once after `split_adjusted`. Extracting the sentence alone
    deduped them into one rule with NO ANTECEDENT, which a model can read as
    applying to all five members. That is worse in a specific way: it would steer
    a caller off `as_known_at` entirely on a 40-credit call, so the fix for an
    invisible rule had made a visible but ungrounded one."""
    desc = _input_schema(mcp_module, "companies_financials_retrieve")["properties"][
        "include"
    ].get("description", "")
    # ⚠ Asserted on the RULE SENTENCE, not on a leading slice. The first version
    # of this test checked the text before "Comma-separated." — which contains
    # the MEMBER LIST, so `as_reported` and `split_adjusted` were present for an
    # unrelated reason and the test passed in the RED phase. Third vacuous
    # assertion of the day with the same shape: asserting over a region that
    # holds the words you are looking for, put there by something else.
    import re
    rules = [t for t in re.split(r"(?<=\.)\s+", desc) if "as_known_at" in t and "Not served" in t]
    assert rules, f"the incompatibility rule is gone entirely: {desc!r}"
    bound = [r for r in rules if "as_reported" in r or "split_adjusted" in r]
    assert bound, (
        "the rule reached the schema with NO antecedent, so it reads as applying "
        f"to all five members: {rules!r}"
    )


def test_a_subject_is_only_bound_when_the_schema_says_it_is_one(mcp_module) -> None:
    """Round 3 bound an operative fragment to the last identifier that opened a
    sentence. That is right for `include`, whose description is written one
    paragraph per enum member — and WRONG for `cursor`, where an earlier
    sentence opens with `ordering`. The emitted text read "`ordering`: Adding
    `page`, or changing `ordering` mid-walk, returns 400", attributing cursor's
    failure rule to a different parameter.

    MIS-grounded is worse than un-grounded: round 3 fixed a vague rule by making
    a false one. The fix is to stop guessing from prose and check the schema —
    bind a subject only when it is a declared member of THIS parameter's enum.
    `cursor` has no enum, so it can never acquire a subject."""
    desc = _input_schema(mcp_module, "filings_list")["properties"]["cursor"].get("description", "")
    assert "`ordering`:" not in desc, f"cursor's rules are attributed to `ordering`: {desc!r}"
    assert "400" in desc, f"the 400 rule was lost: {desc!r}"


def test_both_cursor_failure_rules_survive(mcp_module) -> None:
    """The 400 rule is 89 chars and the 503 rule is 151; the lead budget was 176,
    so the second was dropped by the `break` — while the comment above it claimed
    the 503 note was front-loaded. A parameter carrying hard failure rules gets
    enough cap to hold them, rather than ever-cleverer extraction."""
    desc = _input_schema(mcp_module, "filings_list")["properties"]["cursor"].get("description", "")
    assert "400" in desc and "503" in desc, f"a failure rule was dropped: {desc!r}"
    assert "release_datetime_from" in desc or "added_to_platform_from" in desc, (
        f"the 503 RECOVERY is missing, which is the actionable half: {desc!r}"
    )
    # ⚠ NOT a substring check. "empty `cursor=`" survives the truncation that
    # destroys the instruction — the emitted text was "Send an empty `cursor=`
    # for th…" and this assertion passed on it. Fourth vacuous assertion of the
    # day, same shape every time: the words you look for are still present for
    # a reason that is not the one you care about. Assert the INSTRUCTION, which
    # means the part that tells you what to send and what to do next.
    assert "for the first page" in desc, (
        f"the first-page instruction is truncated mid-sentence: {desc!r}"
    )
    assert "follow `next`" in desc, (
        f"the continuation half of the walk instruction was cut: {desc!r}"
    )


def test_include_keeps_its_real_antecedent(mcp_module) -> None:
    """Control for the narrowing: `include` DOES have an enum, so its fragments
    must still bind. Tightening the rule must not throw away round 3's fix."""
    desc = _input_schema(mcp_module, "companies_financials_retrieve")["properties"][
        "include"
    ].get("description", "")
    import re
    rules = [t for t in re.split(r"(?<=\.)\s+", desc) if "Not served" in t]
    assert rules and any("as_reported" in r or "split_adjusted" in r for r in rules), (
        f"include lost its antecedent: {rules!r}"
    )
