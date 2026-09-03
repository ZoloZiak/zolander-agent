#!/usr/bin/env python3
"""edge_phase3_apply.py — aplikuj fazu 3 (identity klaster + near-duplicity) parent->related.

APLIKUJE LEN cross-lab potvrdene / zjavne:
  IDENTITY (cross-lab 13/13 sibling, apex zamietnuty 1/3 gpt): vsetky parent hrany
    dieta->hub kde hub in {611,494}. To pokryva SAME_LAYER aj INVERTED identity hrany.
  NEAR-DUP (zjavne, netreba LLM): explicitny zoznam near-duplikatov / cross-ref.

NEDOTYKA sa epistemickeho klastra (huby 685,558): tam NIET cross-lab konsenzu
(symetricky test 8/17 is_a, 9 spor) -> ostava ako dokumentovany limit v RFC.

Dry-run default. --apply: zaloha + atomicky prepis. Bezi /usr/bin/python3 (stdlib)."""
import os, sys, json, time, shutil

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
sys.path.insert(0, os.path.join(HOME, "projects", "zolander", "toolkit"))
import zol_graph

APPLY = "--apply" in sys.argv
IDENTITY_HUBS = {611, 494}
# near-duplicity / cross-ref (child, hub) — zjavne rovnaka uroven, nie is-a:
NEAR_DUP = [(498, 686), (572, 672), (592, 672)]
AUDIT = os.path.join(STATE, "edge_audit.json")

def load_worklist_edges():
    """LEN hrany ktore audit oznacil (INVERTED/SAME_LAYER) = mandat fazy 3.
    NEberieme L0 epizody ktore audit ma za OK (mimo mandatu, necross-labovane)."""
    a = json.load(open(AUDIT, encoding="utf-8"))
    wl = a["worklist"]
    s = set()
    for key in ("INVERTED", "SAME_LAYER"):
        for e in wl.get(key, []):
            s.add((e["from"], e["to"]))
    return s

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def short(rows, mid):
    r = rows.get(mid)
    return f"#{mid}({r.get('layer') if r else '?'}) {(r.get('text') or '')[:46] if r else '??'}"

def main():
    rows = load_idx()
    edges = zol_graph._read(EDGES)
    existing_related = {(e.get("from"), e.get("to")) for e in edges if e.get("edge") == "related"}

    targets = set(NEAR_DUP)          # (child, hub)
    worklist = load_worklist_edges()
    for e in edges:
        if e.get("edge") == "parent" and e.get("to") in IDENTITY_HUBS \
                and (e.get("from"), e.get("to")) in worklist:
            targets.add((e.get("from"), e.get("to")))

    hit = [(e.get("from"), e.get("to")) for e in edges
           if e.get("edge") == "parent" and (e.get("from"), e.get("to")) in targets]

    print(f"IDENTITY huby: {IDENTITY_HUBS}  NEAR-DUP: {len(NEAR_DUP)}")
    print(f"Parent hran na prekvalifikovanie parent->related: {len(hit)}\n")
    for f, t in hit:
        tag = " [near-dup]" if (f, t) in NEAR_DUP else ""
        dedup = " [related uz je]" if (f, t) in existing_related else ""
        print(f"  {short(rows,f)}  --parent-->  {short(rows,t)}{tag}{dedup}")

    if not APPLY:
        print(f"\nDRY-RUN. Spusti s --apply. NEDOTYKAM sa epistemic klastra (685/558).")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = EDGES + f".bak-phase3-{ts}"
    shutil.copy2(EDGES, bak)
    out, changed, dropped = [], 0, 0
    seen_related = set(existing_related)
    hitset = set(hit)
    for e in edges:
        key = (e.get("from"), e.get("to"))
        if e.get("edge") == "parent" and key in hitset:
            if key in seen_related:
                dropped += 1; changed += 1; continue
            ne = dict(e); ne["edge"] = "related"
            ne["meta"] = {**(ne.get("meta") or {}), "reclassed_from": "parent",
                          "reason": ("near-duplicate" if key in NEAR_DUP
                                     else "cross-lab consensus sibling (identity)"),
                          "phase": 3, "ts": ts}
            seen_related.add(key); out.append(ne); changed += 1
        else:
            out.append(e)
    zol_graph._rewrite_edges(out)
    print(f"\nHOTOVO. Zaloha: {bak}")
    print(f"Prekvalifikovanych parent->related: {changed} (dedup zahodenych: {dropped})")
    print(f"Hran po zapise: {len(out)}")
    print("Over: /usr/bin/python3 toolkit/edge_audit.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
