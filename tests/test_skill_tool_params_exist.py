"""Every tool and parameter the skills name must exist on the served surface.

⛔ WHY: a skill that tells the model to call `companies_financials_retrieve?company=<id>`
is worse than a skill that says nothing. The real parameter is `id`, the call fails
or silently drops the filter, and the model has been actively misdirected by the
artifact whose whole purpose is directing it well.

Both of the errors this test now pins were real and were written in #208:

  * `companies_financials_retrieve?company=` (the parameter is `id`)
  * `filings_markdown_search?...&q=` (the parameter is `query`)

They were caught by a `claude plugin eval` run, and only because one mock happened
to carry an `expect:` guard on the argument type: the run aborted with
"company = (missing) is not a number". That is a lucky catch, not a gate. An eval
costs money and minutes and needs a mock to guard the exact field; this test is
free, runs in the unit suite, and checks every field in every skill.

Scope: the `tool?param=value` form, which is how the skills write example calls.
Prose that merely mentions a parameter in backticks is not checked, because the
same word is often a response field rather than an argument.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_ROOT = REPO_ROOT / "plugins" / "financialfilings" / "skills"
GENERATED = REPO_ROOT / "src" / "financial_reports_mcp.py"

#: `tool_name?param=` and the `&param=` that follow it on the same token run.
_CALL = re.compile(r"\b([a-z][a-z0-9_]*)\?([a-z0-9_]+=[^`\s]*)")


def _served() -> dict[str, set[str]]:
    """{tool name: its parameter names} from the rendered module."""
    tree = ast.parse(GENERATED.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any("mcp.tool" in ast.unparse(d) for d in node.decorator_list):
            continue
        args = node.args
        out[node.name] = {
            a.arg for a in [*args.args, *args.kwonlyargs] if a.arg != "self"
        }
    return out


def _calls() -> list[tuple[str, str, str]]:
    """(skill file, tool, param) for every `tool?param=` the skills write."""
    found = []
    for path in sorted(SKILL_ROOT.rglob("*.md")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for tool, query in _CALL.findall(path.read_text(encoding="utf-8")):
            for pair in query.split("&"):
                name = pair.split("=", 1)[0]
                if name:
                    found.append((rel, tool, name))
    return found


def test_the_extractor_finds_the_calls_the_skills_actually_contain() -> None:
    """Positive control, first. Every assertion below is of the form "everything
    found is valid", which an extractor that finds NOTHING satisfies perfectly.
    This is the shape of check that passes while measuring nothing, so pin the
    population before trusting the verdict."""
    calls = _calls()
    assert len(calls) >= 12, f"expected a dozen or more example calls, found {len(calls)}"
    tools = {tool for _f, tool, _p in calls}
    assert {"companies_list", "filings_list"} <= tools, (
        f"the extractor missed the most common calls; it found {sorted(tools)}"
    )


@pytest.mark.parametrize("relpath,tool,param", _calls(), ids=lambda v: str(v))
def test_every_named_tool_and_parameter_exists(relpath: str, tool: str, param: str) -> None:
    served = _served()
    assert tool in served, (
        f"{relpath} writes `{tool}?...` and no such tool is served. "
        f"Closest served names: {sorted(n for n in served if n.startswith(tool[:8]))}"
    )
    assert param in served[tool], (
        f"{relpath} passes `{param}` to `{tool}`, which has no such parameter. "
        f"A skill that names a parameter the tool does not take misdirects the "
        f"model. Served parameters: {sorted(served[tool])}"
    )
