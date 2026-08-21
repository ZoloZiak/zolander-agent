#!/usr/bin/env python3
"""test_reparent.py — edge-case testy pre zol_graph.reparent.

Reparent presmeruje hrany zmazaneho uzla na keepera PRED tym nez dedup_dream
zmaze bod z DB (aby deti neosireli). Tieto testy overuju ze to nerobi skodu
v okrajovych pripadoch: dead==keeper, cyklus v parent-hierarchii, prazdny beh,
idempotencia. Spusti: /usr/bin/python3 test_reparent.py
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_graph as g

FAILS = []

def _run(seed, dead, keeper):
    tmp = tempfile.mktemp(suffix=".jsonl")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in seed:
            f.write(json.dumps(e) + "\n")
    g.EDGES = tmp
    res = g.reparent(dead, keeper)
    after = g._read(tmp)
    os.remove(tmp)
    return res, after

def check(name, cond, detail=""):
    tag = "OK  " if cond else "FAIL"
    if not cond:
        FAILS.append(f"{name}: {detail}")
    print(f"  [{tag}] {name}" + (f" — {detail}" if not cond else ""))

def _has_cycle_parent(edges):
    """Je v parent-podgrafe cyklus? (DFS na orientovanom grafe from->to)"""
    adj = {}
    for e in edges:
        if e.get("edge") == "parent":
            adj.setdefault(e["from"], []).append(e["to"])
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            c = color.get(v, WHITE)
            if c == GRAY:
                return True
            if c == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False
    for n in list(adj):
        if color.get(n, WHITE) == WHITE and dfs(n):
            return True
    return False


print("T1: happy path — deti prevesene, self-loop + dup zahodene")
seed = [
    {"from": 606, "to": 559, "edge": "related"},
    {"from": 600, "to": 606, "edge": "parent"},
    {"from": 601, "to": 606, "edge": "parent"},
    {"from": 602, "to": 606, "edge": "parent"},
    {"from": 557, "to": 559, "edge": "parent"},
    {"from": 559, "to": 571, "edge": "parent"},
    {"from": 600, "to": 559, "edge": "parent"},  # uz existuje -> dup po prevesani
    {"from": 999, "to": 888, "edge": "related"},
]
res, after = _run(seed, 606, 559)
cp = sorted(e["to"] for e in after if e["edge"] == "parent" and e["from"] in (600, 601, 602))
check("deti->559", cp == [559, 559, 559], f"cp={cp}")
check("ziadny selfloop", not any(e["from"] == e["to"] for e in after))
check("ziadna dead hrana", not any(606 in (e["from"], e["to"]) for e in after))
check("cudzia hrana ostala", any(e["from"] == 999 for e in after))
check("migrated=2", res["migrated"] == 2, f"{res['migrated']}")
check("dropped_dup=1", res["dropped_dup"] == 1, f"{res['dropped_dup']}")

print("T2: dead == keeper — NESMIE vygumovat hrany")
seed = [
    {"from": 5, "to": 10, "edge": "parent"},
    {"from": 10, "to": 20, "edge": "parent"},
]
res, after = _run(seed, 10, 10)
check("hrany zachovane", len(after) == 2, f"ostalo {len(after)}")

print("T3: cyklus — keeper je potomok dead (keeper->M->dead)")
# 559 -> 700 -> 606 ; zmazem 606, keeper 559. Hrana 700->606 sa stane 700->559.
# Vznikne 559->700->559 = CYKLUS. reparent to NESMIE vytvorit.
seed = [
    {"from": 559, "to": 700, "edge": "parent"},   # keeper je dieta 700
    {"from": 700, "to": 606, "edge": "parent"},   # 700 je dieta dead
    {"from": 601, "to": 606, "edge": "parent"},   # bezne dieta dead
]
res, after = _run(seed, 606, 559)
check("ziadny parent-cyklus", not _has_cycle_parent(after),
      f"edges={[(e['from'],e['to']) for e in after if e['edge']=='parent']}")
check("cyklicka hrana zahodena (dropped_cycle=1)", res["dropped_cycle"] == 1,
      f"{res.get('dropped_cycle')}")
check("bezne dieta 601->559 prevesene",
      any(e["from"] == 601 and e["to"] == 559 for e in after))

print("T4: prazdny beh — dead nie je v grafe")
seed = [{"from": 1, "to": 2, "edge": "parent"}]
res, after = _run(seed, 999, 1)
check("migrated=0", res["migrated"] == 0, f"{res['migrated']}")
check("graf nezmeneny", len(after) == 1 and after[0]["from"] == 1)

print("T5: idempotencia — 2. beh s uz zmazanym dead")
seed = [
    {"from": 601, "to": 606, "edge": "parent"},
    {"from": 559, "to": 571, "edge": "parent"},
]
tmp = tempfile.mktemp(suffix=".jsonl")
with open(tmp, "w", encoding="utf-8") as f:
    for e in seed:
        f.write(json.dumps(e) + "\n")
g.EDGES = tmp
g.reparent(606, 559)
res2 = g.reparent(606, 559)  # 2. beh
after = g._read(tmp)
os.remove(tmp)
check("2. beh migrated=0", res2["migrated"] == 0, f"{res2['migrated']}")
check("dieta stale na 559", any(e["from"] == 601 and e["to"] == 559 for e in after))

print("T6: obojsmerne hrany dead<->keeper (oba smery related)")
seed = [
    {"from": 606, "to": 559, "edge": "related"},
    {"from": 559, "to": 606, "edge": "related"},
    {"from": 601, "to": 606, "edge": "parent"},
]
res, after = _run(seed, 606, 559)
check("oba selfloop zahodene", not any(e["from"] == e["to"] for e in after))
check("dieta prevesene", any(e["from"] == 601 and e["to"] == 559 for e in after))

print()
if FAILS:
    print(f"VYSLEDOK: {len(FAILS)} FAIL(ov):")
    for x in FAILS:
        print("  - " + x)
    sys.exit(1)
print("VYSLEDOK: vsetky testy OK")
