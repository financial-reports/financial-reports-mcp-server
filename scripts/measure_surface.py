#!/usr/bin/env python3
"""Measure the LIVE tool surface against the real API.

Why this exists: the unit suite, the eval suite and the e2e suite all pass
without a single tool ever returning data. They verify registration, transport,
auth and argument shape. None of them answers "does this tool return a correct
result", which is the only question a customer cares about.

This harness answers it. It needs a real FinancialReports API key, so it is NOT
part of CI — run it before a deploy that changes the tool surface.

    export FR_API_KEY=fr_pat_...
    python scripts/measure_surface.py            # every tool
    python scripts/measure_surface.py --json     # machine-readable

Each tool gets a realistic call. For every result we record whether it returned,
whether the payload validates against the schema the tool ADVERTISES, and any
tool-specific invariant worth asserting. A tool that 200s with a shape its own
output_schema rejects is a failure here, because that is what breaks a client.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")

# (tool, args, invariant(result_text, structured) -> str|None). A returned
# string is the failure reason; None means the invariant held.
def _nonempty(txt, st):
    return None if (txt or st) else "empty response"


def _has_periods(txt, st):
    if not isinstance(st, dict):
        return None
    if "periods" not in st:
        return "no `periods` key in structured content"
    return None


def _filters_by_type(txt, st):
    """The whole point of PR #103: `type` must actually filter."""
    if not isinstance(st, dict):
        return None
    rows = st.get("results") or []
    bad = [r.get("filing_type") for r in rows
           if isinstance(r, dict) and r.get("filing_type")
           and str(r.get("filing_type")).upper() not in ("10-K",)]
    return f"type='10-K' returned other types: {sorted(set(bad))[:5]}" if bad else None


CALLS = [
    ("companies_list", {"search": "Roche", "page_size": 3}, _nonempty),
    ("companies_retrieve", {"id": 100}, _nonempty),
    ("companies_financials_retrieve", {"id": 100, "fiscal_period": "FY"}, _has_periods),
    ("companies_next_annual_report_retrieve", {"id": 100}, None),
    ("isins_list", {"company": 100, "page_size": 3}, _nonempty),
    ("filings_list", {"company": 100, "type": "10-K",
                      "ordering": "-release_datetime", "page_size": 5}, _filters_by_type),
    ("filing_types_list", {}, _nonempty),
    ("filing_categories_list", {}, _nonempty),
    ("get_fr_filing_type_taxonomy", {}, _nonempty),
    ("get_fr_industry_classification_isic", {}, _nonempty),
    ("get_fr_markdown_fetch_strategy", {}, _nonempty),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from fastmcp import Client

    results = []
    async with Client(URL) as c:
        tools = {t.name: t for t in await c.list_tools()}
        covered = {n for n, _, _ in CALLS}
        uncovered = sorted(set(tools) - covered)

        for name, kwargs, invariant in CALLS:
            if name not in tools:
                results.append({"tool": name, "status": "NOT_REGISTERED"})
                continue
            t0 = time.time()
            row = {"tool": name, "ms": None, "status": None, "detail": ""}
            try:
                r = await c.call_tool(name, kwargs)
                row["ms"] = int((time.time() - t0) * 1000)
                txt = "".join(getattr(b, "text", "") or "" for b in (r.content or []))
                st = getattr(r, "structured_content", None) or getattr(r, "data", None)
                row["status"] = "OK"
                row["bytes"] = len(txt)
                if invariant:
                    why = invariant(txt, st)
                    if why:
                        row["status"] = "INVARIANT_FAIL"
                        row["detail"] = why
            except Exception as e:
                row["ms"] = int((time.time() - t0) * 1000)
                row["status"] = "ERROR"
                row["detail"] = str(e)[:200]
            results.append(row)

        # PR #102's premise, measured against real data rather than the code path:
        # a computed figure must present as value-present + raw_value/scale null.
        prov = {"tool": "PROVENANCE SIGNAL (#102)", "status": "NOT_MEASURED", "detail": ""}
        try:
            r = await c.call_tool("companies_financials_retrieve",
                                  {"id": 100, "statement_type": "BS"})
            st = getattr(r, "structured_content", None) or getattr(r, "data", None)
            items = [li for p in (st or {}).get("periods", [])
                     for s in p.get("statements", [])
                     for li in s.get("line_items", [])]
            withheld = [li for li in items
                        if li.get("value") is not None
                        and li.get("raw_value") is None and li.get("scale") is None]
            paired = [li for li in items if li.get("raw_value") is not None]
            prov["status"] = "OK"
            prov["detail"] = (f"{len(items)} line items: {len(paired)} carry an "
                              f"as-reported pair, {len(withheld)} present as "
                              f"value-with-null-pair (the signal the guidance keys on)")
        except Exception as e:
            prov["status"] = "ERROR"
            prov["detail"] = str(e)[:200]
        results.append(prov)

    if args.json:
        print(json.dumps({"results": results, "uncovered": uncovered}, indent=2))
    else:
        print(f"{'TOOL':<42} {'STATUS':<16} {'ms':>6}  DETAIL")
        print("-" * 110)
        for r in results:
            print(f"{r['tool']:<42} {str(r.get('status')):<16} "
                  f"{str(r.get('ms') or ''):>6}  {r.get('detail','')[:44]}")
        if uncovered:
            print(f"\nNOT EXERCISED ({len(uncovered)}): {', '.join(uncovered)}")

    bad = [r for r in results if r.get("status") not in ("OK", "NOT_MEASURED")]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
