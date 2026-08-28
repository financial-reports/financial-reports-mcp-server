#!/usr/bin/env python3
"""Detect wrong-source-document contamination in companies_financials_retrieve.

Motivated by customer evaluation feedback (Aug 2026): core XBRL extraction is
accurate, but the system sometimes attaches the WRONG SOURCE DOCUMENT to a
(company, fiscal period) — an 11-K employee-benefit-plan filing instead of the
operating 10-K, a one-page filing notice instead of the annual report, or a
foreign subsidiary's accounts instead of the listed parent's.

The result is not a rounding difference. Volkswagen FY2024 returns revenue of
EUR 35,523,197 against an actual EUR 324.7bn - wrong by ~9,140x, with no error
and no warning.

`source_filing` is NULL for every statement when `sources_masked` is true, which
it was for 150/150 companies sampled on a standard key. A consumer therefore
CANNOT audit which document a number came from. These two detectors work from
the numbers alone, which is the only option available to a caller.

  A) CURRENCY MISMATCH - a statement whose currency differs from the company's
     MODAL reporting currency is almost certainly a different legal entity.
     High precision, unaffected by growth rate.
     Reference case: Rolls-Royce Holdings PLC (GBP parent) returns EUR figures
     from its German subsidiary for 7 of 11 years.

  B) SANDWICHED MAGNITUDE - a year >20x smaller than BOTH neighbouring years.
     The "both neighbours" condition is load-bearing: a plain median test flags
     genuine hypergrowth (Tesla 2011/2012 are real pre-ramp revenues, not bugs).
     Reference case: Volkswagen FY2024.

Validated before use, per repo practice: VW flags (positive control)
Apple,
Microsoft, Amazon, Alphabet, NVIDIA, J&J all come back clean (negative controls,
matching the customer evaluation's "extraction is strong" finding).

Needs a real API key. NOT in CI - it is a data-quality probe, not a unit test.

    python scripts/probe_financials_contamination.py 400
"""
import asyncio
import collections
import sys

from fastmcp import Client

URL = "http://127.0.0.1:8000/mcp"
# Two orthogonal detectors for wrong-source-document contamination.
#  A) CURRENCY MISMATCH — a statement whose currency differs from the company's
#     MODAL reporting currency is almost certainly a different legal entity
#     (the Rolls-Royce case: German subsidiary filings under a UK parent).
#     High precision; unaffected by growth.
#  B) SANDWICHED MAGNITUDE — a year >20x smaller than BOTH neighbours is a
#     wrong document (stub notice / 11-K benefit plan). The "both neighbours"
#     condition is what removes the hypergrowth false positive that a plain
#     median test produces for e.g. Tesla 2011.
RATIO=20.0
async def series(c,cid):
    try:
        r=await c.call_tool("companies_financials_retrieve",{"id":cid,"fiscal_period":"FY","line_items":"revenue"})
        st=getattr(r,"structured_content",None) or getattr(r,"data",None)
    except Exception:
        return []
    out=[]
    for p in (st or {}).get("periods",[]):
        for s in p.get("statements",[]):
            for li in s.get("line_items",[]):
                if li.get("code")=="revenue" and li.get("value") is not None:
                    try:
                        out.append((p.get("fiscal_year"),float(li["value"]),(s.get("currency") or {}).get("code")))
                    except Exception:
                        pass
    return sorted(x for x in out if x[0])
def detect(rows):
    f={}
    ccys=[c for _,_,c in rows if c]
    if ccys:
        modal=collections.Counter(ccys).most_common(1)[0][0]
        odd=[(y,c) for y,_,c in rows if c and c!=modal]
        if odd:
            f["currency"]=(modal,odd)
    d={y:v for y,v,_ in rows}
    yrs=sorted(d)
    sand=[]
    for i,y in enumerate(yrs):
        if i==0 or i==len(yrs)-1:
            continue
        p,n,v=d[yrs[i-1]],d[yrs[i+1]],d[y]
        if v>0 and p>0 and n>0 and p/v>RATIO and n/v>RATIO:
            sand.append((y,v,p,n))
    if sand:
        f["magnitude"]=sand
    return f
async def main():
    limit=int(sys.argv[1]) if len(sys.argv)>1 else 400
    async with Client(URL) as c:
        ids=[]
        for page in range(1,12):
            r=await c.call_tool("companies_list",{"countries":"DE,GB,FR,NL,CH,SE,IT,ES,US","page_size":100,"page":page})
            st=getattr(r,"structured_content",None) or getattr(r,"data",None)
            res=(st or {}).get("results",[])
            if not res:
                break
            ids+=[x["id"] for x in res]
            if len(ids)>=limit:
                break
        ids=ids[:limit]
        meas=0
        cur_hits=[]
        mag_hits=[]
        for cid in ids:
            rows=await series(c,cid)
            if len(rows)<3:
                continue
            meas+=1
            f=detect(rows)
            if "currency" in f:
                cur_hits.append((cid,f["currency"]))
            if "magnitude" in f:
                mag_hits.append((cid,f["magnitude"]))
        print(f"companies queried      : {len(ids)}")
        print(f"measurable (>=3 yrs)   : {meas}")
        print(f"CURRENCY MISMATCH      : {len(cur_hits)}  ({len(cur_hits)/max(meas,1)*100:.1f}% of measurable)")
        print(f"SANDWICHED MAGNITUDE   : {len(mag_hits)}  ({len(mag_hits)/max(meas,1)*100:.1f}%)")
        both={c for c,_ in cur_hits} & {c for c,_ in mag_hits}
        print(f"both signals           : {len(both)}")
        print("\n--- currency-mismatch examples (wrong reporting entity) ---")
        for cid,(modal,odd) in cur_hits[:10]:
            print(f"  id={cid:<8} modal={modal}  off-currency years: {', '.join(f'{y}:{c}' for y,c in odd[:6])}")
        print("\n--- sandwiched-magnitude examples (wrong document) ---")
        for cid,s in mag_hits[:10]:
            for y,v,p,n in s[:2]:
                print(f"  id={cid:<8} FY{y} = {v:,.0f}  but FY{y-1}={p:,.0f} and FY{y+1}={n:,.0f}")
asyncio.run(main())
