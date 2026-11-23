"""Saved searches you pull: `filings_search_save`, `filings_search_new`,
`filings_search_saved_list`, `filings_search_saved_delete` (financial-reports/web#10851).

The tools are emitted only when the schema carries the saved-search routes, and
the committed snapshot does not yet (the web side hides them while its flag is
off). So the default module is checked for their ABSENCE, and everything else
runs against a module rendered here from the snapshot plus the routes in
`fixtures/saved_search_schema.json` (copied from the web schema with the flag
on), written to a temporary file. The default module is never re-rendered here:
`test_published_tool_counts.py` owns that (see its `_regenerate_source`).

What is pinned:
  - the gate: today's snapshot emits nothing of it, the snapshot plus the
    routes emits the four tools and no generic twin, a partial set emits none;
  - the denylist keys are the schema's own operationIds (a misspelt key on a
    denylist fails open);
  - save: filings_search's validation, refused arguments named with a reason,
    the body sent (`q` a list, no `webhook`), never replayed;
  - pull: every hit rendered (a returned hit is never returned again), `more`,
    `capped`, `scan_complete` false with and without hits, empty = not billed,
    404 / 409 mapped, never replayed after it may have run, and the
    repeat_last_pull recovery;
  - list and delete (DELETE, not replayed).
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from .conftest import TEST_API_BASE, TEST_CLIENT_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_mcp_tools.py"
SNAPSHOT = REPO_ROOT / "scripts" / "openapi.snapshot.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "saved_search_schema.json"

TOOLS = {
    "filings_search_save",
    "filings_search_new",
    "filings_search_saved_list",
    "filings_search_saved_delete",
}
SAVED = f"{TEST_API_BASE}/filings/search/saved/"
PULL = f"{TEST_API_BASE}/filings/search/saved/7/new/"
ONE = f"{TEST_API_BASE}/filings/search/saved/7/"


def _generator(name: str):
    """A fresh generator module (its PRUNE_DEFAULT is read at import)."""
    spec = importlib.util.spec_from_file_location(name, GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _with_saved_search(schema: dict) -> dict:
    extra = json.loads(FIXTURE.read_text(encoding="utf-8"))
    merged = copy.deepcopy(schema)
    merged["paths"].update(extra["paths"])
    merged["components"]["schemas"].update(extra["components"]["schemas"])
    return merged


def _render(tmp: Path, schema: dict, *, full_surface: bool = False) -> str:
    gen = _generator(f"_gen_saved_{tmp.name}")
    gen.PRUNE_DEFAULT = not full_surface
    out = tmp / "financial_reports_mcp.py"
    gen.main(schema=schema, output_file=out)
    return out.read_text(encoding="utf-8")


def _tools_in(source: str) -> list[str]:
    """Every @mcp.tool function, duplicates kept (a twin can share a name)."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any("mcp.tool" in ast.unparse(d) for d in node.decorator_list)
    ]


@pytest.fixture(scope="module")
def saved_source(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("saved_default")
    _render(tmp, _with_saved_search(_snapshot()))
    return tmp / "financial_reports_mcp.py"


class _Token:
    def __init__(self) -> None:
        self.token = "real-access-token"
        self.client_id = TEST_CLIENT_ID
        self.claims = {"sub": "test-sub-12345678", "client_id": TEST_CLIENT_ID}


@pytest.fixture()
def m(saved_source, respx_router, monkeypatch):
    """The module rendered WITH the saved-search routes, imported inside the
    respx context (its OIDC discovery runs at import), authenticated."""
    spec = importlib.util.spec_from_file_location("_saved_search_mcp", saved_source)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_saved_search_mcp"] = module
    spec.loader.exec_module(module)

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(module, "_retry_sleep", _instant)
    monkeypatch.setattr(module, "get_access_token", lambda: _Token())
    yield module
    sys.modules.pop("_saved_search_mcp", None)


def _fn(module, name):
    tool = module.mcp._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "function", None)


def _hit(
    fid, *, match=None, released="2019-04-02T08:00:00Z", added="2026-11-23T09:15:00Z"
):
    return {
        "filing_id": str(fid),
        "title": f"Report {fid}",
        "company": {"id": str(900 + fid), "name": f"Company {fid}"},
        "filing_type_code": "AR",
        "release_datetime": released,
        "added_to_platform": added,
        "match": match,
    }


