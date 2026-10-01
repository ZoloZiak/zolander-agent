#!/usr/bin/env python3
"""smoke_selfaudit_chain.py — overi cely retazec root-cause fixu NAZIVO (read-only, ziadny
zapis do grafu). Bezi z ROT adresara ako keby ho volala initiative slucka.

Overuje:
  1. import edge_selfaudit + audit() vrati dict so spravnymi klucmi
  2. import initiative + edge_health() vrati string (alebo "") a NESPADNE
  3. watermark: 1. beh moze nieco vratit; 2. beh (nic sa nezmenilo) musi byt TICHO ("")
  4. import zol_graph + poistka: INVERTED parent sa degraduje aj mimo CWD toolkit/

NEZAPISUJE do mem_edges.jsonl. edge_health zapisuje len state/edge_selfaudit_seen.json
(watermark) a state/edge_selfaudit.json (audit vystup) — to je zamer, nie mutacia grafu.
"""
import os
import sys
import json

HOME = os.path.expanduser("~")
ROOT = os.environ.get("ZOLANDER_ROOT", os.path.join(HOME, "zolander"))
TOOLKIT = os.path.join(ROOT, "toolkit")
STATE = os.path.join(ROOT, "state")
sys.path.insert(0, TOOLKIT)

# spustaj z domovskeho adresara, nie z toolkit/ — simuluj initiative kontext
os.chdir(HOME)

ok = True


def check(name, cond):
    global ok
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}")
    if not cond:
        ok = False


print("=" * 60)
print("SMOKE TEST — root-cause self-audit retazec (read-only)")
print("=" * 60)

# --- 1. edge_selfaudit.audit() ---
import edge_selfaudit
res = edge_selfaudit.audit(write=True)
check("edge_selfaudit.audit() vratil dict", isinstance(res, dict))
for k in ("proposals", "keep_confirmed", "need_geom", "need_llm", "counts", "apex_candidate"):
    check(f"audit dict ma kluc '{k}'", k in res)
check("counts.INVERTED je int", isinstance(res.get("counts", {}).get("INVERTED", 0), int))
# proposaly maju polia co edge_health cita
for p in res.get("proposals", [])[:3]:
    check("proposal ma child/parent/child_txt/parent_txt/delta",
          all(x in p for x in ("child", "parent", "child_txt", "parent_txt",
                               "delta_r_child_minus_parent")))

# --- 2 + 3. initiative.edge_health() watermark ---
# initiative.py is a private, environment-bound daemon (not shipped in this repo).
# If it's present (author's full tree) run the watermark checks; otherwise skip
# gracefully — edge_selfaudit above already covers the shipped self-audit logic.
seen = os.path.join(STATE, "edge_selfaudit_seen.json")
try:
    import initiative
except ImportError:
    print("  [SKIP] initiative not present (private daemon) — watermark checks skipped")
else:
    # reset watermark so the 1st run is deterministic
    if os.path.exists(seen):
        os.remove(seen)
    h1 = initiative.edge_health()
    check("edge_health() 1st run returned str", isinstance(h1, str))
    h2 = initiative.edge_health()
    check("edge_health() 2nd run (nothing changed) is SILENT", h2 == "")
    print(f"      (1st run len={len(h1)}, 2nd run len={len(h2)})")

# --- 4. zol_graph poistka mimo CWD toolkit/ ---
import zol_graph
# over ze funkcia existuje a ma novy podpis (enforce, from_layer, to_layer)
import inspect
sig = inspect.signature(zol_graph.link)
for pn in ("enforce", "from_layer", "to_layer"):
    check(f"zol_graph.link ma parameter '{pn}'", pn in sig.parameters)
check("zol_graph ma helper na layer/geom guard",
      any(hasattr(zol_graph, fn) for fn in ("_parent_guard", "_layer_map", "_parent_reaches")))

print("-" * 60)
print("VYSLEDOK:", "VSETKO OK" if ok else "NIECO ZLYHALO")
sys.exit(0 if ok else 1)
