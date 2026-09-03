#!/usr/bin/env python3
"""edge_audit.py — AUDIT parent-hran v Zolanderovej pamati. LEN CITA, nic nemeni.

Ciel (RFC §9 paka: OSTROST is-a hierarchie): klasifikuj kazdu parent hranu do kategorie,
vypis worklist pre cistenie. Ziadny zapis, ziadne LLM. Bezi pod /usr/bin/python3 (stdlib).

Kategorie parent hrany (from=DIETA -> to=RODIC; rodic ma byt ABSTRAKTNEJSI = VYSSIA vrstva):
  ORPHAN     : from alebo to uz neexistuje v mem_index (decay zmazal uzol, hrana ostala)
  INVERTED   : rodic ma NIZSIU vrstvu nez dieta (opacna hrana alebo zla layer klasifikacia)
  SAME_LAYER : rodic a dieta na rovnakej vrstve (lateralna, nie is-a — asociacia?)
  OK         : rodic vyssia vrstva nez dieta (validna is-a kandidatka)
Plus: deti s >1 rodicom (multi-parent — pri preklopeni na strom rozhodnut hlavneho rodica).

Vystup: state/edge_audit.json (strojovy worklist) + citatelny sumar na stdout.
Pouziti: /usr/bin/python3 toolkit/edge_audit.py
"""
import os, json
from collections import Counter, defaultdict

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def load_rows():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l)
            rows[r["id"]] = r
    return rows


def load_edges():
    out = []
    if os.path.exists(EDGES):
        for l in open(EDGES, encoding="utf-8"):
            l = l.strip()
            if l:
                try:
                    out.append(json.loads(l))
                except Exception:
                    pass
    return out


def short(rows, mid):
    r = rows.get(mid)
    if not r:
        return f"[#{mid} NEEXISTUJE]"
    t = (r.get("text") or "")[:60]
    return f"#{mid}({r.get('layer','?')}): {t}"


def main():
    rows = load_rows()
    edges = load_edges()
    par = [e for e in edges if e.get("edge") == "parent"]

    cats = {"ORPHAN": [], "INVERTED": [], "SAME_LAYER": [], "OK": []}
    seen = set()
    for e in par:
        f, t = e.get("from"), e.get("to")
        if f == t:
            continue
        if (f, t) in seen:
            continue
        seen.add((f, t))
        if f not in rows or t not in rows:
            cats["ORPHAN"].append((f, t)); continue
        cl, pl = LORD.get(rows[f].get("layer"), -1), LORD.get(rows[t].get("layer"), -1)
        if pl > cl:
            cats["OK"].append((f, t))
        elif pl == cl:
            cats["SAME_LAYER"].append((f, t))
        else:
            cats["INVERTED"].append((f, t))

    # multi-parent deti (len z platnych, oba uzly existuju)
    pc = Counter(f for (f, t) in seen if f in rows and t in rows)
    multi = {f: c for f, c in pc.items() if c > 1}

    result = {
        "edges_total": len(edges),
        "parent_total": len(par),
        "parent_distinct": len(seen),
        "counts": {k: len(v) for k, v in cats.items()},
        "multi_parent_children": len(multi),
        "worklist": {
            "ORPHAN": [{"from": f, "to": t} for f, t in cats["ORPHAN"]],
            "INVERTED": [{"from": f, "to": t} for f, t in cats["INVERTED"]],
            "SAME_LAYER": [{"from": f, "to": t} for f, t in cats["SAME_LAYER"]],
        },
        "multi_parent": {str(f): pc[f] for f in multi},
    }
    json.dump(result, open(os.path.join(STATE, "edge_audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"AUDIT parent-hran (state/mem_edges.jsonl)")
    print(f"  hran spolu: {len(edges)}   parent: {len(par)}   distinct parent: {len(seen)}")
    print(f"  ORPHAN (uzol neexistuje): {len(cats['ORPHAN'])}  <- CISTY DLH, zahodit")
    print(f"  INVERTED (rodic nizsie):  {len(cats['INVERTED'])}  <- preverit smer/layer")
    print(f"  SAME_LAYER (lateralne):   {len(cats['SAME_LAYER'])}  <- parent? alebo related?")
    print(f"  OK (validna is-a):        {len(cats['OK'])}")
    print(f"  deti s >1 rodicom:        {len(multi)}  <- pri strome zvolit hlavneho")
    print("=" * 70)
    for cat in ("ORPHAN", "INVERTED", "SAME_LAYER"):
        if cats[cat]:
            print(f"\n--- {cat} (prvych 8) ---")
            for f, t in cats[cat][:8]:
                print(f"  {short(rows, f)}  -->  {short(rows, t)}")
    print(f"\nWorklist zapisany: {os.path.join(STATE, 'edge_audit.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