LITERAL = {
    "query": "going concern",
    "total_hits": 2,
    "hits": [{"offset": 1200, "snippet": "material uncertainty ... going concern ..."}],
}


def _pull(hits, *, more=0, capped=False, scan_complete=True):
    return {
        "saved_search": {"id": "7", "name": "Going concern"},
        "hits": hits,
        "more": more,
        "capped": capped,
        "scan_complete": scan_complete,
        "window": {
            "added_to_platform_from": "2026-11-22T09:00:00Z",
            "added_to_platform_to": "2026-11-23T10:00:00Z",
        },
    }


# --- the gate -----------------------------------------------------------------


def test_todays_snapshot_emits_none_of_it(mcp_module, tmp_path) -> None:
    """The committed snapshot has no saved-search route, so the served module
    has none of the tools, no steering sentence and no placeholder left over."""
    gen = _generator("_gen_saved_gate")
    snapshot = _snapshot()
    assert not any(p.startswith("/filings/search/saved/") for p in snapshot["paths"])
    assert gen._saved_search_ready(snapshot["paths"]) is False
    served = set(mcp_module.mcp._tool_manager._tools)
    assert TOOLS.isdisjoint(served)
    description = mcp_module.mcp._tool_manager._tools["filings_search"].description
    assert "filings_search_save" not in description
    text = Path(mcp_module.__file__).read_text(encoding="utf-8")
    for marker in (
        "__SAVED_SEARCH_STEER__",
        "_api_send_unreplayed",
        "/filings/search/saved/",
    ):
        assert marker not in text, marker
    # And an in-process render of the snapshot is the same module, byte for byte.
    assert _render(tmp_path, snapshot) == text


@pytest.mark.parametrize("full_surface", [False, True])
def test_the_routes_emit_the_four_tools_and_no_generic_twin(
    tmp_path, full_surface
) -> None:
    source = _render(
        tmp_path, _with_saved_search(_snapshot()), full_surface=full_surface
    )
    names = _tools_in(source)
    assert TOOLS <= set(names)
    # One definition each: the generic list twin would take the same name.
    for name in TOOLS:
        assert names.count(name) == 1, name
    for twin in ("filings_search_saved_create", "filings_search_saved_new_create"):
        assert twin not in names
    # retrieve and preview are pruned from the default surface only.
    for twin in (
        "filings_search_saved_retrieve",
        "filings_search_saved_preview_create",
    ):
        assert (twin in names) is full_surface, twin
    assert "__SAVED_SEARCH_STEER__" not in source


def test_every_saved_search_operation_is_denylisted_by_its_real_operation_id() -> None:
    """A denylist fails open: a misspelt key would ship the generic tool. Keys
    are compared with the operationIds of the schema that carries the routes."""
    gen = _generator("_gen_saved_keys")
    extra = json.loads(FIXTURE.read_text(encoding="utf-8"))
    op_ids = {
        gen.snake_case(op["operationId"])
        for item in extra["paths"].values()
        for method, op in item.items()
        if method in ("get", "post")
    }
    assert op_ids == {
        "filings_search_saved_list",
        "filings_search_saved_create",
        "filings_search_saved_retrieve",
        "filings_search_saved_new_create",
        "filings_search_saved_preview_create",
    }
    denied = gen._REPLACED_BY_SYNTHETIC | gen._PRUNED_EXCLUDE
    assert op_ids <= denied
    ours = {k for k in denied if k.startswith("filings_search_saved_")}
    assert ours == op_ids, "a key here that names no operation is a typo"


@pytest.mark.parametrize("drop", ["delete", "repeat", "list", "pull"])
def test_a_partial_saved_search_api_emits_nothing(tmp_path, drop) -> None:
    """Half the routes (or a pull that does not know repeat_last_pull, where a
    'repeat' would run a real pull and record its hits) emit no tool."""
    schema = _with_saved_search(_snapshot())
    if drop == "delete":
        del schema["paths"]["/filings/search/saved/{id}/"]["delete"]
    elif drop == "list":
        del schema["paths"]["/filings/search/saved/"]["get"]
    elif drop == "pull":
        del schema["paths"]["/filings/search/saved/{id}/new/"]
    else:
        pull = schema["paths"]["/filings/search/saved/{id}/new/"]["post"]
        pull["parameters"] = [
            p for p in pull["parameters"] if p["name"] != "repeat_last_pull"
        ]
    names = set(_tools_in(_render(tmp_path, schema)))
    assert TOOLS.isdisjoint(names)


