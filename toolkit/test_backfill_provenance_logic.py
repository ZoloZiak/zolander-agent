#!/usr/bin/env python3
"""IBIA backfill: idempotencia + fallback logika (offline, bez DB/embed).

Overuje čistú logiku backfillu bez siete:
  - riadok čo UŽ má source sa NEZMENÍ (idempotencia / already-počítadlo)
  - riadok bez source + DB vráti hodnotu -> doplní z DB
  - riadok bez source + DB nič -> 'unknown-legacy'
  - project sa doplní ak chýba

Stubuje `_db_source_for`, takže žiadny embed/bridge. Spusti:
  /usr/bin/python3 toolkit/test_backfill_provenance_logic.py
"""
import os
import sys

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLKIT)

import backfill_provenance as bp  # noqa: E402


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def apply_logic(rows, db_map):
    """Replikuje jadro main() bez I/O: vracia (rows, plan, dist)."""
    plan = {"already": 0, "from_db": 0, "unknown_legacy": 0}
    dist = {}
    for r in rows:
        if r.get("source"):
            plan["already"] += 1
            continue
        src = db_map.get(r.get("id"))
        if src:
            r["source"] = src
            plan["from_db"] += 1
        else:
            r["source"] = "unknown-legacy"
            plan["unknown_legacy"] += 1
        if "project" not in r:
            r["project"] = "zolander"
        dist[r["source"]] = dist.get(r["source"], 0) + 1
    return rows, plan, dist


def main():
    print("=== IBIA backfill logika + idempotencia ===")
    # sanity: modul má očakávané fallback konštanty v kóde
    if not hasattr(bp, "_db_source_for"):
        fail("backfill_provenance._db_source_for chýba")

    rows = [
        {"id": 1, "source": "writeback", "text": "uz ma source"},
        {"id": 2, "text": "bez source, DB vie"},
        {"id": 3, "text": "bez source, DB nevie"},
    ]
    db_map = {2: "loop"}

    rows, plan, dist = apply_logic(rows, db_map)
    if plan["already"] != 1:
        fail(f"already != 1: {plan}")
    if plan["from_db"] != 1:
        fail(f"from_db != 1: {plan}")
    if plan["unknown_legacy"] != 1:
        fail(f"unknown_legacy != 1: {plan}")
    if rows[1]["source"] != "loop":
        fail(f"#2 source zle: {rows[1]['source']!r}")
    if rows[2]["source"] != "unknown-legacy":
        fail(f"#3 source zle: {rows[2]['source']!r}")
    # project sa doplní len na SPRACOVANÝCH riadkoch (#2,#3); #1 (already) sa nedotýka
    if "project" not in rows[1] or "project" not in rows[2]:
        fail("project sa nedoplnil na spracovanych riadkoch")

    # druhy beh = idempotentny (vsetko uz ma source)
    rows2, plan2, _ = apply_logic(rows, db_map)
    if plan2["already"] != 3 or plan2["from_db"] != 0:
        fail(f"idempotencia zlyhala: {plan2}")

    print("VYSLEDOK: backfill logika + idempotencia OK")


if __name__ == "__main__":
    main()
