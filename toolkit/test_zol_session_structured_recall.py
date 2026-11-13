#!/usr/bin/env python3
"""Regression test for Structured Memory recall injection (arXiv 2608.08300).

Session-start recall should not be a flat soup. It must be grouped by memory_type
so identity/procedural/semantic/episodic records stay in separate trust/context
buckets before they hit the model prompt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_session as zs  # noqa: E402

fails = []


def check(name, cond):
    print(f"  {'ok' if cond else 'FAIL'}  {name}")
    if not cond:
        fails.append(name)


hits = [
    {"id": 1, "score": 0.95, "meta": {"memory_type": "episodic", "text": "epizóda o debuggingu"}},
    {"id": 2, "distance": 0.12, "meta": {"kind": "identity", "text": "Zolander je zrkadlo, nie poťapkávač"}},
    {"id": 3, "score": 0.77, "meta": {"memory_type": "procedural", "text": "sandbox shell príkazy sú atomické"}},
    {"id": 4, "score": 0.66, "meta": {"memory_type": "semantic", "text": "BM25 robí ťažkú prácu v recalli"}},
]

print("=== Structured session recall ===")
try:
    rendered = zs.format_recall_hits(hits)
except AttributeError as exc:
    print("FAIL missing helper:", exc)
    sys.exit(1)

print(rendered)

check("má identity sekciu", "PAMÄŤ — identity" in rendered)
check("má procedural sekciu", "PAMÄŤ — procedural" in rendered)
check("má semantic sekciu", "PAMÄŤ — semantic" in rendered)
check("má episodic sekciu", "PAMÄŤ — episodic" in rendered)
check("identity je pred episodic", rendered.index("PAMÄŤ — identity") < rendered.index("PAMÄŤ — episodic"))
check("riadky nesú id", "#2" in rendered and "#1" in rendered)
check("nie je to starý flat formát", "[identity" not in rendered and "[episodic" not in rendered)

print(f"\n{'VYSLEDOK: structured recall OK' if not fails else 'VYSLEDOK: FAIL ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
