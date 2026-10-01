#!/usr/bin/env python3
"""recall_verify.py — over ci je novy fakt 683 dohladatelny cez oficialny recall."""
import os, sys, io, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem

def recall(q, k=5):
    _si, _so = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps({"query": q, "k": k}))
    buf = io.StringIO(); sys.stdout = buf
    try:
        zol_mem.cmd_recall()
    finally:
        sys.stdin, sys.stdout = _si, _so
    return buf.getvalue().strip()

for q in ["aku tvrdu elektroniku a hudbu robi veducko gabber hardcore",
          "gabber kick 909 distorzia analog"]:
    out = recall(q)
    try:
        r = json.loads(out.splitlines()[-1])
        hits = r.get("results") or r.get("hits") or (r if isinstance(r, list) else [])
        ids = [h.get("id") for h in hits] if isinstance(hits, list) else "?"
        print(f"\nQ: {q}")
        print(f"  vratene ID={ids}  ->  683 dohladatelne: {'ANO' if (isinstance(ids,list) and 683 in ids) else 'NIE'}")
        for h in (hits if isinstance(hits, list) else [])[:3]:
            print(f"    [{h.get('id')}] {(h.get('text') or '')[:85]}")
    except Exception as e:
        print(f"Q: {q}\n  parse err: {e!r}\n  raw: {out[-400:]}")