def test_annotations(saved_source) -> None:
    expected = {
        "filings_search_save": (False, False, False),
        "filings_search_new": (False, False, False),
        "filings_search_saved_list": (True, False, True),
        "filings_search_saved_delete": (False, True, True),
    }
    for node in ast.walk(ast.parse(saved_source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in expected:
            call = next(d for d in node.decorator_list if "mcp.tool" in ast.unparse(d))
            ann = next(k.value for k in call.keywords if k.arg == "annotations")
            hints = {
                k.arg: ast.literal_eval(k.value)
                for k in ann.keywords
                if k.arg != "title"
            }
            got = (
                hints["readOnlyHint"],
                hints["destructiveHint"],
                hints["idempotentHint"],
            )
            assert got == expected.pop(node.name), node.name
    assert not expected


def test_filings_search_steers_to_save_and_pull_only_when_served(m) -> None:
    description = " ".join(
        m.mcp._tool_manager._tools["filings_search"].description.split()
    )
    assert (
        "To check a search repeatedly for new filings, save it with filings_search_save "
        "and pull with filings_search_new instead of re-running it with a moving "
        "release_datetime_from: that misses filings released earlier but added to "
        "FinancialFilings later."
    ) in description


def test_customer_copy_names_the_platform(m) -> None:
    for name in TOOLS:
        description = m.mcp._tool_manager._tools[name].description
        assert (
            "FinancialReports" not in description
            and "financialreports" not in description
        )
    schema = m.mcp._tool_manager._tools["filings_search_save"].parameters
    assert "ordering" not in schema["properties"] and "q" not in schema["properties"]
    assert {"queries", "name", "companies", "max_hits_per_pull"} <= set(
        schema["properties"]
    )


# --- save ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
        ({}, "at least one non-empty string"),
        ({"queries": ["a", "b", "c", "d", "e", "f"]}, "at most 5 queries"),
        ({"queries": ["x"], "companies": list(range(1, 52))}, "at most 50 company ids"),
        ({"queries": ["x"], "companies": "12,abc"}, "internal company ids"),
        (
            {"queries": ["x"], "ordering": "-release_datetime"},
            "ordering cannot be saved",
        ),
        ({"queries": ["x"], "group_by": "company"}, "group_by cannot be saved"),
        ({"queries": ["x"], "page": 2}, "page cannot be saved"),
        ({"queries": ["x"], "page_size": 50}, "use max_hits_per_pull"),
        (
            {"queries": ["x"], "added_to_platform_from": "2026-01-01T00:00:00Z"},
            "added_to_platform_from cannot be saved",
        ),
        (
            {"queries": ["x"], "include_predecessors": True},
            "include_predecessors needs company",
        ),
        ({"queries": ["x"], "max_hits_per_pull": 0}, "max_hits_per_pull must be"),
        ({"queries": ["x"], "max_hits_per_pull": 201}, "max_hits_per_pull must be"),
        ({"queries": ["x"], "name": "n" * 201}, "name must be at most 200"),
    ],
)
async def test_save_refuses_bad_input_before_any_request(
    m, respx_router, kwargs, says
) -> None:
    route = respx_router.post(SAVED).mock(
        return_value=httpx.Response(201, json={"id": 7})
    )
    out = await _fn(m, "filings_search_save")(**kwargs)
    assert not route.called
    assert out.startswith("Invalid argument:") and says in out, out


