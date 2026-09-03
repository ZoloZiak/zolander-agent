#!/usr/bin/env python3
"""edge_clean_orphans.py — FAZA 1 cistenia: zahod ORPHAN parent/related hrany.

ORPHAN = hrana ktorej from ALEBO to uzol uz neexistuje v mem_index.jsonl (decay zmazal
uzol, hrana ostala visiet). Cisty technicky dlh — zahodenie je bezpecne a reverzibilne.

BEZPECNOST:
  - DRY-RUN je DEFAULT. Bez --apply nic nezapise, len vypise co by zahodilo.
  - Pred --apply spravi zalohu state/mem_edges.jsonl.bak-orphan-<ts>.
  - Zapis cez zol_graph._rewrite_edges (atomicky tmp+os.replace, fcntl lock).
  - Zahadzuje LEN hrany s neexistujucim uzlom. Validne (oba uzly su) sa NEDOTKNE.

Pouzitie:
  /usr/bin/python3 toolkit/edge_clean_orphans.py            # dry-run (default)
  /usr/bin/python3 toolkit/edge_clean_orphans.py --apply    # naozaj zahod + zaloha
"""
import os, sys, json, time, shutil

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
sys.path.insert(0, os.path.join(HOME, "projects", "zolander", "toolkit"))


def load_ids():
    ids = set()
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            ids.add(json.loads(l)["id"])
    return ids


def load_edges():
    out = []
    for l in open(EDGES, encoding="utf-8"):
        l = l.strip()
        if l:
            out.append(json.loads(l))
    return out


def main():
    apply = "--apply" in sys.argv
    ids = load_ids()
    edges = load_edges()
    keep, drop = [], []
    for e in edges:
        f, t = e.get("from"), e.get("to")
        if f in ids and t in ids:
            keep.append(e)
        else:
            drop.append(e)

    from collections import Counter
    dt = Counter(e.get("edge", "?") for e in drop)
    print(f"hran spolu: {len(edges)}   validnych: {len(keep)}   ORPHAN na zahodenie: {len(drop)}")
    print(f"  z toho podla typu: {dict(dt)}")
    print(f"  ({len(drop)} hran mieri na uzol co uz neexistuje = decay dlh)")

    if not apply:
        print("\nDRY-RUN (nic sa nezmenilo). Spusti s --apply pre realne zahodenie + zalohu.")
        print("Prvych 10 co by sa zahodilo:")
        for e in drop[:10]:
            print(f"  {e.get('edge')}: {e.get('from')} -> {e.get('to')}")
        return 0

    # --apply: zaloha + atomicky prepis
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = f"{EDGES}.bak-orphan-{ts}"
    shutil.copy2(EDGES, bak)
    import zol_graph
    zol_graph._rewrite_edges(keep)
    print(f"\nHOTOVO. Zaloha: {bak}")
    print(f"Zahodenych {len(drop)} orphan hran, ostalo {len(keep)}.")
    print("Over: /usr/bin/python3 toolkit/edge_audit.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
