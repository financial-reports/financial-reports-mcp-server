"""Every JSON eval mock body may only carry fields and values the served API returns.

⛔ WHY. Across six SPECHT rounds on #220 the single most repeated defect was a
mock carrying fields the real API does not serve, or missing ones it does:
`company`/`results` instead of `company_id`/`periods`, `resolved`/`unresolved`
instead of `{summary, results}`, `period_ending_date` on a FilingSummary row,
`country_iso`/`isin`/`ticker`/`listing_status`/`currency` on CompanyMinimal,
`employees`/`website`/`currency` on Company. EVERY ONE made the benchmark easier,
because a fixture more generous than the API lets a skill pass on a field that
will not exist in production. Each was found by a reviewer reading the snapshot
by hand, one round at a time.

This test does that check mechanically, against `scripts/openapi.snapshot.json`,
which is what the shipping server is generated from. It checks KEYS first (an
invented field is the commonest failure), then VALUES where the schema constrains
them: enum membership, object-vs-scalar, and decimal-as-string. Fixed bodies and
the fenced ```json blocks of agent mocks are both checked.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / "scripts" / "openapi.snapshot.json").read_text(encoding="utf-8"))
SCHEMAS = SNAPSHOT["components"]["schemas"]
EVALS = ROOT / "plugins" / "financialfilings" / "evals"


def _operation(tool: str):
    for path, ops in SNAPSHOT["paths"].items():
        for method, op in ops.items():
            if isinstance(op, dict) and op.get("operationId") == tool:
                return path, method, op
    return None


def _deref(schema: dict) -> dict:
    while isinstance(schema, dict) and "$ref" in schema:
        schema = SCHEMAS[schema["$ref"].rsplit("/", 1)[-1]]
    if isinstance(schema, dict) and "oneOf" in schema:
        options = [o for o in schema["oneOf"] if o.get("type") != "null"]
        if len(options) == 1:
            return _deref(options[0])
    return schema


def _response_schema(op: dict) -> dict | None:
    resp = op.get("responses", {}).get("200", {})
    sch = resp.get("content", {}).get("application/json", {}).get("schema")
    return _deref(sch) if sch else None


_FENCE = re.compile(r"```json\n(.*?)\n```", re.S)


def _bodies(md: pathlib.Path) -> list:
    """The JSON a mock can return: a fixed body, or each fenced block of an agent mock.

    An agent mock is prose instructions, so it is not checkable as a whole -- but
    when it carries its per-input responses as fenced ```json blocks, each block
    is exactly what the tool will return and is checked like a fixed body. The
    first version skipped agent mocks entirely, so converting a fixed mock to an
    agent mock (to make it vary by input) silently took it out of this gate.
    """
    text = md.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return []
    body = re.sub(r"<!--.*?-->", "", parts[2], flags=re.S).strip()
    if "type: agent" in parts[1]:
        return [json.loads(block) for block in _FENCE.findall(body)]
    if "type: fixed" not in parts[1] or not body.startswith("{"):
        return []  # markdown guide bodies, not JSON
    # templated substitutions are not JSON; any number stands in for them
    body = re.sub(r"\{\{input\.[a-z_]+\}\}", "1", body)
    return [json.loads(body)]


def _mocks():
    found = []
    for md in sorted(EVALS.rglob("mocks/financialfilings/*.md")):
        bodies = _bodies(md)
        if not bodies:
            continue
        hit = _operation(md.stem)
        if hit is None:
            continue
        schema = _response_schema(hit[2])
        if not schema or "properties" not in schema:
            continue  # no published response shape to check against
        found += [(md, body, schema) for body in bodies]
    return found


MOCKS = _mocks()


def test_the_checker_finds_the_mocks_it_must_guard() -> None:
    """Positive control, first: a checker that finds nothing passes everything."""
    stems = {md.stem for md, _b, _s in MOCKS}
    # filings_retrieve is an AGENT mock: listing it proves the fenced-block path runs.
    assert {"companies_list", "companies_retrieve", "filings_list", "filings_retrieve"} <= stems, (
        f"expected the core mocks to be checkable, found {sorted(stems)}"
    )


def _invented(body: dict, schema: dict) -> list[str]:
    bad = sorted(k for k in body if k not in schema["properties"])
    results = schema["properties"].get("results")
    if isinstance(body.get("results"), list) and results:
        item = _deref(results.get("items", {}))
        if "properties" in item:
            for i, row in enumerate(body["results"]):
                if isinstance(row, dict):
                    bad += [f"results[{i}].{k}" for k in row if k not in item["properties"]]
    return bad


@pytest.mark.parametrize("md,body,schema", MOCKS, ids=lambda v: getattr(v, "name", ""))
def test_no_mock_carries_a_field_the_api_does_not_serve(md, body, schema) -> None:
    bad = _invented(body, schema)
    assert not bad, (
        f"{md.relative_to(ROOT)} carries fields the served response does not have: "
        f"{bad}. A fixture more generous than the API lets a skill pass on a field "
        "that will not exist in production."
    )


def test_the_shape_check_can_fail() -> None:
    """Mutation control: an invented key must be reported."""
    md, body, schema = next(m for m in MOCKS if m[0].stem == "companies_retrieve")
    assert _invented({**body, "employees": 1}, schema) == ["employees"]


# --- types and enums, recursively (#220 round 8) -------------------------------
#
# Key-checking alone passed a financials mock that had every right KEY and the
# wrong VALUES: `currency` as the string "SEK" where the API serves an object
# `{code, name, symbol}`, `value` as a number where it serves an exact decimal
# STRING, `scale` as "MILLIONS" where the enum is lower-case, and a `trust_tier`
# of "XBRL_AUDITED", which is not a tier at all. An agent can pass an eval by
# interpreting a shape it will never receive in production, so the values are
# checked too: enum membership, object-vs-scalar, and decimal-as-string.


def _types(schema: dict) -> set:
    t = schema.get("type")
    return set(t) if isinstance(t, list) else ({t} if t else set())


def _value_errors(value, schema: dict, path: str) -> list[str]:
    schema = _deref(schema)
    errs: list[str] = []
    types = _types(schema)
    if value is None:
        # A null is valid wherever the served type admits it, whether or not the
        # enum lists None. The first version checked the enum BEFORE this and
        # flagged a legitimately nullable `filters.min_trust_tier` -- a false
        # positive in the checker, caught on its first run against real mocks.
        if types and "null" not in types and None not in schema.get("enum", [None]):
            errs.append(f"{path} is null, served type is {sorted(types)}")
        return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}={value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        if types and "object" not in types:
            errs.append(f"{path} is an object, served type is {sorted(types)}")
        for key, sub in value.items():
            prop = schema.get("properties", {}).get(key)
            if prop is not None:
                errs += _value_errors(sub, prop, f"{path}.{key}")
        return errs
    if isinstance(value, list):
        if types and "array" not in types:
            errs.append(f"{path} is an array, served type is {sorted(types)}")
        items = schema.get("items")
        if items:
            for i, sub in enumerate(value):
                errs += _value_errors(sub, items, f"{path}[{i}]")
        return errs
    if "object" in types and "string" not in types:
        errs.append(f"{path}={value!r} is a scalar, served type is an object")
    if schema.get("format") == "decimal" and not isinstance(value, str):
        errs.append(f"{path}={value!r} must be an exact decimal STRING, not a number")
    return errs


@pytest.mark.parametrize("md,body,schema", MOCKS, ids=lambda v: getattr(v, "name", ""))
def test_no_mock_value_has_a_type_or_enum_the_api_does_not_serve(md, body, schema) -> None:
    errs = _value_errors(body, schema, "$")
    assert not errs, f"{md.relative_to(ROOT)}: " + "; ".join(errs[:8])


def test_the_value_check_can_fail() -> None:
    """Mutation controls, one per rule: each must be reported."""
    md, body, schema = next(m for m in MOCKS if m[0].stem == "companies_financials_retrieve")
    assert _value_errors({**body, "currency": "SEK"}, schema, "$"), "string currency passed"
    bad_period = dict(body)
    period = dict(body["periods"][0])
    stmt = dict(period["statements"][0])
    item = dict(stmt["line_items"][0])
    for mutation in ({"scale": "MILLIONS"}, {"trust_tier": "XBRL_AUDITED"}, {"value": 51900}):
        stmt["line_items"] = [{**item, **mutation}]
        period["statements"] = [stmt]
        bad_period["periods"] = [period]
        assert _value_errors(bad_period, schema, "$"), f"{mutation} passed"
