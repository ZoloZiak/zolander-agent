#!/usr/bin/env python3
"""Offline test for EARM-style rerank cache (arXiv 2608.22767).

The same query over the same candidate payload should call the expensive LLM reranker
once, then reuse the cached order. Changing candidate text must invalidate the cache.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types

TK = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mem_rerank", os.path.join(TK, "mem_rerank.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať mem_rerank.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


print("=== EARM rerank cache ===")
fd, cache_path = tempfile.mkstemp(prefix="zol_rerank_cache_", suffix=".json")
os.close(fd)
try:
    os.unlink(cache_path)
except OSError:
    pass
os.environ["ZOL_RERANK_CACHE"] = cache_path
setattr(mr, "CACHE_PATH", cache_path)

calls = {"n": 0}


def chat(prompt, model="opus", max_tokens=200, system=None):
    calls["n"] += 1
    return "[2, 1]"


pc = types.ModuleType("palantir_client")
setattr(pc, "chat", chat)
sys.modules["palantir_client"] = pc

cands = [
    {"id": 1, "text": "prvý kandidát"},
    {"id": 2, "text": "druhý kandidát"},
]

r1 = mr.rerank("moja otázka", cands)
r2 = mr.rerank("moja otázka", cands)
if r1 != [2, 1] or r2 != [2, 1]:
    fail(f"cache má vracať rovnaké poradie [2,1], dostal {r1} a {r2}")
if calls["n"] != 1:
    fail(f"rovnaký rerank má volať LLM iba raz, volal {calls['n']}x")

# Zmena textu kandidáta mení fingerprint, takže cache nesmie vrátiť starý výsledok bez LLM.
cands_changed = [
    {"id": 1, "text": "prvý kandidát — zmenený obsah"},
    {"id": 2, "text": "druhý kandidát"},
]
mr.rerank("moja otázka", cands_changed)
if calls["n"] != 2:
    fail(f"zmenený kandidát má invalidovať cache, LLM calls={calls['n']}")

data = {}
try:
    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)
except Exception as exc:
    fail("cache súbor nie je čitateľný JSON: " + str(exc))
if not data:
    fail("cache súbor je prázdny")

print("VYSLEDOK: EARM rerank cache OK")