@pytest.mark.asyncio
async def test_save_sends_the_search_as_params_with_q_a_list_and_no_webhook(
    m, respx_router
) -> None:
    route = respx_router.post(SAVED).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 7,
                "name": "going concern; Unternehmensfortführung",
                "params": {
                    "q": ["going concern", "Unternehmensfortführung"],
                    "companies": "12,345",
                    "countries": "DE,FR",
                    "include_predecessors": "true",
                },
                "webhook": None,
                "is_active": True,
                "max_hits_per_run": 20,
            },
        )
    )
    out = await _fn(m, "filings_search_save")(
        queries=["going concern", "Unternehmensfortführung"],
        companies=[12, 345, 12],
        countries="DE,FR",
        include_predecessors=True,
    )
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "name": "going concern; Unternehmensfortführung",
        "params": {
            "q": ["going concern", "Unternehmensfortführung"],
            "companies": "12,345",
            "include_predecessors": True,
            "countries": "DE,FR",
        },
        "max_hits_per_run": 20,
    }
    assert "webhook" not in body
    assert "Saved search 7" in out
    assert "filings_search_new(saved_search_id=7)" in out
    assert "for the filings that already match, run filings_search" in out
    assert "up to 20 filings per pull" in out


@pytest.mark.asyncio
async def test_save_takes_filings_search_aliases(m, respx_router) -> None:
    route = respx_router.post(SAVED).mock(
        return_value=httpx.Response(201, json={"id": 8})
    )
    await _fn(m, "filings_search_save")(
        q="buyback", company_id=42, name="  My  watch ", max_hits_per_pull=5
    )
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "name": "My watch",
        "params": {"q": ["buyback"], "company": 42},
        "max_hits_per_run": 5,
    }


@pytest.mark.asyncio
async def test_save_404_means_not_available_yet(m, respx_router) -> None:
    respx_router.post(SAVED).mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_save")(queries=["x"])
    assert (
        "Saved searches are not available on this FinancialFilings account yet"
        in str(exc.value)
    )
    assert exc.value.error_kind == "saved_searches_unavailable"


@pytest.mark.asyncio
async def test_save_at_the_active_limit_points_at_list_and_delete(
    m, respx_router
) -> None:
    respx_router.post(SAVED).mock(
        return_value=httpx.Response(
            400,
            json={
                "is_active": [
                    "At most 20 saved searches can be active per account. Pause or delete one first."
                ]
            },
        )
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_save")(queries=["x"])
    text = str(exc.value)
    assert "At most 20 saved searches" in text
    assert "filings_search_saved_list" in text and "filings_search_saved_delete" in text


@pytest.mark.asyncio
async def test_save_forwards_the_apis_refusal(m, respx_router) -> None:
    respx_router.post(SAVED).mock(
        return_value=httpx.Response(
            400,
            json={
                "params": [
                    "`types`: Select a valid choice. ZZ is not one of the available choices."
                ]
            },
        )
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_save")(queries=["x"], types="ZZ")
    assert "ZZ is not one of the available choices" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "502"])
async def test_save_is_never_replayed(m, respx_router, failure) -> None:
    """A replay after a lost answer would save the search twice."""
    if failure == "timeout":
        route = respx_router.post(SAVED).mock(side_effect=httpx.ReadTimeout("slow"))
    else:
        route = respx_router.post(SAVED).mock(return_value=httpx.Response(502))
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_save")(queries=["x"])
    assert route.call_count == 1
    if failure == "timeout":
        assert "check filings_search_saved_list before saving it again" in str(
            exc.value
        )


