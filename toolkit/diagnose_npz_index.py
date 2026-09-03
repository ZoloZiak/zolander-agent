#!/usr/bin/env python3
"""Bug #2/#3 diagnostika: NPZ (gemma_all_nodes.npz) vs mem_index.jsonl.

Zisťuje naostro (systémový python3 + numpy, žiadny embed/DB):
  - koľko ID je v NPZ, koľko v indexe
  - orphan: v NPZ ale NIE v indexe (mŕtve vektory)
  - missing: v indexe ale NIE v NPZ (chýbajúci vektor)
  - prázdne: NPZ vektor s (skoro) nulovou normou
Read-only. Spusti: /usr/bin/python3 toolkit/diagnose_npz_index.py
"""
import os
import json

import numpy as np

STATE = os.path.join(os.path.expanduser("~"), "projects", "zolander", "state")
NPZ = os.path.join(STATE, "gemma_all_nodes.npz")
IDX = os.path.join(STATE, "mem_index.jsonl")


def main():
    d = np.load(NPZ, allow_pickle=True)
    npz_ids = [int(x) for x in d["ids"]]
    V = np.asarray(d["vecs"], dtype="float64")
    norms = np.linalg.norm(V, axis=1)

    idx_ids = []
    with open(IDX, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                idx_ids.append(int(json.loads(line)["id"]))

    npz_set, idx_set = set(npz_ids), set(idx_ids)
    orphans = sorted(npz_set - idx_set)
    missing = sorted(idx_set - npz_set)
    zero_norm = [npz_ids[i] for i in range(len(npz_ids)) if norms[i] < 1e-6]

    print(f"NPZ vektorov:   {len(npz_ids)}")
    print(f"index ID:       {len(idx_ids)}")
    print(f"orphan (NPZ\\idx): {len(orphans)}  {orphans[:20]}")
    print(f"missing (idx\\NPZ):{len(missing)}  {missing[:20]}")
    print(f"nulová norma:   {len(zero_norm)}  {zero_norm[:20]}")

    # prienik prázdnych s orphanmi (sú tie prázdne zároveň orphan?)
    zn_orphan = sorted(set(zero_norm) & set(orphans))
    zn_live = sorted(set(zero_norm) & idx_set)
    print(f"\nprázdne & orphan: {len(zn_orphan)}  {zn_orphan[:20]}")
    print(f"prázdne & ŽIVÉ (v indexe!): {len(zn_live)}  {zn_live[:20]}")
    if zn_live:
        print("  ^ POZOR: živý index záznam má prázdny/nulový Gemma vektor -> recall degradovaný")


if __name__ == "__main__":
    main()
