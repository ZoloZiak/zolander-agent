#!/usr/bin/env python3
"""test_when_gate.py — ŽL5 temporálny prefilter (kolo31, ŽL cesta zo scout backlogu).

When-gate sa zapína, keď query_router povie route=temporal ("kedy / aktuálne /
posledný stav X"). Pred fúziou skóre prefiltruje kandidátov podľa bitemporal
stavu z zol_graph._temporal_state():
  - superseded záznam (valid_until != None) sa pri temporal dotaze POTLAČÍ
    (nechceme vrátiť neaktuálny fakt na otázku "aká je AKTUÁLNA adresa")
  - survivor (valid_until == None) prejde
  - StateMem precondition: current-state filter už existuje; toto je jeho
    dotazovo-podmienený variant (hard filter LEN keď sa pýtaš na aktuálnosť).

Iron law (TDD): napísané PRED when_gate(), musí zlyhať ImportErrorom.

Beh: /usr/bin/python3 toolkit/test_when_gate.py   (offline, in-memory temporal)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from when_gate import when_gate

FAILS = []

# in-memory bitemporal stav: id 100 superseded id 200 (200 je starý, 100 žije)
TEMPORAL = {
    200: {"id": 200, "valid_until": "2026-08-31T20:00:00", "superseded_by": 100},
    100: {"id": 100, "valid_until": None, "superseded_by": None},
    300: {"id": 300, "valid_until": None, "superseded_by": None},
}

# kandidáti z recall (id, skóre) — 200 (starý) má vyššie skóre než 100 (nový)
CANDS = [
    {"id": 200, "score": 0.9, "meta": {"text": "adresa A"}},
    {"id": 100, "score": 0.7, "meta": {"text": "adresa B"}},
    {"id": 300, "score": 0.5, "meta": {"text": "iný fakt"}},
]

# --- TEMPORAL route: superseded 200 sa POTLAČÍ ---
out = when_gate(CANDS, TEMPORAL, route="temporal")
ids = [c["id"] for c in out]
if 200 in ids:
    FAILS.append(f"  temporal route: superseded id 200 mal byť potlačený, dostal {ids}")
if 100 not in ids or 300 not in ids:
    FAILS.append(f"  temporal route: survivor 100/300 mali prejsť, dostal {ids}")

# --- POINT route: when-gate NEZASAHUJE (flat recall ostáva nedotknutý) ---
out_point = when_gate(CANDS, TEMPORAL, route="point")
if [c["id"] for c in out_point] != [200, 100, 300]:
    FAILS.append(f"  point route: when-gate nemá zasahovať, dostal {[c['id'] for c in out_point]}")

# --- FAIL-OPEN: prázdny temporal stav → nič sa nefiltruje ---
out_empty = when_gate(CANDS, {}, route="temporal")
if len(out_empty) != 3:
    FAILS.append(f"  prázdny temporal stav → fail-open (nechaj všetko), dostal {len(out_empty)}")

# --- neznámy id (nie je v temporal) → treated as active, prejde ---
cands2 = [{"id": 999, "score": 0.8, "meta": {}}]
out2 = when_gate(cands2, TEMPORAL, route="temporal")
if [c["id"] for c in out2] != [999]:
    FAILS.append(f"  neznámy id (bez temporal záznamu) = aktívny, mal prejsť, dostal {[c['id'] for c in out2]}")

# --- audit: potlačené kandidáty sa nezahodia ticho, vráti sa dôvod ---
out3, dropped = when_gate(CANDS, TEMPORAL, route="temporal", return_dropped=True)
if 200 not in [d["id"] for d in dropped]:
    FAILS.append(f"  return_dropped: potlačené id 200 má byť v dropped zozname, dostal {[d['id'] for d in dropped]}")
if not dropped or "superseded_by" not in dropped[0]:
    FAILS.append("  return_dropped: dropped záznam má niesť dôvod (superseded_by)")

if FAILS:
    print("FAIL when_gate:")
    for f in FAILS:
        print(f)
    sys.exit(1)
print("PASS when_gate: superseded potlačený pri temporal, point nedotknutý, fail-open, audit dropped")
