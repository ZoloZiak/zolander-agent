#!/usr/bin/env python3
"""test_link_guard.py — overi POISTKU v zol_graph.link() proti INVERTED/cyklickym
parent hranam. Izolovany: presmeruje STATE/EDGES/MEM_INDEX na docasny adresar, aby
sa NIKDY nedotkol ziveho grafu. Bezi pod /usr/bin/python3 (stdlib).

Spustenie:  /usr/bin/python3 toolkit/test_link_guard.py
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zol_graph as G  # noqa: E402


def _setup(tmp):
    """Presmeruj vsetky cesty modulu na tmp a nasadaj mem_index s vrstvami."""
    G.STATE = tmp
    G.EDGES = os.path.join(tmp, "mem_edges.jsonl")
    G.TEMPORAL = os.path.join(tmp, "mem_temporal.jsonl")
    G.MEM_INDEX = os.path.join(tmp, "mem_index.jsonl")
    # uzly: 1=L0, 2=L1, 3=L2, 4=L3, 5=L1 (bez layeru: 99)
    idx = [
        {"id": 1, "layer": "L0", "text": "epizoda"},
        {"id": 2, "layer": "L1", "text": "destilat"},
        {"id": 3, "layer": "L2", "text": "jadro"},
        {"id": 4, "layer": "L3", "text": "meta"},
        {"id": 5, "layer": "L1", "text": "iny destilat"},
        {"id": 99, "text": "bez vrstvy"},
    ]
    with open(G.MEM_INDEX, "w", encoding="utf-8") as f:
        for r in idx:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _last_edge():
    rows = G._read(G.EDGES)
    return rows[-1] if rows else None


def run():
    fails = []

    def check(name, cond, detail=""):
        status = "OK" if cond else "FAIL"
        print(f"[{status}] {name}" + (f" :: {detail}" if detail else ""))
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        _setup(tmp)

        # 1) L0 -> L1 parent: dieta nizsie, rodic vyssie = SPRAVNE is-a, ostane parent
        e = G.link(1, 2, "parent")
        check("L0->L1 ostane parent", e["edge"] == "parent" and "meta" not in e, str(e))

        # 2) L2 -> L1 parent: rodic (L1) NIZSIE nez dieta (L2) = INVERTED -> degrade
        e = G.link(3, 2, "parent")
        check("L2->L1 degraduje na related (inverted_layer)",
              e["edge"] == "related"
              and e.get("meta", {}).get("degrade_reason") == "inverted_layer", str(e))

        # 3) L1 -> L1 parent: rovnaka vrstva = surodenci -> degrade (same_layer)
        e = G.link(2, 5, "parent")
        check("L1->L1 degraduje na related (same_layer)",
              e["edge"] == "related"
              and e.get("meta", {}).get("degrade_reason") == "same_layer", str(e))

        # 4) cyklus: uz mame 1->2 (parent). Skus 2->1 parent = uzavrel by cyklus -> degrade.
        e = G.link(2, 1, "parent")
        check("cyklus 2->1 degraduje (would_create_cycle)",
              e["edge"] == "related"
              and e.get("meta", {}).get("degrade_reason") == "would_create_cycle", str(e))

        # 5) enforce=False obide poistku: L2->L1 parent PREJDE tak ako je
        e = G.link(3, 2, "parent", enforce=False)
        check("enforce=False obide poistku",
              e["edge"] == "parent" and "degrade_reason" not in e.get("meta", {}), str(e))

        # 6) fail-open: uzol 99 bez vrstvy -> parent PREJDE (netvrdim inverziu z nedostatku dat)
        e = G.link(99, 2, "parent")
        check("bez vrstvy fail-open (parent prejde)",
              e["edge"] == "parent" and "degrade_reason" not in e.get("meta", {}), str(e))

        # 7) explicitne from_layer/to_layer hinty (dream ich posiela) prebiju index
        e = G.link(1, 5, "parent", from_layer="L2", to_layer="L1")
        check("hint from_layer/to_layer degraduje (inverted)",
              e["edge"] == "related"
              and e.get("meta", {}).get("degrade_reason") == "inverted_layer", str(e))

        # 8) related hrana sa NIKDY nedotyka poistky (len parent)
        e = G.link(3, 2, "related")
        check("related ostava related (guard len na parent)", e["edge"] == "related", str(e))

    print()
    if fails:
        print(f"VYSLEDOK: {len(fails)} FAIL: {fails}")
        return 1
    print("VYSLEDOK: vsetkych 8 testov OK")
    return 0


if __name__ == "__main__":
    sys.exit(run())
