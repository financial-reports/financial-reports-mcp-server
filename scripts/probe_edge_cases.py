#!/usr/bin/env python3
"""Adversarial edge-case probe for the live tool surface.

Companion to scripts/measure_surface.py. That one asks "do the tools work on the
happy path"; this one asks "where do they fail, and do they fail LOUDLY".

The distinction matters because the expensive defects in this repo have all been
QUIET ones: a parameter silently dropped, an error returned as a successful
result, a filter value that yields count=0 instead of a complaint. A tool that
raises is cheap — the model sees it and adapts. A tool that returns a plausible
wrong answer is what reaches a user.

Needs a real API key (same setup as measure_surface.py), so it is NOT in CI.
Run it before a deploy that changes the tool surface or its guidance.

    python scripts/probe_edge_cases.py

Outcome column:
  OK              returned normally (read DETAIL — "normally" may still be wrong)
  TOOLERROR       raised; the model would see it. Usually the DESIRABLE outcome here.
  ERR-AS-SUCCESS  an upstream error came back is_error=false with the error as
                  body text. Flagged, because a client branching on isError
                  treats it as data. See issue #104.
"""
import asyncio
import json

from fastmcp import Client

URL="http://127.0.0.1:8000/mcp"

CASES = [
 # (id, tool, args, what we're probing for)
 ("bad-enum-fiscal",   "companies_financials_retrieve", {"id":100,"fiscal_period":"Q5"}, "invalid enum -> loud or silently ignored?"),
 ("bad-enum-stmt",     "companies_financials_retrieve", {"id":100,"statement_type":"XX"}, "invalid enum"),
 ("unknown-lineitem",  "companies_financials_retrieve", {"id":100,"line_items":"not_a_real_kpi"}, "docs say 400"),
 ("future-year",       "companies_financials_retrieve", {"id":100,"fiscal_year":2099}, "empty vs error"),
 ("nonexistent-co",    "companies_retrieve", {"id":999999999}, "404 path"),
 ("negative-id",       "companies_retrieve", {"id":-1}, "negative id"),
 ("zero-id",           "companies_retrieve", {"id":0}, "zero id"),
 ("bad-isin",          "isins_retrieve", {"code":"XX0000000000"}, "unknown ISIN -> 404"),
 ("isin-wrong-len",    "isins_retrieve", {"code":"SHORT"}, "malformed ISIN"),
 ("isin-injection",    "isins_retrieve", {"code":"../../etc/passwd"}, "path traversal in a path param"),
 ("pagesize-huge",     "filings_list", {"company":100,"page_size":100000}, "cap enforced?"),
 ("pagesize-zero",     "filings_list", {"company":100,"page_size":0}, "zero page size"),
 ("page-way-past-end", "filings_list", {"company":100,"page":99999}, "past last page"),
 ("bad-ordering",      "filings_list", {"company":100,"ordering":"-nonsense_field"}, "silently dropped (known)"),
 ("date-only-on-dt",   "filings_list", {"company":100,"release_datetime_from":"2026-01-01"}, "date on a date-time param"),
 ("garbage-date",      "filings_list", {"company":100,"release_datetime_from":"not-a-date"}, "malformed date"),
 ("unknown-type",      "filings_list", {"company":100,"type":"NOT-A-TYPE"}, "unknown filing type"),
 ("country-singular",  "companies_list", {"countries":"DE","page_size":2}, "control: valid"),
 ("md-offset-past-end","filings_markdown_retrieve", {"filing_id":33041841,"offset":99999999,"limit":100}, "offset past EOF"),
 ("md-limit-over-cap", "filings_markdown_retrieve", {"filing_id":33041841,"offset":0,"limit":999999}, "per-call cap 150k"),
 ("md-negative-offset","filings_markdown_retrieve", {"filing_id":33041841,"offset":-5,"limit":100}, "negative offset"),
 ("md-missing-filing", "filings_markdown_retrieve", {"filing_id":999999999,"limit":100}, "missing filing"),
 ("search-empty",      "filings_markdown_search", {"filing_id":33041841,"query":""}, "empty query"),
 ("search-regex",      "filings_markdown_search", {"filing_id":33041841,"query":".*"}, "regex metachars"),
 ("ambiguous-search",  "companies_list", {"search":"Apple","page_size":5}, "ambiguity surfaced?"),
]

async def taxonomy_drift(c):
    """The built-in taxonomy reference vs what filing_types_list actually serves.

    These drift silently: the reference is a hand-maintained table inside the
    generator, the live list comes from the API. A code advertised but not
    served is a wrong answer waiting to happen — a client engineer comparing
    the two spots it immediately. Not CI-able (needs a key), so it lives here.
    """
    import re
    r = await c.call_tool("get_fr_filing_type_taxonomy", {})
    ref = "".join(getattr(b, "text", "") or "" for b in (r.content or []))
    ref_codes = []
    for line in ref.splitlines():
        if line.startswith("|") and not line.startswith("|---") and "| Code |" not in line:
            cells = [x.strip() for x in line.strip("|").split("|")]
            if cells and cells[0]:
                ref_codes.append(cells[0])
    live = set()
    for page in (1, 2, 3):
        try:
            rr = await c.call_tool("filing_types_list", {"page": page})
        except Exception:
            break
        txt = "".join(getattr(b, "text", "") or "" for b in (rr.content or []))
        found = re.findall(r'"code"\s*:\s*"([^"]+)"', txt)
        if not found:
            break
        live |= set(found)
    advertised_only = [x for x in ref_codes if x not in live]
    served_only = sorted(live - set(ref_codes))
    print("\n=== taxonomy drift ===")
    print(f"  reference table: {len(ref_codes)} codes   live list: {len(live)} codes")
    print(f"  advertised but NOT served: {advertised_only or 'none'}")
    print(f"  served but NOT advertised: {served_only or 'none'}")
    return advertised_only, served_only


async def main():
    async with Client(URL) as c:
        print(f"{'CASE':<20} {'OUTCOME':<16} {'DETAIL'}")
        print("-"*118)
        findings=[]
        for cid, tool, args, why in CASES:
            try:
                r = await c.call_tool(tool, args)
                txt = "".join(getattr(b,"text","") or "" for b in (r.content or []))
                st = getattr(r,"structured_content",None) or getattr(r,"data",None)
                if txt.lstrip().startswith("Error "):
                    out, det = "ERR-AS-SUCCESS", txt.strip()[:74]
                    findings.append((cid,"403/err returned as SUCCESS result"))
                else:
                    n = st.get("count") if isinstance(st,dict) and "count" in st else (
                        len(st.get("results",[])) if isinstance(st,dict) and "results" in st else None)
                    out = "OK"
                    det = f"count={n} " if n is not None else ""
                    det += (txt[:60].replace("\n"," ") if txt else json.dumps(st)[:60] if st else "<empty>")
            except Exception as e:
                msg=str(e)
                out = "TOOLERROR"
                det = msg.split("\n")[0][:74]
            print(f"{cid:<20} {out:<16} {det}")
        await taxonomy_drift(c)
        if findings:
            print("\nFLAGGED:")
            for f in findings:
                print("  ", f)

if __name__ == "__main__":
    asyncio.run(main())
