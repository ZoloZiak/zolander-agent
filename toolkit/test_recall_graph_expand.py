#!/usr/bin/env python3
"""Offline graph recall expansion test (RippleMem 2608.13334 / GraphMemix 2608.26983).

Graph expansion must be opt-in and must add related neighbors of top recall seeds
as lower-scored evidence candidates, without duplicating existing hits.
"""
import os
import sys
import io
import json
import types
import importlib.util

_ey = types.ModuleType("embed_yar")
setattr(_ey, "embed_one", lambda text: [0.0] * 129)
sys.modules["embed_yar"] = _ey
_zp = types.ModuleType("zol_paths")
setattr(_zp, "NODE", "node")
setattr(_zp, "HS", "hs.mjs")
setattr(_zp, "NODE_ENV", {})
setattr(_zp, "ZROOT", "/tmp")
sys.modules["zol_paths"] = _zp

TK = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("zol_mem", os.path.join(TK, "zol_mem.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať zol_mem.py")
zm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zm)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


print("=== Graph recall expansion ===")
seed = {"id": 1, "score": 1.0, "meta": {"text": "seed fakt", "memory_type": "semantic"}}
index = {
    2: {"id": 2, "text": "sused dopĺňa dôkaz", "kind": "semantic", "layer": "L1", "ts": "2026-08-01T00:00:00"},
    3: {"id": 3, "text": "ďalší sused", "kind": "episodic", "layer": "L0", "ts": "2026-08-02T00:00:00"},
}


def neighbors(mid, edge=None):
    if mid == 1 and edge == "related":
        return [
            {"dir": "out", "from": 1, "to": 2, "edge": "related"},
            {"dir": "in", "from": 3, "to": 1, "edge": "related"},
            {"dir": "out", "from": 1, "to": 1, "edge": "related"},
        ]
    return []


expanded = []
try:
    expanded = zm._expand_graph_candidates([seed], index=index, neighbor_fn=neighbors, max_seeds=1, max_neighbors=2, hop_decay=0.5)
except AttributeError as exc:
    fail("zol_mem._expand_graph_candidates neexistuje: " + str(exc))

ids = [r["id"] for r in expanded]
if ids != [1, 2, 3]:
    fail(f"graph expansion má pridať dvoch related susedov za seed, dostal IDs {ids}")

by_id = {r["id"]: r for r in expanded}
if not by_id[2].get("graph_expanded") or by_id[2].get("seed_id") != 1:
    fail("sused musí niesť graph_expanded + seed_id audit meta")
if by_id[2].get("score") >= by_id[1].get("score"):
    fail("sused má mať nižšie skóre než seed")

# cmd_recall wiring: default bez graph_expand nechá len seed, opt-in pridá suseda.
def fake_hs(cmd, *args, stdin=None):
    if cmd == "search" and args and args[0] == zm.MEM_COL:
        return [{"id": 1, "distance": 0.1, "meta": {"text": "seed fakt", "memory_type": "semantic"}}]
    return []


setattr(zm, "hs", fake_hs)
setattr(zm, "embed_one", lambda text: [0.0] * 129)
setattr(zm, "_gemma_query", lambda query, fetch: [])
setattr(zm, "_filter_active_records", lambda records, include_inactive=False, active_fn=None: records)
setattr(zm, "_graph_index_by_id", lambda: index)

_ml = types.ModuleType("mem_lexical")
setattr(_ml, "search", lambda query, topk=10: [])
sys.modules["mem_lexical"] = _ml
_zg = types.ModuleType("zol_graph")
setattr(_zg, "neighbors", neighbors)
sys.modules["zol_graph"] = _zg


def run_recall(payload):
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(payload))
    buf = io.StringIO()
    sys.stdout = buf
    try:
        zm.cmd_recall()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return json.loads(buf.getvalue())

plain = run_recall({"query": "seed", "topk": 5, "rerank": False, "no_gemma": True, "no_lexical": True})
plain_ids = [r["id"] for r in plain]
if plain_ids != [1]:
    fail(f"graph_expand má byť default OFF, dostal IDs {plain_ids}")

graph = run_recall({"query": "seed", "topk": 5, "rerank": False, "no_gemma": True, "no_lexical": True, "graph_expand": True})
graph_ids = [r["id"] for r in graph]
if graph_ids != [1, 2, 3]:
    fail(f"graph_expand=True má pridať susedov, dostal IDs {graph_ids}")

print("VYSLEDOK: graph recall expansion OK")
