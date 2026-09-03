#!/usr/bin/env python3
"""IBIA fix-forward test: mem_store.put() musí persistovať `source` (a project) do
index-riadku. Predtým ho zahadzoval -> IBIA weighting čítal index a videl 0 provenance.

Offline: stubuje HS insert aj embed, píše do dočasného indexu, overí zapísaný riadok.
Spusti: /usr/bin/python3 toolkit/test_put_persists_source.py
"""
import os
import sys
import json
import tempfile

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLKIT)

import mem_store as ms  # noqa: E402


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    print("=== IBIA: put() persistuje source do indexu ===")
    tmp = tempfile.mkdtemp()
    idx = os.path.join(tmp, "mem_index.jsonl")

    # stub HS insert (nech nič nejde na sieť) + embed
    ms.hs_insert_clean = lambda col, mid, rec: (True, {"ok": True})
    ms.gemma_embed = lambda texts, mode: [[0.0] * 768 for _ in texts]
    ms._yar_embed_one = lambda t: [0.0] * 129
    ms.IDX = idx
    ms.STATE = tmp

    meta = {"kind": "semantic", "memory_type": "semantic", "layer": "L1",
            "salience": 0.6, "confidence": 0.7, "source": "session",
            "project": "zolander", "ts": "2026-08-31T12:00:00",
            "text": "testovaci zaznam"}
    ms.put(1234, "testovaci zaznam", meta, vec=[0.0] * 129, gvec=[0.0] * 768,
           append_index=True)

    with open(idx, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    if not rows:
        fail("index prazdny — put() nezapisal riadok")
    row = rows[-1]
    if "source" not in row:
        fail(f"index riadok NEMA 'source': keys={sorted(row.keys())}")
    if row["source"] != "session":
        fail(f"source zle: {row['source']!r} != 'session'")
    if row.get("project") != "zolander":
        fail(f"project zle/chyba: {row.get('project')!r}")
    print("VYSLEDOK: put() persistuje source+project OK")


if __name__ == "__main__":
    main()
