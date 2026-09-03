#!/usr/bin/env python3
"""verify_zombies2.py — over 541/621/640 cez realnu Lorentz search cestu.

640 je merge KEEPER (nemazal som ho) -> ak vyjde 'zombie', je to FALSE-POSITIVE
guardu (Lorentz union neuplny). Metoda ako cmd_recall: embed_one + hs search.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_mem import hs, MEM_COL
from embed_yar import embed_one

STATE = os.path.expanduser("~/projects/zolander/state")
idx = [json.loads(l) for l in open(os.path.join(STATE, "mem_index.jsonl")) if l.strip()]
byid = {r["id"]: r for r in idx}

for zid in [541, 621, 640]:
    r = byid.get(zid)
    if not r:
        print(f"[{zid}] NIE je v indexe"); continue
    txt = r["text"]
    vec = embed_one(txt)
    try:
        res = hs("search", MEM_COL, 30, stdin=json.dumps({"vector": vec})) or []
    except Exception as e:
        print(f"[{zid}] search chyba: {e!r}"); continue
    ids = [h.get("id") for h in res]
    found = zid in ids
    print(f"[{zid}] {r.get('layer')}/{r.get('kind')} :: {txt[:60]}")
    print(f"    self-search top30 vratil {zid}? {'ANO=ZIVY (false-positive guardu)' if found else 'NIE=realny zombie'}  (top8: {ids[:8]})")
