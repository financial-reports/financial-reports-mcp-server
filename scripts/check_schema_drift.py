"""Detect drift between the live FinancialReports OpenAPI schema and the
committed snapshot at ``scripts/openapi.snapshot.json``.

Why this exists
---------------
CI and the Docker build both set ``FR_PIN_SCHEMA=1``, so the generated tool
surface is rendered from the *committed* snapshot rather than a build-time live
fetch. That is deliberate — it makes the shipped surface deterministic and
reviewed. The cost is that the snapshot silently lags the live API: nothing in
the build goes red when the upstream schema moves.

The sharp edge this check exists for
------------------------------------
``_PRUNED_EXCLUDE`` in ``scripts/generate_mcp_tools.py`` is a **denylist**, not
an allowlist. Every operation the live schema gains is therefore emitted onto
the *curated default* LLM-facing surface the moment the snapshot is refreshed,
unless somebody remembers to add it to ``_PRUNED_EXCLUDE`` in the same PR. A
new upstream endpoint does not need a decision to reach every connected client
— it needs a decision to *stay off*. So the most important section of the
report below is "Tools that would join the DEFAULT surface".

Design notes
------------
* ``SCHEMA_URL`` and ``_PRUNED_EXCLUDE`` are **imported** from the generator so
  the two can never disagree. Importing the generator is side-effect-free: its
  module body only defines constants, template strings and functions — the
  schema fetch and the file write both live in ``main()``, which only runs
  under ``if __name__ == "__main__"``.
* The live endpoint serves **YAML**; the snapshot on disk is **JSON**. That
  asymmetry is not an accident, it mirrors ``generate_mcp_tools.main()``
  exactly (``yaml.safe_load(response.content)`` for the live fetch,
  ``json.load`` for the pinned file). Keep both in step.
* **This script always exits 0.** Drift is signalled through the
  ``drifted=true|false`` output on ``$GITHUB_OUTPUT``, so a transient fetch
  outage produces a "could not check" report instead of paging anyone.

Usage::

    python scripts/check_schema_drift.py --report drift-report.md
    python scripts/check_schema_drift.py --live-schema some.yaml   # offline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from generate_mcp_tools import (  # noqa: E402  (deliberate post-sys.path import)
    _PRUNED_EXCLUDE,
    SCHEMA_URL,
    snake_case,
)

SNAPSHOT_PATH = _SCRIPTS_DIR / "openapi.snapshot.json"

#: Methods the generator actually turns into MCP tools. Anything else in the
#: schema is inert as far as the served surface is concerned, but is still
#: reported so a DELETE/PATCH addition stays visible.
TOOL_METHODS = ("get", "post")

#: Every method an OpenAPI path item may carry, so ``$ref`` / ``parameters`` /
#: ``summary`` siblings are not mistaken for operations.
_HTTP_METHODS = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)

FETCH_TIMEOUT_SECONDS = 120.0
_USER_AGENT = "FinancialReports-MCP-DriftCheck/1.0"


# ---------------------------------------------------------------------------
# Schema introspection helpers (pure — no network, no filesystem)
# ---------------------------------------------------------------------------

def operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Map ``(path, method)`` -> operation object for every real operation."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in (schema.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            found[(path, method.lower())] = operation
    return found


def parameter_names(operation: dict[str, Any]) -> set[str]:
    """Names of every declared parameter (path, query, header, cookie).

    Request-body properties are intentionally out of scope: the generator
    derives POST arguments from the body schema, and body-shape changes already
    surface through the ``components.schemas`` diff.
    """
    names: set[str] = set()
    for param in operation.get("parameters") or []:
        if isinstance(param, dict) and param.get("name"):
            names.add(str(param["name"]))
    return names


def component_schemas(schema: dict[str, Any]) -> set[str]:
    """The ``components.schemas`` key set."""
    components = schema.get("components") or {}
    schemas = components.get("schemas") or {}
    return set(schemas) if isinstance(schemas, dict) else set()


def _op_label(path: str, method: str) -> str:
    return f"{method.upper()} {path}"


def default_surface_tool_name(operation: dict[str, Any]) -> str | None:
    """The generated function name for an operation, or ``None`` if it could
    never become a tool (no ``operationId``)."""
    operation_id = operation.get("operationId")
    if not operation_id:
        return None
    return snake_case(operation_id)


def joins_default_surface(
    path: str, method: str, operation: dict[str, Any]
) -> str | None:
    """Return the tool name a new operation would silently gain on the *default*
    (pruned) surface, or ``None`` if it would not be served there.

    This is the denylist consequence spelled out: presence in
    ``_PRUNED_EXCLUDE`` is the *only* thing that keeps an operation off the
    curated surface.
    """
    if method.lower() not in TOOL_METHODS:
        return None
    func_name = default_surface_tool_name(operation)
    if func_name is None or func_name in _PRUNED_EXCLUDE:
        return None
    return func_name


# ---------------------------------------------------------------------------
# Drift model
# ---------------------------------------------------------------------------

@dataclass
class SchemaDrift:
    """The full comparison result. ``breaking_reasons`` drives classification."""

    snapshot_version: str = ""
    live_version: str = ""
    snapshot_title: str = ""
    live_title: str = ""

    added_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    added_operations: list[str] = field(default_factory=list)
    removed_operations: list[str] = field(default_factory=list)
    renamed_operation_ids: list[tuple[str, str, str]] = field(default_factory=list)
    added_parameters: dict[str, list[str]] = field(default_factory=dict)
    removed_parameters: dict[str, list[str]] = field(default_factory=dict)
    added_schemas: list[str] = field(default_factory=list)
    removed_schemas: list[str] = field(default_factory=list)
    new_default_surface_tools: list[tuple[str, str]] = field(default_factory=list)
    breaking_reasons: list[str] = field(default_factory=list)

    @property
    def version_changed(self) -> bool:
        return self.snapshot_version != self.live_version

    @property
    def title_changed(self) -> bool:
        return self.snapshot_title != self.live_title

    @property
    def is_breaking(self) -> bool:
        return bool(self.breaking_reasons)

    @property
    def has_drifted(self) -> bool:
        return bool(
            self.version_changed
            or self.title_changed
            or self.added_paths
            or self.removed_paths
            or self.added_operations
            or self.removed_operations
            or self.renamed_operation_ids
            or self.added_parameters
            or self.removed_parameters
            or self.added_schemas
            or self.removed_schemas
        )

    @property
    def classification(self) -> str:
        if not self.has_drifted:
            return "none"
        return "breaking" if self.is_breaking else "additive"


def diff_schemas(snapshot: dict[str, Any], live: dict[str, Any]) -> SchemaDrift:
    """Compare two parsed OpenAPI documents.

    Pure function — unit-tested with synthetic dicts, never touches the network.
    """
    snap_info = snapshot.get("info") or {}
    live_info = live.get("info") or {}

    drift = SchemaDrift(
        snapshot_version=str(snap_info.get("version", "")),
        live_version=str(live_info.get("version", "")),
        snapshot_title=str(snap_info.get("title", "")),
        live_title=str(live_info.get("title", "")),
    )

    snap_paths = set(snapshot.get("paths") or {})
    live_paths = set(live.get("paths") or {})
    drift.added_paths = sorted(live_paths - snap_paths)
    drift.removed_paths = sorted(snap_paths - live_paths)

    snap_ops = operations(snapshot)
    live_ops = operations(live)
    drift.added_operations = sorted(
        _op_label(path, method) for path, method in live_ops.keys() - snap_ops.keys()
    )
    drift.removed_operations = sorted(
        _op_label(path, method) for path, method in snap_ops.keys() - live_ops.keys()
    )

    for key in sorted(snap_ops.keys() & live_ops.keys()):
        path, method = key
        label = _op_label(path, method)
        before, after = snap_ops[key], live_ops[key]

        before_id = before.get("operationId") or ""
        after_id = after.get("operationId") or ""
        if before_id != after_id:
            drift.renamed_operation_ids.append((label, before_id, after_id))

        before_params = parameter_names(before)
        after_params = parameter_names(after)
        added = sorted(after_params - before_params)
        if added:
            drift.added_parameters[label] = added
        removed = sorted(before_params - after_params)
        if removed:
            drift.removed_parameters[label] = removed

    snap_schemas = component_schemas(snapshot)
    live_schemas = component_schemas(live)
    drift.added_schemas = sorted(live_schemas - snap_schemas)
    drift.removed_schemas = sorted(snap_schemas - live_schemas)

    for key in sorted(live_ops.keys() - snap_ops.keys()):
        path, method = key
        func_name = joins_default_surface(path, method, live_ops[key])
        if func_name:
            drift.new_default_surface_tools.append(
                (func_name, _op_label(path, method))
            )

    drift.breaking_reasons = classify_breaking(drift)
    return drift


def classify_breaking(drift: SchemaDrift) -> list[str]:
    """Breaking = anything that can make an *already generated* tool stop
    working: a path or operation that disappeared, a parameter an existing tool
    still sends, or an ``operationId`` rename (which renames the tool and
    breaks every client prompt, skill and eval that names it).

    Everything else — new paths, new operations, new optional parameters, new
    component schemas, a bumped ``info.version`` — is additive.
    """
    reasons: list[str] = []
    if drift.removed_paths:
        reasons.append(
            f"{len(drift.removed_paths)} path(s) removed: "
            + ", ".join(drift.removed_paths)
        )
    if drift.removed_operations:
        reasons.append(
            f"{len(drift.removed_operations)} operation(s) removed: "
            + ", ".join(drift.removed_operations)
        )
    if drift.removed_parameters:
        detail = "; ".join(
            f"{label} ({', '.join(names)})"
            for label, names in sorted(drift.removed_parameters.items())
        )
        reasons.append(f"parameter(s) removed: {detail}")
    if drift.renamed_operation_ids:
        detail = "; ".join(
            f"{label}: {before or '<none>'} -> {after or '<none>'}"
            for label, before, after in drift.renamed_operation_ids
        )
        reasons.append(f"operationId changed (renames the tool): {detail}")
    return reasons


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _bullets(items: Iterable[str], empty: str = "_none_") -> str:
    listed = [f"- `{item}`" for item in items]
    return "\n".join(listed) if listed else empty


def render_report(drift: SchemaDrift, schema_url: str = SCHEMA_URL) -> str:
    """Markdown report — written to ``--report`` and posted to the tracking issue.

    Contains no timestamp on purpose: the same schema pair always renders the
    same bytes, so a repeated weekly comment is obviously a repeat.
    """
    lines: list[str] = [
        "## OpenAPI snapshot drift report",
        "",
        f"- **Live schema:** {schema_url}",
        "- **Snapshot:** `scripts/openapi.snapshot.json`",
        (
            f"- **`info.version`:** `{drift.snapshot_version}` (snapshot) → "
            f"`{drift.live_version}` (live)"
        ),
    ]
    if drift.title_changed:
        lines.append(
            f"- **`info.title`:** `{drift.snapshot_title}` → `{drift.live_title}`"
        )
    lines.append(f"- **Classification:** **{drift.classification.upper()}**")
    lines.append("")

    if not drift.has_drifted:
        lines += [
            (
                "No drift. The committed snapshot matches the live schema on"
                " version, title, paths, operations, per-operation parameters"
                " and `components.schemas`."
            ),
            "",
        ]
        return "\n".join(lines)

    if drift.is_breaking:
        lines += ["### Breaking drift", ""]
        lines += [f"- {reason}" for reason in drift.breaking_reasons]
        lines.append("")
    else:
        lines += [
            "### Additive drift only",
            "",
            (
                "Nothing was removed and no `operationId` changed, so refreshing"
                " the snapshot cannot break an existing tool."
            ),
            "",
        ]

    lines += [
        "### Tools that would join the DEFAULT surface",
        "",
        (
            "`_PRUNED_EXCLUDE` in `scripts/generate_mcp_tools.py` is a"
            " **denylist**. Every new operation listed here is emitted onto the"
            " curated default (LLM-facing) surface the moment the snapshot is"
            " refreshed — no extra decision required. To keep one *off*, it must"
            " be added to `_PRUNED_EXCLUDE` in the same PR that bumps the"
            " snapshot. **This is the reason this check exists.**"
        ),
        "",
    ]
    if drift.new_default_surface_tools:
        lines += [
            f"- `{func_name}` — from `{label}`"
            for func_name, label in drift.new_default_surface_tools
        ]
        lines += [
            "",
            (
                "**Default surface would grow by "
                f"{len(drift.new_default_surface_tools)} tool(s).**"
            ),
        ]
    else:
        lines.append(
            "_No new operation would join the default surface (every new"
            " operation is already denylisted, lacks an `operationId`, or uses a"
            " method the generator skips)._"
        )
    lines.append("")

    lines += [
        "### Paths",
        "",
        f"Added ({len(drift.added_paths)}):",
        "",
        _bullets(drift.added_paths),
        "",
        f"Removed ({len(drift.removed_paths)}):",
        "",
        _bullets(drift.removed_paths),
        "",
        "### Operations",
        "",
        f"Added ({len(drift.added_operations)}):",
        "",
        _bullets(drift.added_operations),
        "",
        f"Removed ({len(drift.removed_operations)}):",
        "",
        _bullets(drift.removed_operations),
        "",
    ]
    if drift.renamed_operation_ids:
        lines += ["Renamed `operationId`s:", ""]
        lines += [
            f"- `{label}`: `{before or '<none>'}` → `{after or '<none>'}`"
            for label, before, after in drift.renamed_operation_ids
        ]
        lines.append("")

    lines += ["### Parameters on operations present in both", ""]
    if drift.added_parameters:
        for label, names in sorted(drift.added_parameters.items()):
            lines.append(f"- `{label}` gained: {', '.join(f'`{n}`' for n in names)}")
    else:
        lines.append("- none added")
    if drift.removed_parameters:
        for label, names in sorted(drift.removed_parameters.items()):
            lines.append(f"- `{label}` lost: {', '.join(f'`{n}`' for n in names)}")
    else:
        lines.append("- none removed")
    lines.append("")

    lines += [
        "### `components.schemas`",
        "",
        f"Added ({len(drift.added_schemas)}):",
        "",
        _bullets(drift.added_schemas),
        "",
        f"Removed ({len(drift.removed_schemas)}):",
        "",
        _bullets(drift.removed_schemas),
        "",
        "### How to act on this",
        "",
        (
            "1. Decide, per tool listed above, whether it belongs on the default"
            " surface. Anything that should stay off goes into `_PRUNED_EXCLUDE`."
        ),
        "2. Refresh `scripts/openapi.snapshot.json` from the live schema.",
        "3. `make regen` and re-run the unit suite.",
        (
            "4. `make audit` — `docs/token-budget.md` is diff-gated in"
            " `.github/workflows/ci.yml`, so a stale baseline fails CI."
        ),
        "5. Update the hand-written tool counts in `README.md`.",
        "",
        "All five belong in **one** PR; splitting them leaves `main` red.",
        "",
    ]
    return "\n".join(lines)


def render_fetch_failure_report(
    error: BaseException, schema_url: str = SCHEMA_URL
) -> str:
    """Report for the case where the live schema could not be fetched or parsed."""
    return "\n".join(
        [
            "## OpenAPI snapshot drift report",
            "",
            f"- **Live schema:** {schema_url}",
            "- **Classification:** **UNKNOWN (fetch failed)**",
            "",
            "### Could not check",
            "",
            f"Fetching the live schema failed: `{type(error).__name__}: {error}`",
            "",
            (
                "This run reports `drifted=false` on purpose. A transient"
                " upstream outage must not open an issue or page anyone; the next"
                " weekly run re-checks."
            ),
            "",
        ]
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    """The committed snapshot is JSON (see ``generate_mcp_tools.main()``)."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def fetch_live_schema(url: str = SCHEMA_URL) -> dict[str, Any]:
    """Fetch and parse the live schema.

    The endpoint serves YAML, so ``yaml.safe_load`` — same as the generator.
    ``follow_redirects=True`` because financialreports.eu 301s to
    financialfilings.com, and the next hostname move must not break this
    silently (that is exactly how the old URL rotted; see #70).
    """
    response = httpx.get(
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    parsed = yaml.safe_load(response.content)
    # A 200 that isn't a schema (login page, HTML error) parses "successfully"
    # and would otherwise be reported as "every path removed" — the loudest
    # possible false positive. Refuse instead.
    if not isinstance(parsed, dict) or not parsed.get("paths"):
        raise ValueError(
            f"schema at {url} parsed but has no 'paths' "
            f"(got {type(parsed).__name__}) — refusing to compare"
        )
    return parsed


def load_local_schema(path: Path) -> dict[str, Any]:
    """Parse a local schema file, JSON or YAML (YAML is a JSON superset)."""
    with open(path, encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle)
    if not isinstance(parsed, dict):
        raise TypeError(f"{path} did not parse to a mapping")
    return parsed


def write_github_output(**values: str) -> None:
    """Append ``key=value`` pairs to ``$GITHUB_OUTPUT`` when running in Actions."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in values.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff the live FinancialReports OpenAPI schema against the "
        "committed snapshot. Always exits 0."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=SNAPSHOT_PATH,
        help="committed snapshot to compare against (default: %(default)s)",
    )
    parser.add_argument(
        "--live-schema",
        type=Path,
        default=None,
        help="read the 'live' schema from a local file instead of fetching it "
        "(offline testing)",
    )
    parser.add_argument(
        "--schema-url",
        default=SCHEMA_URL,
        help="live schema URL (default: imported from generate_mcp_tools)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the markdown report to this path",
    )
    args = parser.parse_args(argv)

    snapshot = load_snapshot(args.snapshot)

    try:
        live = (
            load_local_schema(args.live_schema)
            if args.live_schema
            else fetch_live_schema(args.schema_url)
        )
    except Exception as exc:  # noqa: BLE001 — a fetch outage must never page
        report = render_fetch_failure_report(exc, args.schema_url)
        print(report)
        if args.report:
            args.report.write_text(report, encoding="utf-8")
        write_github_output(drifted="false", classification="unknown")
        # Always 0 — see the module docstring.
        return 0

    drift = diff_schemas(snapshot, live)
    report = render_report(drift, args.schema_url)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")

    write_github_output(
        drifted="true" if drift.has_drifted else "false",
        classification=drift.classification,
        snapshot_version=drift.snapshot_version,
        live_version=drift.live_version,
        new_default_tools=str(len(drift.new_default_surface_tools)),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
