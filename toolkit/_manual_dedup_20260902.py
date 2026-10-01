#!/usr/bin/env python3
"""Jednorazovy CIELENY dedup (2026-09-02) — RUCNE overene pary, NIE slepy Opus dedup.
Kazdy par bol overeny plnym textom (keeper pokryva removed BEZ straty detailu).
Maze cez mem_store.delete (Lorentz+Gemma+index) + recovery stopa do dedup_trash.jsonl
+ reparent hran (deti removed -> keeper). Fail-open na grafe. Idempotentne (uz zmazane
id preskoci). Spustaj cez .venv-yar python.
"""
import os
import sys
import json

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.join(ROOT, "toolkit"))

import mem_store  # noqa: E402

# remove_id -> keep_id (VSETKY overene plnym textom v tejto session)
PAIRS = {
    712: 696,   # arXiv verifikacia (identicke)
    784: 774,   # faceless video biznis model (identicke)
    778: 776,   # zamknuty Mac riziko (776 bohatsi: +VPS odporucanie)
    801: 779,   # nohavice Mateusz (identicke)
    699: 716,   # Mem0 LLM-judge zhovievavost (716 superset: +swap 0.90->0.48)
    698: 714,   # Mem0 verbatim RAG (pokryte 714 MemDelta + 715 Fidelity)
    894: 714,   # Mem0 A/B (714 konkretnejsi: cisla 47.2 vs 49.8, p=0.34)
}


def load_rows():
    rows = {}
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if line:
            o = json.loads(line)
            rows[o["id"]] = o
    return rows


def main():
    rows = load_rows()
    try:
        import zol_graph
    except Exception as e:
        zol_graph = None
        print(f"WARN zol_graph nedostupny (reparent skip): {e!r}")

    done = []
    for rid, kid in PAIRS.items():
        if rid not in rows:
            print(f"SKIP {rid}: uz nie je v indexe (idempotent)")
            continue
        if kid not in rows:
            print(f"SKIP {rid}->{kid}: keeper {kid} chyba! (bezpecnostny abort tohto paru)")
            continue
        rec = rows[rid]
        # 1) reparent hran removed -> keeper (deti neosiria), fail-open
        rp = None
        if zol_graph is not None:
            try:
                rp = zol_graph.reparent(rid, kid)
            except Exception as e:
                print(f"  reparent {rid}->{kid} zlyhal (hrany ostali): {e!r}")
        # 2) del z OBOCH kolekcii + index + recovery stopa
        res = mem_store.delete(
            rid, remove_index=True, trash_rec=rec,
            reason=f"manual_dedup_20260902 -> merged_into {kid}",
        )
        print(f"DEL {rid}->{kid} | lorentz={res.get('lorentz')} gemma={res.get('gemma')} "
              f"reparent={rp}")
        done.append({"removed": rid, "kept": kid, "res": res})

    print(f"\nHOTOVO: {len(done)}/{len(PAIRS)} zmazanych. Recovery: state/dedup_trash.jsonl")


if __name__ == "__main__":
    main()