# --- pull ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_renders_each_hit_as_filings_search_does_and_says_it_is_consumed(
    m, respx_router
) -> None:
    route = respx_router.post(PULL).mock(
        return_value=httpx.Response(200, json=_pull([_hit(1, match=LITERAL), _hit(2)]))
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert (
        route.called and "repeat_last_pull" not in route.calls.last.request.url.params
    )
    assert route.calls.last.request.content == b""
    lines = out.splitlines()
    assert lines[0].startswith('2 new filing(s) for saved search 7 "Going concern"')
    assert "between 2026-11-22T09:00:00Z and 2026-11-23T10:00:00Z" in lines[0]
    assert "will not return them again" in lines[0]
    assert (
        "- filing 1 | Company 1 (company 901) | AR | released 2019-04-02 | "
        "added 2026-11-23 | Report 1"
    ) in lines
    assert "    @offset 1200: material uncertainty ... going concern ..." in lines
    assert "    matched; no snippet was computed for this filing" in lines
    assert "only the first 10" not in out
    assert out.endswith("(6 credits, 12 if any filing above is a premium type).")
    assert "more new filing" not in out and "stopped before" not in out


@pytest.mark.asyncio
async def test_pull_with_more_capped_and_an_early_stop(m, respx_router) -> None:
    respx_router.post(PULL).mock(
        return_value=httpx.Response(
            200, json=_pull([_hit(1)], more=31, capped=True, scan_complete=False)
        )
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "At least 31 more new filing(s) are waiting" in out
    assert "call filings_search_new(saved_search_id=7) again now" in out
    assert "some new filings may never be returned" in out
    assert "it may be incomplete: more new filings may exist. Pull again later." in out
    assert "Nothing was recorded" not in out  # this pull did return (record) a hit
    assert "Billed as one filings_search page" in out


@pytest.mark.asyncio
async def test_an_empty_pull_is_not_billed(m, respx_router) -> None:
    respx_router.post(PULL).mock(return_value=httpx.Response(200, json=_pull([])))
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert out.startswith(
        'No new filings for saved search 7 "Going concern" since the previous pull'
    )
    assert out.endswith("Nothing was billed.")


@pytest.mark.asyncio
async def test_an_empty_early_stopped_pull_is_not_an_absence(m, respx_router) -> None:
    respx_router.post(PULL).mock(
        return_value=httpx.Response(200, json=_pull([], scan_complete=False))
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "No new filings" not in out
    assert "This is NOT an absence" in out
    assert "Nothing was recorded" in out and "Pull again later" in out
    assert out.endswith("Nothing was billed.")


@pytest.mark.asyncio
async def test_an_empty_capped_pull_does_not_claim_there_is_nothing_new(
    m, respx_router
) -> None:
    respx_router.post(PULL).mock(
        return_value=httpx.Response(200, json=_pull([], capped=True))
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "No new filings" not in out
    assert "new filings may exist beyond those" in out and "Narrow it" in out


@pytest.mark.asyncio
async def test_no_hit_is_dropped_for_length(m, respx_router) -> None:
    """A pulled hit is never returned again, so the size limit trims snippets,
    never hits."""
    long_match = {
        "query": "x",
        "total_hits": 5,
        "hits": [{"offset": i, "snippet": "s" * 2000} for i in range(5)],
    }
    hits = [_hit(i, match=long_match) for i in range(1, 201)]
    respx_router.post(PULL).mock(return_value=httpx.Response(200, json=_pull(hits)))
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert len(out) <= m._MAX_RESULT_CHARS
    for i in range(1, 201):
        assert f"- filing {i} | " in out, i
    assert "snippets left out to keep the result inside its size limit" in out
    assert "@offset" in out  # the first hits still carry theirs


@pytest.mark.asyncio
async def test_pull_404_and_409_are_explained(m, respx_router) -> None:
    route = respx_router.post(PULL)
    route.mock(return_value=httpx.Response(404, json={"detail": "Not found."}))
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "No saved search 7 on this account" in str(exc.value)
    assert "not available on this account yet" in str(exc.value)

    route.mock(
        return_value=httpx.Response(
            409,
            json={
                "detail": "This saved search delivers its new hits to a webhook.",
                "type": "delivers_to_webhook",
            },
        )
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "delivers its new filings to a webhook" in str(exc.value)
    assert exc.value.error_kind == "delivers_to_webhook"

    route.mock(
        return_value=httpx.Response(
            409,
            json={
                "detail": "This saved search is paused.",
                "type": "saved_search_paused",
            },
        )
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert "Saved search 7 is paused" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "504"])
async def test_a_pull_that_may_have_run_is_not_replayed_and_points_at_the_repeat(
    m, respx_router, failure
) -> None:
    """A replay would return the NEXT hits and lose the first answer's for good."""
    if failure == "timeout":
        route = respx_router.post(PULL).mock(side_effect=httpx.ReadTimeout("slow"))
    else:
        route = respx_router.post(PULL).mock(return_value=httpx.Response(504))
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert route.call_count == 1
    assert "filings_search_new(saved_search_id=7, repeat_last_pull=true)" in str(
        exc.value
    )


@pytest.mark.asyncio
async def test_a_busy_search_is_retried_once_because_it_never_ran(
    m, respx_router
) -> None:
    route = respx_router.post(PULL).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"detail": "Too many searches running.", "type": "search_busy"},
            ),
            httpx.Response(200, json=_pull([_hit(1)])),
        ]
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7)
    assert route.call_count == 2
    assert "1 new filing(s)" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -3, True])
