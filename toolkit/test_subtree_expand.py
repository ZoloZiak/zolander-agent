#!/usr/bin/env python3
"""test_subtree_expand.py — ŽL3 subtree expansion pre aggregate dotazy (kolo28).

Keď query_router povie route="aggregate" ("zhrň VŠETKO o X"), naivný top-k flat
recall vráti len najbližšie hity — ale agregačný dotaz chce POKRYTIE témy, nie
najbližší bod. ŽL3 dotiahne subtree (parent + child hrany) okolo top seedov ako
nižšie skórované evidence kandidáty. Rovnaká disciplína ako graph_expand:
každý pridaný záznam nesie `subtree_expanded` + `seed_id` + hĺbku, nič sa
nevytvára ani nemaže.

Iron law (TDD): napísané PRED expand_subtree_candidates(), musí zlyhať ImportErrorom.

Beh: /usr/bin/python3 toolkit/test_subtree_expand.py   (offline, injectované fn)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from subtree_expand import expand_subtree_candidates

FAILS = []

# graf: 10 je seed; jeho subtree = 11 (child), 12 (parent), 13 (grandparent)
SUBTREE_EDGES = {
    10: [{"child": 10, "parent": 12, "depth": 1},
         {"child": 12, "parent": 13, "depth": 2}],
    11: [{"child": 11, "parent": 10, "depth": 1}],
}
# reverzné child hrany: kto má 10 za rodiča → 11
CHILDREN = {10: [11], 12: [10], 13: [12]}

INDEX = {
    10: {"text": "seed o Wole", "kind": "fact"},
    11: {"text": "detail 1 o Wole", "kind": "fact"},
    12: {"text": "nadradený koncept Varšava", "kind": "fact"},
    13: {"text": "koreň Poľsko", "kind": "fact"},
}


def fake_subtree(mid, depth=3):
    return SUBTREE_EDGES.get(mid, [])


def fake_children(mid):
    return CHILDREN.get(mid, [])


SEEDS = [{"id": 10, "score": 0.9, "meta": {"text": "seed o Wole"}}]


# --- AGGREGATE route: seed 10 sa rozšíri o subtree (parent 12, 13 + child 11) ---
out = expand_subtree_candidates(
    SEEDS, route="aggregate", index=INDEX,
    subtree_fn=fake_subtree, children_fn=fake_children, max_seeds=1)
ids = [c["id"] for c in out]
if 10 not in ids:
    FAILS.append(f"  seed 10 musí ostať, dostal {ids}")
if 12 not in ids or 11 not in ids:
    FAILS.append(f"  subtree susedia 11 (child) + 12 (parent) mali pribudnúť, dostal {ids}")

# pridané kandidáty nesú audit meta
for c in out:
    if c["id"] != 10:
        if not c.get("subtree_expanded") or c.get("seed_id") != 10:
            FAILS.append(f"  id {c['id']} musí niesť subtree_expanded + seed_id=10")
        if c.get("score", 1.0) >= 0.9:
            FAILS.append(f"  rozšírený id {c['id']} má mať nižšie skóre než seed (hop decay)")

# --- POINT route: NO-OP, žiadne rozšírenie ---
out_point = expand_subtree_candidates(
    SEEDS, route="point", index=INDEX,
    subtree_fn=fake_subtree, children_fn=fake_children)
if [c["id"] for c in out_point] != [10]:
    FAILS.append(f"  point route: žiadne rozšírenie, dostal {[c['id'] for c in out_point]}")

# --- fail-safe: chýbajúci subtree_fn → vráť seedy nedotknuté ---
out_safe = expand_subtree_candidates(SEEDS, route="aggregate", index=INDEX,
                                     subtree_fn=None, children_fn=None)
if [c["id"] for c in out_safe] != [10]:
    FAILS.append(f"  bez subtree_fn → fail-safe (len seedy), dostal {[c['id'] for c in out_safe]}")

# --- dedup: susedia už v seedoch sa nepridajú dvakrát ---
seeds2 = [{"id": 10, "score": 0.9, "meta": {}}, {"id": 11, "score": 0.8, "meta": {}}]
out_dedup = expand_subtree_candidates(
    seeds2, route="aggregate", index=INDEX,
    subtree_fn=fake_subtree, children_fn=fake_children, max_seeds=2)
id_counts = {}
for c in out_dedup:
    id_counts[c["id"]] = id_counts.get(c["id"], 0) + 1
dupes = [i for i, n in id_counts.items() if n > 1]
if dupes:
    FAILS.append(f"  dedup zlyhal, duplicitné IDs: {dupes}")

if FAILS:
    print("FAIL subtree_expand:")
    for f in FAILS:
        print(f)
    sys.exit(1)
print("PASS subtree_expand: aggregate rozšíri o subtree, point NO-OP, fail-safe, audit meta, dedup")
