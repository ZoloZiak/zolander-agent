#!/usr/bin/env python3
"""Regression test for StateMem-style current-state recall (arXiv 2608.19652).

Superseded memories should not be injected by default. Historical records remain
available only when the caller explicitly asks for include_inactive=true.
"""
import os
import sys
import io
import json
import types
import importlib.util

# Stub heavy/local dependencies so this stays an offline unit test.
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


candidates = [
    {"id": 10, "score": 0.9, "meta": {"text": "starý prenájom už neplatí"}},
    {"id": 11, "score": 0.8, "meta": {"text": "aktuálny prenájom platí"}},
]

temporal = {
    10: {"id": 10, "valid_until": "2026-08-01T00:00:00", "superseded_by": 11},
    11: {"id": 11, "valid_until": None, "superseded_by": None},
}


def active_fn(mid):
    st = temporal.get(mid)
    return (not st or st.get("valid_until") is None), st


try:
    default_filtered = zm._filter_active_records(candidates, active_fn=active_fn)
except AttributeError as exc:
    fail("zol_mem._filter_active_records neexistuje: " + str(exc))

ids = [r["id"] for r in default_filtered]
if ids != [11]:
    fail(f"default recall má vyhodiť superseded záznamy, dostal IDs {ids}")

kept = zm._filter_active_records(candidates, include_inactive=True, active_fn=active_fn)
kept_ids = [r["id"] for r in kept]
if kept_ids != [10, 11]:
    fail(f"include_inactive=True má ponechať históriu, dostal IDs {kept_ids}")

if "_temporal" not in default_filtered[0]:
    fail("aktívny výstup má niesť temporal info pre audit")

# End-to-end cmd_recall smoke with all heavy lanes stubbed: default excludes old,
# include_inactive keeps history. This proves the helper is actually wired.
def fake_hs(cmd, *args, stdin=None):
    if cmd == "search" and args and args[0] == zm.MEM_COL:
        return [
            {"id": 10, "distance": 0.1, "meta": {"text": "starý prenájom už neplatí", "memory_type": "semantic"}},
            {"id": 11, "distance": 0.2, "meta": {"text": "aktuálny prenájom platí", "memory_type": "semantic"}},
        ]
    return []


setattr(zm, "hs", fake_hs)
setattr(zm, "embed_one", lambda text: [0.0] * 129)
setattr(zm, "_gemma_query", lambda query, fetch: [])

_ml = types.ModuleType("mem_lexical")
setattr(_ml, "search", lambda query, topk=10: [])
sys.modules["mem_lexical"] = _ml

_zg = types.ModuleType("zol_graph")
setattr(_zg, "is_active", active_fn)
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


default_cmd = run_recall({"query": "prenájom", "topk": 5, "rerank": False, "no_gemma": True, "no_lexical": True})
default_cmd_ids = [r["id"] for r in default_cmd]
if default_cmd_ids != [11]:
    fail(f"cmd_recall default má vyhodiť superseded, dostal IDs {default_cmd_ids}")

history_cmd = run_recall({"query": "prenájom", "topk": 5, "rerank": False, "no_gemma": True, "no_lexical": True, "include_inactive": True})
history_cmd_ids = [r["id"] for r in history_cmd]
if history_cmd_ids != [10, 11]:
    fail(f"cmd_recall include_inactive má ponechať históriu, dostal IDs {history_cmd_ids}")

print("VYSLEDOK: recall current-state filter OK")