async def test_pull_refuses_a_bad_id(m, respx_router, bad) -> None:
    route = respx_router.post(PULL).mock(
        return_value=httpx.Response(200, json=_pull([]))
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=bad)
    assert not route.called and "saved_search_id must be a positive integer" in out


# --- repeat_last_pull -----------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_returns_the_last_pull_again(m, respx_router) -> None:
    route = respx_router.post(PULL).mock(
        return_value=httpx.Response(
            200,
            json={
                "saved_search": {"id": "7", "name": "Going concern"},
                "hits": [_hit(1), _hit(2)],
                "pulled_at": "2026-11-23T08:00:00Z",
            },
        )
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7, repeat_last_pull=True)
    assert route.calls.last.request.url.params["repeat_last_pull"] == "true"
    assert out.startswith("Repeat of the pull at 2026-11-23T08:00:00Z")
    assert "Nothing was searched, recorded or billed" in out
    assert "- filing 1 | " in out and "- filing 2 | " in out
    assert "matched;" not in out  # no snippet lines on a repeat


@pytest.mark.asyncio
async def test_repeat_with_nothing_to_repeat(m, respx_router) -> None:
    respx_router.post(PULL).mock(
        return_value=httpx.Response(
            200,
            json={
                "saved_search": {"id": "7", "name": "Going concern"},
                "hits": [],
                "pulled_at": None,
            },
        )
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7, repeat_last_pull=True)
    assert "has returned filings yet, so there is nothing to repeat" in out


@pytest.mark.asyncio
async def test_a_repeat_the_api_ran_as_a_pull_says_so(m, respx_router) -> None:
    """An API that ignored the flag ran a REAL pull: its hits are recorded."""
    respx_router.post(PULL).mock(
        return_value=httpx.Response(200, json=_pull([_hit(1)]))
    )
    out = await _fn(m, "filings_search_new")(saved_search_id=7, repeat_last_pull=True)
    assert out.startswith(
        "The FinancialFilings API ran a new pull instead of repeating"
    )
    assert "Billed as one filings_search page" in out


# --- list and delete ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_renders_each_search(m, respx_router) -> None:
    route = respx_router.get(SAVED).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": 7,
                        "name": "Going concern",
                        "params": {"q": ["going concern"], "countries": "DE"},
                        "webhook": None,
                        "is_active": True,
                        "max_hits_per_run": 20,
                        "cursor": "2026-11-23T10:00:00Z",
                        "last_run_at": "2026-11-23T10:00:00Z",
                        "last_status": "delivered",
                        "created_at": "2026-11-20T10:00:00Z",
                        "updated_at": "2026-11-20T10:00:00Z",
                    },
                    {
                        "id": 8,
                        "name": "Hooked",
                        "params": {"q": ["buyback"]},
                        "webhook": 3,
                        "is_active": True,
                        "max_hits_per_run": 50,
                        "cursor": "2026-11-20T10:00:00Z",
                        "last_run_at": None,
                        "last_status": "",
                        "created_at": "2026-11-20T10:00:00Z",
                        "updated_at": "2026-11-20T10:00:00Z",
                    },
                ],
            },
        )
    )
    out = await _fn(m, "filings_search_saved_list")()
    assert route.calls.last.request.url.params["page_size"] == "20"
    assert "- saved search 7 | Going concern | queries" in out
    assert "filters: countries=DE" in out and "up to 20 per pull" in out
    assert "active, pulled with filings_search_new" in out
    assert "last ran 2026-11-23T10:00:00Z (delivered)" in out
    assert (
        "delivers to a webhook (cannot be pulled here)" in out
        and "not pulled yet" in out
    )


@pytest.mark.asyncio
async def test_list_404_means_not_available_yet(m, respx_router) -> None:
    respx_router.get(SAVED).mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_saved_list")()
    assert "not available on this FinancialFilings account yet" in str(exc.value)


