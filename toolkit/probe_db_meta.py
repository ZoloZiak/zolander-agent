#!/usr/bin/env python3
"""probe_db_meta.py — READ-ONLY prieskum DB point meta pred Bug 2 zapisom.

Ciel: zistit co je v DB meta (hlavne HMAC sig/digest polia), aby re-insert
pri downgrade zachoval podpis. + over ci sa point vobec najde cez search.
"""
import os, sys, io, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem as Z

# re-embed text a search — najdi sam seba, vypis plne meta
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state")
idx = [json.loads(l) for l in open(os.path.join(STATE, "mem_index.jsonl")) if l.strip()]
byid = {r["id"]: r for r in idx}

for probe_id in (514, 487):
    txt = byid[probe_id]["text"]
    vec = Z.embed_one(txt)
    res = Z.hs("search", Z.MEM_COL, 5, stdin=json.dumps({"vector": vec})) or []
    print(f"\n=== probe {probe_id} :: {txt[:60]!r}")
    print(f"  search vratil {len(res)} vysledkov, top ids: {[r.get('id') for r in res]}")
    hit = next((r for r in res if r.get("id") == probe_id), None)
    if hit:
        m = hit.get("meta", {}) or {}
        print(f"  NASIEL SA. meta kluce: {sorted(m.keys())}")
        print(f"  salience={m.get('salience')!r}  layer={m.get('layer')!r}  kind={m.get('kind') or m.get('memory_type')!r}")
        # HMAC polia?
        for k in ("sig", "digest", "hmac", "owner", "signed"):
            if k in m:
                print(f"  HMAC pole {k!r}: {str(m[k])[:40]}...")
    else:
        print(f"  !!! {probe_id} sa NENASIEL v top5 (nedeterministicky search)")
