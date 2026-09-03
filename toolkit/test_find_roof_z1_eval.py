#!/usr/bin/env python3
"""Offline Z1 placement harness test (Lorentz ŽL1 / arXiv watcher backlog).

The harness must measure flat cosine placement vs the ordinal Z1 gate on explicit
child→gold-parent cases. Synthetic fixture: a high-cosine sibling distractor should win
flat ranking, but be removed by r[parent] < r[child], letting the true parent win.
"""
import importlib.util
import os
import sys

TK = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("find_roof", os.path.join(TK, "find_roof.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať find_roof.py")
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


print("=== Z1 placement harness ===")
# r: menšie = vyššie/všeobecnejšie. Kandidát 2 je viac podobný, ale je súrodenec/špecifickejší.
r = {10: 0.90, 1: 0.20, 2: 0.95, 3: 0.70}
case = {
    "child": 10,
    "gold": 1,
    "candidates": [
        {"id": 2, "score": 0.99},
        {"id": 1, "score": 0.80},
        {"id": 3, "score": 0.60},
    ],
}

ranked = []
try:
    ranked = fr.rank_with_z1_gate(case["child"], case["candidates"], r)
except AttributeError as exc:
    fail("find_roof.rank_with_z1_gate neexistuje: " + str(exc))

if [c["id"] for c in ranked] != [1, 3]:
    fail(f"Z1 gate má odstrániť kandidáta 2 a zachovať poradie [1,3], dostal {ranked}")

metrics = {}
try:
    metrics = fr.evaluate_z1_gate([case], r)
except AttributeError as exc:
    fail("find_roof.evaluate_z1_gate neexistuje: " + str(exc))

if metrics.get("flat_r1") != 0.0:
    fail(f"flat baseline má na fixture zlyhať, metrics={metrics}")
if metrics.get("z1_r1") != 1.0:
    fail(f"Z1 gate má na fixture trafiť gold parenta, metrics={metrics}")
if metrics.get("delta_r1") != 1.0:
    fail(f"delta_r1 má byť +1.0, metrics={metrics}")
if metrics.get("n") != 1:
    fail(f"n má byť 1, metrics={metrics}")

print("VYSLEDOK: Z1 placement harness OK")
