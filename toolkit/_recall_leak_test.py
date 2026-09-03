#!/usr/bin/env python3
"""Over ci purgnuta vata (napr. id 641/490/677) STALE vyskakuje v recall cez
semanticky (Lorentz) / Gemma lens, aj ked je index prerezany. Realny test."""
import sys, os, json, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem

PURGED = {385,395,396,449,451,452,453,454,478,479,480,481,482,483,484,486,487,488,489,490,491,492,493,502,504,505,506,507,508,509,510,511,512,513,515,521,523,546,547,548,549,550,551,552,553,557,558,559,562,565,566,567,569,570,600,602,604,605,607,608,632,633,634,636,638,639,640,641,667,668,669,670,674,675,676,677,678,684}

def recall(q, k=10):
    si = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"query": q, "topk": k}))
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            zol_mem.cmd_recall()
    finally:
        sys.stdin = si
    return json.loads(buf.getvalue())

for q in ["realita je jediny arbiter", "hranica je prvotna", "nezvratnost autorita"]:
    print(f"\n===== QUERY: {q!r} =====")
    res = recall(q, 10)
    hits = res if isinstance(res, list) else res.get("results", res)
    leaked = []
    for r in (hits or []):
        rid = r.get("id")
        txt = (r.get("meta", {}) or {}).get("text", "") or r.get("text", "")
        mark = " <<< PURGED LEAK" if rid in PURGED else ""
        print(f"  id={rid}{mark} | {str(txt)[:60]}")
        if rid in PURGED:
            leaked.append(rid)
    print(f"  -> leaked purged ids: {leaked}")
