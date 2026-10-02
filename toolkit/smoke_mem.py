#!/usr/bin/env python3
"""smoke_mem.py — E2E smoke test novej pamäte (embed_yar -> zol_mem -> HSDB -> recall).
Overuje že cely retazec funguje na reálnom modeli a Lorentz kolekciách.
Model sa načíta RAZ (import embed_yar), vloží 4 spomienky, spraví 2 recally.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem as zm

def remember(text, kind, layer="L0"):
    mid = zm.next_id()
    vec = zm.embed_one(text)
    col = zm.col_for(kind)
    meta = {"kind": kind, "layer": layer, "salience": 0.6, "confidence": 0.8,
            "source": "smoke", "project": "zolander", "links": "",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text[:300]}
    zm.hs("insert", col, stdin=json.dumps({"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n")
    print(f"  + [{col}] id={mid}: {text[:50]}")
    return mid

print("== vkladam spomienky ==")
remember("Zolander vola pouzivatela 'veducko' a ma jedovaty humor.", "identity", "L2")
remember("Cesta B: nativny hyperbolicky embedder YAR v5 nahradil EmbeddingGemmu.", "semantic", "L1")
remember("Dnes presiel izolovany test YAR v5 naostro, SK/PL/EN funguje.", "episodic", "L0")
remember("Recept na gulas: cibulu opraz na masti, pridaj papriku a maso.", "semantic", "L1")

print("\n== recall 'ako sa oslovuje pouzivatel' (identity) ==")
vec = zm.embed_one("ako Zolander oslovuje pouzivatela")
res = zm.hs("search", "zol_identity", 3, stdin=json.dumps({"vector": vec}))
for r in (res or []):
    print(f"  d={r.get('distance'):.4f}  {r.get('meta',{}).get('text','')[:60]}")

print("\n== recall 'aky embedder pouzivame' (semantic) ==")
vec = zm.embed_one("aky embedding model pouziva pamat")
res = zm.hs("search", "zol_semantic", 3, stdin=json.dumps({"vector": vec}))
for r in (res or []):
    print(f"  d={r.get('distance'):.4f}  {r.get('meta',{}).get('text','')[:60]}")
