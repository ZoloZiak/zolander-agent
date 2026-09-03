#!/usr/bin/env python3
"""subtree_expand.py — ŽL3 subtree expansion pre aggregate dotazy (kolo28).

Zapína sa LEN keď query_router klasifikuje route="aggregate" ("zhrň VŠETKO o X",
"kompletný obraz o Y"). Naivný flat top-k vráti najbližšie body, ale agregačný
dotaz chce POKRYTIE témy. ŽL3 vezme top seed hity ako kotvy a dotiahne ich
subtree — parent hrany (nadhľad, kontext) aj priame child hrany (detaily) —
ako nižšie skórované evidence kandidáty.

Dôkazový les, nie nový fakt: každý pridaný záznam nesie `subtree_expanded`,
`seed_id`, `edge` (parent/child) a `depth`. Nič sa netvorí ani nemaže.

Rovnaká disciplína a rozhranie ako zol_mem._expand_graph_candidates:
  - injectable subtree_fn / children_fn (offline testovateľné, bez zol_graph)
  - route != "aggregate"        → NO-OP
  - chýbajúce fn / prázdny index → FAIL-SAFE (vráť seedy nedotknuté)
  - dedup proti existujúcim IDs
  - hop_decay tlmí skóre pridaných kandidátov pod seed
"""


def expand_subtree_candidates(records, route="point", index=None,
                              subtree_fn=None, children_fn=None,
                              max_seeds=3, max_nodes=6, hop_decay=0.5):
    """Rozšír aggregate recall o subtree kandidátov okolo top seedov.

    Args:
      records: recall kandidáti [{"id","score","meta"}, ...], poradie zachované.
      route: výstup query_router; expander koná LEN pri "aggregate".
      index: {id: {"text","kind",...}} na doplnenie textu pridaných uzlov.
      subtree_fn(mid, depth) -> [{"child","parent","depth"}] (parent hrany nahor).
      children_fn(mid) -> [child_id, ...] (priame deti nadol).
      max_seeds: koľko top hitov brať ako kotvy.
      max_nodes: strop pridaných uzlov celkovo (proti zaplaveniu promptu).
      hop_decay: násobič skóre pridaných kandidátov (< seed).

    Returns: rozšírený zoznam records (seedy prvé, potom subtree kandidáti).
    """
    if route != "aggregate":
        return list(records)
    if not records or subtree_fn is None or not index:
        return list(records)
    try:
        max_seeds = max(0, int(max_seeds))
        max_nodes = max(0, int(max_nodes))
        hop_decay = float(hop_decay)
    except Exception:
        max_seeds, max_nodes, hop_decay = 3, 6, 0.5
    if max_seeds <= 0 or max_nodes <= 0:
        return list(records)

    expanded = list(records)
    seen = {r.get("id") for r in expanded}
    added = 0

    def _add(nid, seed_id, edge, depth, seed_score):
        nonlocal added
        if added >= max_nodes or nid is None or nid in seen:
            return
        doc = index.get(nid)
        if not doc:
            return
        meta = {
            "text": doc.get("text", ""),
            "kind": doc.get("kind"),
            "memory_type": doc.get("memory_type") or doc.get("kind"),
            "layer": doc.get("layer"),
            "ts": doc.get("ts"),
            "source": doc.get("source"),
        }
        expanded.append({
            "id": nid, "col": None, "meta": meta, "distance": None,
            "score": round(seed_score * (hop_decay ** max(depth, 1)), 4),
            "subtree_expanded": True, "seed_id": seed_id,
            "edge": edge, "depth": depth,
        })
        seen.add(nid)
        added += 1

    for seed in records[:max_seeds]:
        if added >= max_nodes:
            break
        sid = seed.get("id")
        if sid is None:
            continue
        seed_score = float(seed.get("score", 0.0) or 0.0)
        # parent hrany (nahor — kontext/nadhľad)
        try:
            for e in (subtree_fn(sid) or []):
                _add(e.get("parent"), sid, "parent", int(e.get("depth", 1)), seed_score)
        except Exception:
            pass
        # child hrany (nadol — detaily)
        if children_fn is not None:
            try:
                for cid in (children_fn(sid) or []):
                    _add(cid, sid, "child", 1, seed_score)
            except Exception:
                pass

    return expanded


if __name__ == "__main__":
    import sys
    import json
    obj = json.loads(sys.stdin.read())
    out = expand_subtree_candidates(
        obj.get("records", []), route=obj.get("route", "point"),
        index=obj.get("index", {}))
    print(json.dumps({"n": len(out), "ids": [c.get("id") for c in out]},
                     ensure_ascii=False, indent=2))
