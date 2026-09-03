#!/usr/bin/env python3
"""Offline test for Weighted Memory Tree recall-hit telemetry (arXiv 2608.20631).

Before salience bumps, recall must emit a read-only event containing used memory IDs.
It must not persist raw query text because recall queries can contain private/secrety user input.
"""
import importlib.util
import io
import json
import os
import sys
import types

_ey = types.ModuleType("embed_yar")
setattr(_ey, "embed_one", lambda text: [0.0] * 129)
sys.modules["embed_yar"] = _ey
_zp = types.ModuleType("zol_paths")
setattr(_zp, "NODE", "node")
setattr(_zp, "HS", "hs.mjs")
setattr(_zp, "NODE_ENV", {})
setattr(_zp, "ZROOT", "/tmp")
sys.modules["zol_paths"] = _zp

EVENTS = []
_ze = types.ModuleType("zol_events")
setattr(_ze, "emit", lambda source, event, data=None, run_id=None: EVENTS.append({
    "source": source,
    "event": event,
    "data": data or {},
    "run_id": run_id,
}))
sys.modules["zol_events"] = _ze

TK = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("zol_mem", os.path.join(TK, "zol_mem.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať zol_mem.py")
zm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zm)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


print("=== Recall hit telemetry ===")


def fake_hs(cmd, *args, stdin=None):
    if cmd == "search" and args and args[0] == zm.MEM_COL:
        return [
            {"id": 11, "distance": 0.1, "meta": {"text": "alpha", "memory_type": "semantic"}},
            {"id": 12, "distance": 0.2, "meta": {"text": "beta", "memory_type": "episodic"}},
        ]
    return []


setattr(zm, "hs", fake_hs)
setattr(zm, "embed_one", lambda text: [0.0] * 129)
setattr(zm, "_gemma_query", lambda query, fetch: [])
setattr(zm, "_filter_active_records", lambda records, include_inactive=False, active_fn=None: records)
_ml = types.ModuleType("mem_lexical")
setattr(_ml, "search", lambda query, topk=10: [])
sys.modules["mem_lexical"] = _ml

secret_query = "kde je API_TOKEN=super-secret-v-chat-e toto nesmie ísť do telemetry"
old_stdin, old_stdout = sys.stdin, sys.stdout
sys.stdin = io.StringIO(json.dumps({
    "query": secret_query,
    "topk": 2,
    "rerank": False,
    "no_gemma": True,
    "no_lexical": True,
}))
buf = io.StringIO()
sys.stdout = buf
try:
    zm.cmd_recall()
finally:
    sys.stdin, sys.stdout = old_stdin, old_stdout

out = json.loads(buf.getvalue())
if [r["id"] for r in out] != [11, 12]:
    fail(f"test harness očakáva recall ids [11,12], dostal {out}")
if len(EVENTS) != 1:
    fail(f"recall má emitnúť práve jeden telemetry event, dostal {len(EVENTS)}")
ev = EVENTS[0]
if ev.get("source") != "memory" or ev.get("event") != "recall_hits":
    fail(f"zlý event typ: {ev}")
data = ev.get("data", {})
if data.get("ids") != [11, 12]:
    fail(f"telemetry musí niesť recall ids [11,12], dostal {data}")
blob = json.dumps(data, ensure_ascii=False)
if "super-secret" in blob or secret_query in blob or "API_TOKEN" in blob:
    fail("telemetry nesmie ukladať raw query/secrety")
if not data.get("query_hash"):
    fail("telemetry má niesť query_hash namiesto raw query")

print("VYSLEDOK: recall hit telemetry OK")


# ── source propagation (spike 012): audit musí vedieť KTO volal ──────────────
print("=== Recall source propagation ===")

EVENTS.clear()
old_stdin, old_stdout = sys.stdin, sys.stdout
sys.stdin = io.StringIO(json.dumps({
    "query": "kontext dotaz",
    "topk": 2,
    "rerank": False,
    "no_gemma": True,
    "no_lexical": True,
    "source": "initiative",
}))
buf = io.StringIO()
sys.stdout = buf
try:
    zm.cmd_recall()
finally:
    sys.stdin, sys.stdout = old_stdin, old_stdout

if len(EVENTS) != 1:
    fail(f"recall má emitnúť jeden event, dostal {len(EVENTS)}")
sdata = EVENTS[0].get("data", {})
if sdata.get("source") != "initiative":
    fail(f"recall_hits musí niesť source volajúceho, dostal {sdata.get('source')!r}")

# default: bez source v obj → 'adhoc' (nie chýbajúce pole, nech audit vždy vie triediť)
EVENTS.clear()
old_stdin, old_stdout = sys.stdin, sys.stdout
sys.stdin = io.StringIO(json.dumps({
    "query": "kontext dotaz",
    "topk": 2,
    "rerank": False,
    "no_gemma": True,
    "no_lexical": True,
}))
buf = io.StringIO()
sys.stdout = buf
try:
    zm.cmd_recall()
finally:
    sys.stdin, sys.stdout = old_stdin, old_stdout

ddata = EVENTS[0].get("data", {})
if ddata.get("source") != "adhoc":
    fail(f"bez source v obj má recall_hits default 'adhoc', dostal {ddata.get('source')!r}")

print("VYSLEDOK: recall source propagation OK")
