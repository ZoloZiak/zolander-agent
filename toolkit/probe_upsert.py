#!/usr/bin/env python3
"""probe_upsert.py — EMPIRICKY over: insert s existujucim ID = upsert alebo duplikat?

Test na docasnom ID 999001 (mimo realneho rozsahu). Ziaden zasah do realnej pamate.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem as Z

TID = 999001
txt = "PROBE UPSERT TEST zzz-marker-999001 docasny zaznam na overenie upsert mechaniky"
vec = Z.embed_one(txt)

def count_hits():
    res = Z.hs("search", Z.MEM_COL, 20, stdin=json.dumps({"vector": vec})) or []
    return [(r.get("id"), (r.get("meta", {}) or {}).get("salience")) for r in res if r.get("id") == TID]

# 1) prvy insert sal=0.9
rec1 = json.dumps({"id": TID, "vector": vec, "meta": {"kind": "semantic", "memory_type": "semantic", "layer": "L2", "salience": "0.9", "text": txt}}, ensure_ascii=False) + "\n"
Z.hs("insert", Z.MEM_COL, stdin=rec1)
h1 = count_hits()
print(f"po 1. insert (sal=0.9): {len(h1)} zaznamov s ID {TID} -> {h1}")

# 2) re-insert rovnake ID sal=0.3
rec2 = json.dumps({"id": TID, "vector": vec, "meta": {"kind": "semantic", "memory_type": "semantic", "layer": "L2", "salience": "0.3", "text": txt}}, ensure_ascii=False) + "\n"
Z.hs("insert", Z.MEM_COL, stdin=rec2)
h2 = count_hits()
print(f"po 2. insert (sal=0.3): {len(h2)} zaznamov s ID {TID} -> {h2}")

if len(h2) == 1 and h2[0][1] == "0.3":
    print("VERDIKT: UPSERT (in-place, salience presla na 0.3) -> re-insert je bezpecny")
elif len(h2) > 1:
    print("VERDIKT: DUPLIKAT (vznikli 2 zaznamy) -> downgrade MUSI robit del+insert")
else:
    print(f"VERDIKT: NEJASNE (search nedeterministicky) h2={h2}")

# 3) upratanie test ID
d = Z.hs("del", Z.MEM_COL, str(TID))
print(f"cleanup: del {TID} -> {d}")
