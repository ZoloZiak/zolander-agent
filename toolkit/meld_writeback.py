#!/usr/bin/env python3
"""MELD writeback: aplikuj SCHVÁLENÉ MERGE-konsenzus návrhy cez zol_graph.supersede.

NIE hard-delete. Používa bitemporal supersede (valid_until + supersedes hrana) —
reverzibilné, recall superseded odfiltruje (LOOP #2 StateMem current-state filter).

Union-find: prepojené páry (#206~611, #195~206) tvoria KLASTER; v klastri prežije
survivor = najbohatší (dĺžka textu -> novší ts -> vyššia salience), ostatní -> superseded doňho.
Tým sa vyhne dangling ref (supersedovať A do B a potom mať pár C~A na mŕtve A).

Berie LEN páry s verdict=MERGE & agree=consensus (3/3). Default DRY-RUN.
  .venv-yar/bin/python toolkit/meld_writeback.py            # dry-run (plán)
  .venv-yar/bin/python toolkit/meld_writeback.py --commit   # vykoná supersede
"""
import os
import sys
import json

ROOT = os.path.expanduser("~/projects/zolander")
STATE = os.path.join(ROOT, "state")
PROP = os.path.join(STATE, "meld_proposals.jsonl")
IDX = os.path.join(STATE, "mem_index.jsonl")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))


def _load_idx():
    idx = {}
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if line:
            o = json.loads(line)
            idx[o["id"]] = o
    return idx


def _richness(o):
    """Vyšší = bohatší survivor: dĺžka textu, potom novší ts, potom salience."""
    return (len(o.get("text", "")), o.get("ts", ""), o.get("salience", 0) or 0)


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main():
    commit = "--commit" in sys.argv
    idx = _load_idx()
    prop = [json.loads(l) for l in open(PROP, encoding="utf-8") if l.strip()]
    merge_pairs = [(r["a"], r["b"]) for r in prop
                   if r["verdict"] == "MERGE" and r["agree"] == "consensus"]

    # union-find -> klastre
    uf = UF()
    ids = set()
    for a, b in merge_pairs:
        uf.union(a, b)
        ids.add(a)
        ids.add(b)
    clusters = {}
    for m in ids:
        clusters.setdefault(uf.find(m), set()).add(m)

    plan = []
    for _, members in clusters.items():
        members = [m for m in members if m in idx]
        if len(members) < 2:
            continue
        survivor = max(members, key=lambda m: _richness(idx[m]))
        losers = [m for m in members if m != survivor]
        plan.append((survivor, losers))

    print(f"MERGE-konsenzus párov: {len(merge_pairs)} -> {len(plan)} klastrov")
    for survivor, losers in plan:
        print(f"\n  PREŽIJE #{survivor}: {idx[survivor]['text'][:75]!r}")
        for m in losers:
            print(f"  supersede #{m} -> #{survivor}: {idx[m]['text'][:60]!r}")

    if not commit:
        print("\n[dry-run] nič sa nezmenilo. Spusti s --commit na vykonanie.")
        return

    import zol_graph
    done = []
    for survivor, losers in plan:
        for m in losers:
            try:
                zol_graph.supersede(survivor, m)
                done.append((m, survivor))
            except Exception as e:
                print(f"  CHYBA supersede #{m}->#{survivor}: {e}")
    print(f"\n[commit] superseded {len(done)} záznamov (reverzibilné, valid_until). "
          f"Recall ich odfiltruje pri ďalšom štarte.")


if __name__ == "__main__":
    main()
