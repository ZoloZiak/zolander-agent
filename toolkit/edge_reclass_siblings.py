#!/usr/bin/env python3
"""edge_reclass_siblings.py — prekvalifikuj CROSS-LAB konsenzus 'parent'->'related'.

Faza 2/3 (edge-cleanup): cita state/edge_cluster_verdict.json. Berie LEN hrany dieta->hub
kde OPUS aj GEMINI nezavisle povedali relation=='sibling' (konsenzus). Tie NIE su is-a ->
prekvalifikuje parent hranu na related (zachova asociaciu, odstrani z hierarchie).

NEMENI vrstvy uzlov (na to niet cross-lab konsenzu). NEDOTYKA sa is_a ani spornych hran.
Dry-run default. --apply: zaloha bak-reclass-<ts> + atomicky prepis cez zol_graph._rewrite_edges.
Bezi pod /usr/bin/python3 (stdlib)."""
import os, sys, json, time, shutil

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
VERDICT = os.path.join(STATE, "edge_cluster_verdict.json")
sys.path.insert(0, os.path.join(HOME, "projects", "zolander", "toolkit"))
import zol_graph

APPLY = "--apply" in sys.argv

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def consensus_siblings(v):
    """Vrat set (child, hub) kde opus aj gemini == 'sibling'."""
    pairs = set()
    for hub_s, blk in v.items():
        hub = int(hub_s)
        o = blk.get("opus", {}); g = blk.get("gemini", {})
        if not (o.get("ok") and g.get("ok")):
            continue
        orel = {c["id"]: c.get("relation") for c in o["parsed"].get("children", [])}
        grel = {c["id"]: c.get("relation") for c in g["parsed"].get("children", [])}
        for cid in set(orel) & set(grel):
            if orel[cid] == "sibling" and grel[cid] == "sibling":
                pairs.add((cid, hub))
    return pairs

def main():
    rows = load_idx()
    v = json.load(open(VERDICT, encoding="utf-8"))
    targets = consensus_siblings(v)
    edges = zol_graph._read(EDGES)

    # existujuce related (dedup) a najdi parent hrany na prekval.
    existing_related = {(e.get("from"), e.get("to")) for e in edges if e.get("edge") == "related"}
    hit, already_rel = [], 0
    for e in edges:
        if e.get("edge") == "parent" and (e.get("from"), e.get("to")) in targets:
            hit.append((e.get("from"), e.get("to")))

    def short(mid):
        r = rows.get(mid); t = (r.get("text") or "")[:48] if r else "??"
        return f"#{mid}({r.get('layer') if r else '?'}) {t}"

    print(f"Cross-lab konsenzus sibling parov: {len(targets)}")
    print(f"Parent hran na prekvalifikovanie parent->related: {len(hit)}\n")
    for f, t in hit:
        dedup = " [related uz existuje -> len zmaz parent]" if (f, t) in existing_related else ""
        print(f"  {short(f)}  --parent-->  {short(t)}{dedup}")

    if not APPLY:
        print(f"\nDRY-RUN. Spusti s --apply. (INVERTED by malo klesnut ~63->27, SAME ~35->28)")
        return 0

    # aplikuj: parent -> related (dedup ak related uz je -> proste zahod parent)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = EDGES + f".bak-reclass-{ts}"
    shutil.copy2(EDGES, bak)
    out, changed, dropped_dup = [], 0, 0
    seen_related = set(existing_related)
    hitset = set(hit)
    for e in edges:
        if e.get("edge") == "parent" and (e.get("from"), e.get("to")) in hitset:
            key = (e.get("from"), e.get("to"))
            if key in seen_related:
                dropped_dup += 1
                changed += 1
                continue  # related uz existuje -> parent len zahodime
            ne = dict(e); ne["edge"] = "related"
            ne["meta"] = {**(ne.get("meta") or {}), "reclassed_from": "parent",
                          "reason": "cross-lab consensus sibling", "ts": ts}
            seen_related.add(key)
            out.append(ne); changed += 1
        else:
            out.append(e)
    zol_graph._rewrite_edges(out)
    print(f"\nHOTOVO. Zaloha: {bak}")
    print(f"Prekvalifikovanych parent->related: {changed} (z toho {dropped_dup} related uz existoval -> parent zahodeny)")
    print(f"Hran po zapise: {len(out)}")
    print("Over: /usr/bin/python3 toolkit/edge_audit.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
