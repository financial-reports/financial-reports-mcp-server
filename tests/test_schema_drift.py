"""Unit tests for the OpenAPI snapshot drift classifier.

Entirely synthetic: every schema here is a hand-built dict, so nothing in this
module touches the network or the committed 42-path snapshot. The classifier is
the part worth pinning, because the weekly workflow's decision to open an issue
rides on `drifted` plus its additive/breaking verdict.

The load-bearing pair is `test_new_operation_joins_default_surface_by_default`
and `test_denylisted_new_operation_stays_off_default_surface`: together they
encode that `_PRUNED_EXCLUDE` is a DENYLIST, i.e. a new upstream endpoint reaches
every connected client unless somebody explicitly excludes it.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_schema_drift as drift_mod  # noqa: E402
from generate_mcp_tools import _PRUNED_EXCLUDE  # noqa: E402

_BASE_PATHS: dict = {
    "/companies/": {
        "get": {
            "operationId": "companies_list",
            "parameters": [
                {"name": "search", "in": "query", "schema": {"type": "string"}},
                {"name": "page", "in": "query", "schema": {"type": "integer"}},
            ],
        }
    },
    "/filings/{id}/": {
        "get": {
            "operationId": "filings_retrieve",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                },
            ],
        }
    },
}


def _schema(
    *,
    version: str = "1.0.0",
    title: str = "Synthetic API",
    paths: dict | None = None,
    schemas: dict | None = None,
) -> dict:
    """A minimal but structurally faithful OpenAPI 3.1 document."""
    return {
        "openapi": "3.1.0",
        "info": {"version": version, "title": title},
        "paths": copy.deepcopy(paths if paths is not None else _BASE_PATHS),
        "components": {"schemas": copy.deepcopy(schemas or {"Company": {}})},
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# No drift
# ---------------------------------------------------------------------------

def test_identical_schemas_report_no_drift() -> None:
    result = drift_mod.diff_schemas(_schema(), _schema())

    assert result.has_drifted is False
    assert result.is_breaking is False
    assert result.classification == "none"
    assert "No drift." in drift_mod.render_report(result)


# ---------------------------------------------------------------------------
# Additive drift
# ---------------------------------------------------------------------------

def test_version_bump_alone_is_additive_drift() -> None:
    result = drift_mod.diff_schemas(
        _schema(version="1.1.5"), _schema(version="1.3.0")
    )

    assert result.has_drifted is True
    assert result.classification == "additive"
    assert result.snapshot_version == "1.1.5"
    assert result.live_version == "1.3.0"
    assert result.breaking_reasons == []


def test_title_change_is_drift_but_not_breaking() -> None:
    result = drift_mod.diff_schemas(
        _schema(title="FinancialReports API"), _schema(title="FinancialFilings API")
    )

    assert result.title_changed is True
    assert result.classification == "additive"
    assert "FinancialFilings API" in drift_mod.render_report(result)


def test_new_optional_parameter_is_additive() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/"]["get"]["parameters"].append(
        {"name": "cik", "in": "query", "schema": {"type": "string"}}
    )

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_parameters == {"GET /companies/": ["cik"]}
    assert result.removed_parameters == {}
    assert result.classification == "additive"


def test_component_schema_additions_are_reported() -> None:
    result = drift_mod.diff_schemas(
        _schema(schemas={"Company": {}}),
        _schema(schemas={"Company": {}, "SecurityListing": {}}),
    )

    assert result.added_schemas == ["SecurityListing"]
    assert result.removed_schemas == []
    assert result.classification == "additive"


def test_removed_component_schema_is_drift_but_not_classified_breaking() -> None:
    """A dropped component schema is recorded, but does not flip the verdict.

    Breaking is defined narrowly as "an already generated tool can stop
    working": removed paths, removed operations, removed parameters, or a
    renamed operationId. A component schema can vanish because it was inlined
    or renamed upstream without any served tool changing shape, so it stays
    additive and is left for a human to read in the report.
    """
    result = drift_mod.diff_schemas(
        _schema(schemas={"Company": {}, "Legacy": {}}),
        _schema(schemas={"Company": {}}),
    )

    assert result.removed_schemas == ["Legacy"]
    assert result.classification == "additive"


# ---------------------------------------------------------------------------
# The denylist consequence — the reason this check exists
# ---------------------------------------------------------------------------

def test_new_operation_joins_default_surface_by_default() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/resolve/"] = {
        "post": {"operationId": "companies_resolve_create", "parameters": []}
    }

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_paths == ["/companies/resolve/"]
    assert result.added_operations == ["POST /companies/resolve/"]
    assert result.new_default_surface_tools == [
        ("companies_resolve_create", "POST /companies/resolve/")
    ]
    report = drift_mod.render_report(result)
    assert "denylist" in report
    assert "companies_resolve_create" in report
    assert "Default surface would grow by 1 tool(s)." in report


def test_denylisted_new_operation_stays_off_default_surface() -> None:
    # Guard: if the denylist stops containing this name the assertion below is
    # meaningless, so pin the precondition explicitly.
    assert "webhooks_list" in _PRUNED_EXCLUDE

    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/webhooks/"] = {
        "get": {"operationId": "webhooks_list", "parameters": []}
    }

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_operations == ["GET /webhooks/"]
    assert result.new_default_surface_tools == []
    assert (
        "No new operation would join the default surface"
        in drift_mod.render_report(result)
    )


def test_non_get_post_method_never_joins_the_surface() -> None:
    """The generator only emits GET and POST tools, so a new DELETE is inert."""
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/{id}/"] = {
        "delete": {"operationId": "companies_destroy", "parameters": []}
    }

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_operations == ["DELETE /companies/{id}/"]
    assert result.new_default_surface_tools == []


def test_operation_without_operation_id_never_joins_the_surface() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/undocumented/"] = {"get": {"parameters": []}}

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_operations == ["GET /undocumented/"]
    assert result.new_default_surface_tools == []


# ---------------------------------------------------------------------------
# Breaking drift
# ---------------------------------------------------------------------------

def test_removed_path_is_breaking() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    del live_paths["/filings/{id}/"]

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.removed_paths == ["/filings/{id}/"]
    assert result.classification == "breaking"
    assert any("path(s) removed" in reason for reason in result.breaking_reasons)


def test_removed_operation_on_a_surviving_path_is_breaking() -> None:
    snapshot_paths = copy.deepcopy(_BASE_PATHS)
    snapshot_paths["/companies/"]["post"] = {
        "operationId": "companies_create",
        "parameters": [],
    }

    result = drift_mod.diff_schemas(
        _schema(paths=snapshot_paths), _schema(paths=_BASE_PATHS)
    )

    assert result.removed_paths == []
    assert result.removed_operations == ["POST /companies/"]
    assert result.classification == "breaking"


def test_removed_parameter_is_breaking() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/"]["get"]["parameters"] = [
        {"name": "search", "in": "query", "schema": {"type": "string"}}
    ]

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.removed_parameters == {"GET /companies/": ["page"]}
    assert result.classification == "breaking"
    assert any("parameter(s) removed" in r for r in result.breaking_reasons)


def test_renamed_operation_id_is_breaking() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/"]["get"]["operationId"] = "companies_search"

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.renamed_operation_ids == [
        ("GET /companies/", "companies_list", "companies_search")
    ]
    assert result.classification == "breaking"
    report = drift_mod.render_report(result)
    assert "Breaking drift" in report
    assert "companies_search" in report


def test_breaking_wins_over_simultaneous_additions() -> None:
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/security-listings/"] = {
        "get": {"operationId": "security_listings_list", "parameters": []}
    }
    del live_paths["/filings/{id}/"]

    result = drift_mod.diff_schemas(_schema(), _schema(paths=live_paths))

    assert result.added_paths == ["/security-listings/"]
    assert result.removed_paths == ["/filings/{id}/"]
    assert result.classification == "breaking"


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

def test_operations_ignores_non_method_path_item_keys() -> None:
    schema = _schema(
        paths={
            "/companies/": {
                "summary": "shared summary",
                "parameters": [{"name": "shared", "in": "query"}],
                "get": {"operationId": "companies_list"},
            }
        }
    )

    assert set(drift_mod.operations(schema)) == {("/companies/", "get")}


def test_parameter_names_tolerates_a_missing_parameters_key() -> None:
    assert drift_mod.parameter_names({"operationId": "x"}) == set()


def test_component_schemas_tolerates_a_missing_components_key() -> None:
    assert drift_mod.component_schemas({"paths": {}}) == set()


# ---------------------------------------------------------------------------
# main(): always exit 0, always emit a `drifted` output
# ---------------------------------------------------------------------------

def test_main_exits_zero_and_reports_drift(tmp_path, monkeypatch) -> None:
    snapshot = _write_json(tmp_path / "snap.json", _schema(version="1.1.5"))
    live_paths = copy.deepcopy(_BASE_PATHS)
    live_paths["/companies/resolve/"] = {
        "post": {"operationId": "companies_resolve_create", "parameters": []}
    }
    live = _write_json(
        tmp_path / "live.json", _schema(version="1.3.0", paths=live_paths)
    )
    outputs = tmp_path / "gh-output"
    report = tmp_path / "report.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    exit_code = drift_mod.main(
        [
            "--snapshot",
            str(snapshot),
            "--live-schema",
            str(live),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    emitted = outputs.read_text(encoding="utf-8")
    assert "drifted=true" in emitted
    assert "classification=additive" in emitted
    assert "new_default_tools=1" in emitted
    assert "companies_resolve_create" in report.read_text(encoding="utf-8")


def test_main_exits_zero_on_a_clean_comparison(tmp_path, monkeypatch) -> None:
    snapshot = _write_json(tmp_path / "snap.json", _schema())
    live = _write_json(tmp_path / "live.json", _schema())
    outputs = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    exit_code = drift_mod.main(
        ["--snapshot", str(snapshot), "--live-schema", str(live)]
    )

    assert exit_code == 0
    assert "drifted=false" in outputs.read_text(encoding="utf-8")


def test_main_exits_zero_when_the_live_schema_cannot_be_read(
    tmp_path, monkeypatch
) -> None:
    """A fetch outage must report drifted=false, not fail the weekly build."""
    snapshot = _write_json(tmp_path / "snap.json", _schema())
    outputs = tmp_path / "gh-output"
    report = tmp_path / "report.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    exit_code = drift_mod.main(
        [
            "--snapshot",
            str(snapshot),
            "--live-schema",
            str(tmp_path / "does-not-exist.yaml"),
            "--report",
            str(report),
        ]
    )

    assert exit_code == 0
    emitted = outputs.read_text(encoding="utf-8")
    assert "drifted=false" in emitted
    assert "classification=unknown" in emitted
    assert "Could not check" in report.read_text(encoding="utf-8")


def test_fetch_rejects_a_200_that_is_not_a_schema(monkeypatch) -> None:
    """An HTML login page parses as YAML; treating it as a schema would report
    every path as removed. Refuse loudly instead."""
    import httpx

    def _fake_get(url, **kwargs):
        assert kwargs["follow_redirects"] is True
        return httpx.Response(
            200,
            text="<html><body>Sign in</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(drift_mod.httpx, "get", _fake_get)

    with pytest.raises(ValueError, match="no 'paths'"):
        drift_mod.fetch_live_schema("https://example.invalid/api/schema/")


def test_write_github_output_is_a_noop_outside_actions(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    drift_mod.write_github_output(drifted="true")  # must not raise


def test_schema_url_is_imported_from_the_generator() -> None:
    """The whole point of importing it: the checker and the generator can never
    disagree about which URL is canonical."""
    import generate_mcp_tools

    assert drift_mod.SCHEMA_URL == generate_mcp_tools.SCHEMA_URL
