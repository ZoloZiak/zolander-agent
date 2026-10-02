#!/usr/bin/env python3
"""Diagnostika: preco patterns.detect nespojil "kameru" s ulozenym vzorcom id=10.
Ukaze cely recall vystup + ldist medzi situaciou a KAZDYM ulozenym vzorcom."""
import os, sys, json
ROOT = os.path.expanduser("~/projects/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
import patterns as P

sit = "Kúpil som si drahú kameru na fotenie, nadšene som mesiac fotil, teraz leží v skrini a ani neviem kde mám nabíjačku."

print("=== recall top-8 (mode=sem) ===")
hits = P.recall(sit, topk=8, mode="sem")
for h in hits:
    txt = str(h.get("meta", {}).get("text", ""))[:55]
    print(f"  id={h.get('id')} dist={h.get('distance'):.4f} :: {txt}")

print("\n=== filter na VZOREC: prefix ===")
pats = [h for h in hits if str(h.get("meta", {}).get("text","")).startswith(P.PATTERN_PREFIX)]
print(f"  najdenych vzorcov v recall: {len(pats)}")
for p in pats:
    print(f"    id={p.get('id')} dist={p.get('distance'):.4f}")

print(f"\nMATCH_THRESHOLD={P.MATCH_THRESHOLD}  RECHECK_WINDOW={P.RECHECK_WINDOW}")
