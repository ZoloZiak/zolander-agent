#!/usr/bin/env python3
"""recall_verify2.py — spravny parser (recall vracia pretty JSON na stdout)."""
import os, sys, io, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem

def recall(q, k=8):
    _si, _so = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps({"query": q, "k": k}))
    buf = io.StringIO(); sys.stdout = buf
    try:
        zol_mem.cmd_recall()
    finally:
        sys.stdin, sys.stdout = _si, _so
    return buf.getvalue().strip()

for q in ["aku elektronicku hudbu robi veducko",
          "elektronika beat efekt analog retazec"]:
    raw = recall(q)
    try:
        r = json.loads(raw)  # cely blob, nie posledny riadok
    except Exception as e:
        print(f"Q:{q}\n  cely-parse err {e!r}; raw[:200]={raw[:200]}")
        continue
    hits = r if isinstance(r, list) else (r.get("results") or r.get("hits") or [])
    ids = [h.get("id") for h in hits]
    print(f"\nQ: {q}")
    print(f"  vratene ID (poradie)={ids}")
    print(f"  683 dohladatelne: {'ANO ✓' if 683 in ids else 'NIE ✗'}")
    for h in hits:
        mark = " <<< NOVY" if h.get("id") == 683 else ""
        txt = (h.get("meta", {}) or {}).get("text") or h.get("text") or ""
        print(f"    [{h.get('id')}] score={h.get('score')} {txt[:70]}{mark}")
