#!/usr/bin/env python3
"""Zmeria Lorentz vzdialenost medzi L2 konceptami 9 a 10 (a vsetkymi parmi)
aby sme videli aky ldist prah ma pre ascend L2->L3 zmysel."""
import os, sys, json, itertools
ROOT = os.path.expanduser("~/projects/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
from ascend import load_index, embed_many, ldist

rows = [r for r in load_index() if r.get("layer") == "L2"]
print("L2 koncepty:", [(r["id"], r["text"][:45]) for r in rows])
vecs = embed_many([r["text"] for r in rows])
for (ra, va), (rb, vb) in itertools.combinations(zip(rows, vecs), 2):
    print(f"ldist({ra['id']},{rb['id']}) = {ldist(va, vb):.4f}")
