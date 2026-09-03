#!/usr/bin/env python3
"""edge_phase3_epistemic_apply.py — aplikuj verdikt 3-lab na 24 epistemickych INVERTED hran.

Vstup: rozhodnutia zafixovane z edge_phase3_epistemic_3lab.json + striktna vacsina (>=2/3)
a geometria (r_opus, MARGIN=0.05). Zafixovane VOPRED, nizsie ako konstanty (aby apply
nebol zavisly na opatovnom LLM behu):

  REVERSE (4): dieta preukazatelne abstraktnejsie (geom rev + >=2/3 labov 'dieta subsumuje
               hub') -> hrana sa OTOCI child->hub  =>  hub->child (parent, cista is-a).
  KEEP    (3): hub abstraktnejsi (geom isa + 3/3 labov) -> hrana OSTAVA parent (INVERTED
               flag bol len artefakt hrubeho layer-stringu; nemenime).
  RELATED (17): siblings alebo spor -> parent prekvalifikovana na related.

Cielovy graf overeny ako acyklicky DAG (edge_phase3_epistemic_3lab beh + cycle check).
Zaloha + atomicky zapis (temp+rename). Dry-run default; --apply zapisuje.
"""
import os, sys, json, time, shutil

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
EDGES_PATH = os.path.join(STATE, "mem_edges.jsonl")
APPLY = "--apply" in sys.argv

# zafixovane rozhodnutia (child, hub)
REVERSE = [(487, 685), (490, 685), (640, 685), (490, 558)]
KEEP    = [(478, 685), (509, 685), (567, 685)]
RELATED = [(347, 685), (449, 685), (492, 685), (512, 685), (515, 685), (552, 685),
           (559, 685), (570, 685), (667, 685), (670, 685), (677, 685), (558, 685),
           (347, 558), (492, 558), (512, 558), (515, 558), (552, 558)]

def read_jsonl(path):
    out = []
    for l in open(path, encoding="utf-8"):
        l = l.strip()
        if l: out.append(json.loads(l))
    return out

def main():
    edges = read_jsonl(EDGES_PATH)
    rev_set, rel_set = set(REVERSE), set(RELATED)
    keep_set = set(KEEP)

    n_rev = n_rel = n_keep = 0
    new_edges = []
    for e in edges:
        f, t, kind = e.get("from"), e.get("to"), e.get("edge")
        key = (f, t)
        if kind == "parent" and key in rev_set:
            ne = dict(e); ne["from"], ne["to"] = t, f      # otoc smer
            ne["_note"] = "phase3-reverse (dieta abstraktnejsie, 3-lab)"
            new_edges.append(ne); n_rev += 1
        elif kind == "parent" and key in rel_set:
            ne = dict(e); ne["edge"] = "related"
            ne["_note"] = "phase3-sibling/spor->related (3-lab)"
            new_edges.append(ne); n_rel += 1
        else:
            if kind == "parent" and key in keep_set:
                n_keep += 1
            new_edges.append(e)

    print(f"REVERSE otocene: {n_rev}/{len(REVERSE)}")
    print(f"RELATED prekval: {n_rel}/{len(RELATED)}")
    print(f"KEEP nedotknute: {n_keep}/{len(KEEP)}")
    print(f"hran spolu: {len(edges)} -> {len(new_edges)} (pocet sa nemeni)")

    if not APPLY:
        print("\n[DRY-RUN] nic nezapisane. Spusti s --apply.")
        return 0

    bak = EDGES_PATH + ".bak-epistemic-" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(EDGES_PATH, bak)
    tmp = EDGES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in new_edges:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, EDGES_PATH)
    print(f"\n[APPLY] zaloha: {bak}")
    print(f"[APPLY] zapisane: {EDGES_PATH}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
