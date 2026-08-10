#!/usr/bin/env python3
"""Izolovany test cluster() fold_singletons logiky (bez DB stavu).
Realne data: id 4,5,6 (L0 epizody, roznorode) vs id 9,10 (L2 principy, nesuvisiace).
Overuje: L0 (fold=True) -> zliaty do 1 skupiny; L2 (fold=False) -> ostanu 2 singletony."""
import os, sys
ROOT = os.path.expanduser("~/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
from ascend import load_index, cluster

l0 = [r for r in load_index() if r.get("layer") == "L0"]
l2 = [r for r in load_index() if r.get("layer") == "L2"]

g_fold = cluster(l0, fold_singletons=True)
g_nofold = cluster(l2, fold_singletons=False)

print(f"L0 fold=True  ({len(l0)} zdrojov): {len(g_fold)} skupin, velkosti {[len(g) for g in g_fold]}")
print(f"L2 fold=False ({len(l2)} zdrojov): {len(g_nofold)} skupin, velkosti {[len(g) for g in g_nofold]}")

ok_fold = len(g_fold) == 1 and len(g_fold[0]) == len(l0)
ok_nofold = len(g_nofold) == 2 and all(len(g) == 1 for g in g_nofold)
print("L0 fold zliaty do 1 skupiny:", "PASS" if ok_fold else "FAIL")
print("L2 nofold ostali 2 singletony:", "PASS" if ok_nofold else "FAIL")
print("VYSLEDOK:", "PASS" if (ok_fold and ok_nofold) else "FAIL")
