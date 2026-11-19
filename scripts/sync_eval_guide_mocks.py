#!/usr/bin/env python3
"""Regenerate the eval mocks for the three `get_fr_*` guide tools from the module.

⛔ WHY THIS SCRIPT EXISTS. The guide tools return long reference documents: the
filing-type code table, the ISIC hierarchy, the markdown fetch strategy. I first
wrote their eval mocks BY HAND, and invented their content:

  * a 4-digit ISIC class-name table. The real resource says the hierarchy
    endpoints are "NOT exposed as tools on this server, so there is no
    code-lookup call available".
  * a filing-type table calling `AR` an Annual Report and saying `10-K` is not a
    code. The real taxonomy has `10-K` = "Annual Report (US + 20-F)" and
    **`AR` = "Audit Report / Information"**.

⇒ A fixture that fabricates a guide tool's CONTENT is worse than one with the
wrong SHAPE. The wrong shape makes an eval fail; invented content makes it PASS
while teaching the agent a code that selects the wrong filings in production, and
it marks a correct agent wrong on the way. My `filings_list` mock labelled its
annual rows `AR`, so an agent following the real taxonomy would have filtered
`types=10-K`, got nothing, and been scored down for being right.

Run after any change to the guide resources:

    python scripts/sync_eval_guide_mocks.py

Reads the literals out of the GENERATED module with `ast` rather than importing
it, because importing reaches the network for Cognito OIDC discovery and fails
without it.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATED = ROOT / "src" / "financial_reports_mcp.py"
MOCKS = ROOT / "plugins" / "financialfilings" / "evals" / "mocks" / "financialfilings"

#: mock filename stem -> the resource function whose return literal is its body
PAIRS = {
    "get_fr_filing_type_taxonomy": "_resource_filing_types",
    "get_fr_industry_classification_isic": "_resource_industry",
    "get_fr_markdown_fetch_strategy": "_resource_markdown",
}

BANNER = (
    "<!-- GENERATED from the shipping module's `{res}` by\n"
    "     scripts/sync_eval_guide_mocks.py. Do NOT hand-write this file: the\n"
    "     first version was hand-written and invented this tool's content. -->\n"
)


def main() -> int:
    if not GENERATED.exists():
        print(f"{GENERATED} is absent; render it first", file=sys.stderr)
        return 1
    tree = ast.parse(GENERATED.read_text(encoding="utf-8"))
    written = 0
    for stem, res in PAIRS.items():
        node = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == res
            ),
            None,
        )
        if node is None:
            print(f"skip {stem}: no {res} in the module", file=sys.stderr)
            continue
        ret = next((n for n in ast.walk(node) if isinstance(n, ast.Return)), None)
        if ret is None or not isinstance(ret.value, ast.Constant) or not isinstance(
            ret.value.value, str
        ):
            print(
                f"skip {stem}: {res} does not return a plain string literal, so its "
                "body cannot be lifted without running it",
                file=sys.stderr,
            )
            continue
        target = MOCKS / f"{stem}.md"
        target.write_text(
            "---\ntype: fixed\n---\n"
            + BANNER.format(res=res)
            + ret.value.value.rstrip("\n")
            + "\n",
            encoding="utf-8",
        )
        print(f"{target.name} <- {res} ({len(ret.value.value)} chars)")
        written += 1
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
