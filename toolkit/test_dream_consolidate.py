#!/usr/bin/env python3
"""OSTRY test F4 consolidate() plneho cyklu (Opus). NEUKLADA nic (consolidate len
vracia destilaty; remember_l1 je az v dream()). Overuje ze epizody z 2 roznych tem
vyprodukuju 2 samostatne CISTE L1, nie 1 rozmazany.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "projects", "zolo2.0", "toolkit")) if os.path.isdir(os.path.join(os.path.expanduser("~"),"projects","zolo2.0","toolkit")) else sys.path.insert(0, os.path.join(os.path.expanduser("~"),"zolo2.0","toolkit"))
import zolander_dream as d

# 4 epizody: 2 o zdravi/behu, 2 o kode/debugovani. Rozne temy.
episodes = [
    {"id": 101, "text": "Rano som si zabehol 5km, cital som sa lepsie cely den."},
    {"id": 102, "text": "Vecer prechadzka po veceri, hlava sa mi vycistila."},
    {"id": 103, "text": "Debugoval som cross-domain bug v clusteri, embedding klamal."},
    {"id": 104, "text": "Opravil som druhy bug v detektore vzorcov cez LLM re-check."},
]
print("=== VSTUP: 4 epizody, 2 temy (pohyb/telo vs debugovanie kodu) ===")
for e in episodes:
    print(f"  [{e['id']}] {e['text']}")

print("\n=== F4 consolidate (Opus, LLM-clustering + per-skupina destilat) ===")
distilled = d.consolidate(episodes, model="opus")
print(f"\nVYSLEDOK: {len(distilled)} L1 destilatov")
for x in distilled:
    print(f"  z {x['from_ids']}: {x['text']}")

# vyhodnotenie: ocakavame 2 destilaty (2 temy), kazdy z 2 epizod
ok_count = len(distilled) == 2
ids_sets = sorted(sorted(x["from_ids"]) for x in distilled)
ok_split = ids_sets == [[101, 102], [103, 104]]
print("\n=== VYHODNOTENIE ===")
print("  2 samostatne L1 (nie 1 rozmazany):", "PASS" if ok_count else "FAIL")
print("  spravne temy [101,102] a [103,104]:", "PASS" if ok_split else f"FAIL -> {ids_sets}")
print("\nCELKOVO:", "PASS" if (ok_count and ok_split) else "FAIL")