@pytest.mark.asyncio
async def test_list_404_past_the_last_page_vs_feature_off(m, respx_router) -> None:
    """A later-page 404 is "past the end" only when page 1 answers (SPECHT on #224)."""

    def pages(first_status):
        def answer(request):
            if request.url.params["page"] == "1":
                if first_status == 200:
                    return httpx.Response(
                        200, json={"count": 0, "next": None, "previous": None, "results": []}
                    )
                return httpx.Response(first_status, json={"detail": "Not found."})
            return httpx.Response(404, json={"detail": "Invalid page."})

        return answer

    route = respx_router.get(SAVED).mock(side_effect=pages(200))
    out = await _fn(m, "filings_search_saved_list")(page=3)
    assert out.startswith("No saved searches on page 3.")
    assert [c.request.url.params["page"] for c in route.calls] == ["3", "1"]
    route.mock(side_effect=pages(404))
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_saved_list")(page=2)
    assert "not available on this FinancialFilings account yet" in str(exc.value)


@pytest.mark.asyncio
async def test_delete_sends_delete(m, respx_router) -> None:
    route = respx_router.delete(ONE).mock(return_value=httpx.Response(204))
    out = await _fn(m, "filings_search_saved_delete")(saved_search_id=7)
    assert route.called and route.calls.last.request.method == "DELETE"
    assert out == "Deleted saved search 7. Nothing was billed."


@pytest.mark.asyncio
async def test_delete_404_and_no_replay(m, respx_router) -> None:
    route = respx_router.delete(ONE)
    route.mock(return_value=httpx.Response(404, json={"detail": "Not found."}))
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_saved_delete")(saved_search_id=7)
    assert "No saved search 7 on this account" in str(exc.value)
    route.mock(return_value=httpx.Response(502))
    calls = route.call_count
    with pytest.raises(m.UpstreamHTTPError):
        await _fn(m, "filings_search_saved_delete")(saved_search_id=7)
    assert route.call_count == calls + 1


# --- through FastMCP's own validation -------------------------------------------


async def _call(module, name, args):
    from fastmcp import Client

    async with Client(module.mcp) as client:
        result = await client.call_tool(name, args)
    return result.content[0].text


@pytest.mark.asyncio
async def test_save_through_the_mcp_call_path(m, respx_router) -> None:
    """The signature, not only the body: a null for an omitted argument, a call
    copied from filings_search (page=1, view), and a refused argument."""
    route = respx_router.post(SAVED).mock(
        return_value=httpx.Response(201, json={"id": 7})
    )
    await _call(m, "filings_search_save", {"queries": ["x"], "max_hits_per_pull": None})
    assert json.loads(route.calls.last.request.content)["max_hits_per_run"] == 20
    await _call(m, "filings_search_save", {"queries": ["x"], "page": 1, "view": "full"})
    assert route.call_count == 2
    out = await _call(m, "filings_search_save", {"queries": ["x"], "ordering": "-id"})
    assert "ordering cannot be saved" in out and route.call_count == 2


@pytest.mark.asyncio
async def test_a_pull_the_index_refused_is_not_replayed_and_needs_no_repeat(
    m, respx_router
) -> None:
    """503 search_unavailable is raised before the search runs: nothing was
    recorded, so no repeat advice (it would return an older batch)."""
    route = respx_router.post(PULL).mock(
        return_value=httpx.Response(
            503, json={"detail": "Search unavailable.", "type": "search_unavailable"}
        )
    )
    with pytest.raises(m.UpstreamHTTPError) as exc:
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert route.call_count == 1
    assert "repeat_last_pull" not in str(exc.value)


@pytest.mark.asyncio
async def test_an_account_429_on_a_pull_is_not_retried(m, respx_router) -> None:
    route = respx_router.post(PULL).mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "86400"},
            json={"detail": "Monthly quota reached.", "type": "quota_limit_exceeded"},
        )
    )
    with pytest.raises(m.UpstreamHTTPError):
        await _fn(m, "filings_search_new")(saved_search_id=7)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_an_empty_pull_the_api_ran_instead_of_a_repeat_says_so(
    m, respx_router
) -> None:
    respx_router.post(PULL).mock(return_value=httpx.Response(200, json=_pull([])))
    out = await _fn(m, "filings_search_new")(saved_search_id=7, repeat_last_pull=True)
    assert out.startswith(
        "The FinancialFilings API ran a new pull instead of repeating"
    )
    assert out.endswith("Nothing was billed.")
