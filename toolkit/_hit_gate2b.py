#!/usr/bin/env python3
"""_hit_gate2b.py — GATE 2b: HiT (Oxford, WordNet-treneny hyperbolicky enkoder) na NASICH
spomienkach. Rozhodca: aj ucelovy anti-kolaps hyperbolicky model neporazi flat cosine na
nasej osobnej hierarchii? Ak nie -> problem je DOMENA (osobne fakty netvoria hlboky strom),
navzdy. Ak ano -> geometria vie vyhrat spravne postavena.

Cita geom_data.json (text+gemma) + gold_pairs_*.jsonl. Nic nezapisuje.
Metrika = rovnaka ako harness: AUROC nad pool, priemer cez deti, per lab.
"""
import os, sys, json
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)
import numpy as np

STATE = os.path.expanduser("~/projects/zolander/state")
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items()}
TEXT = {i: data[i]["text"] for i in data if "text" in data[i]}
GEMMA = {i: np.array(data[i]["gemma"], dtype="float32") for i in data if "gemma" in data[i]}

GOLDS = {"opus": "gold_pairs.jsonl", "gpt": "gold_pairs_gpt.jsonl", "gemini": "gold_pairs_gemini.jsonl"}

def load_gold(path):
    out = []
    for l in open(os.path.join(STATE, path), encoding="utf-8"):
        l = l.strip()
        if l:
            g = json.loads(l)
            if g.get("parents"):
                out.append(g)
    return out

def auroc(pos, neg):
    if not pos or not neg: return None
    c = t = 0
    for p in pos:
        for n in neg:
            if p > n: c += 1
            elif p == n: t += 1
    return (c + 0.5 * t) / (len(pos) * len(neg))

# --- HiT encode vsetkych spomienok ---
from hierarchy_transformers import HierarchyTransformer
model = HierarchyTransformer.from_pretrained("Hierarchy-Transformers/HiT-MiniLM-L12-WordNetNoun")
ids = sorted(TEXT)
emb = model.encode([TEXT[i] for i in ids], convert_to_numpy=True, show_progress_bar=False)
HIT = {i: emb[k] for k, i in enumerate(ids)}
curv = float(model.manifold.c) if hasattr(model.manifold, "c") else 1.0
print(f"HiT encoded {len(HIT)} spomienok, dim={emb.shape[1]}, curvature c={curv}")

def poincare_dist(u, v, c=1.0):
    sq = c
    diff = u - v
    num = 2 * sq * (diff @ diff)
    den = (1 - sq * (u @ u)) * (1 - sq * (v @ v))
    x = 1 + num / max(den, 1e-9)
    return np.arccosh(max(x, 1.0))

# HiT oficialny subsumption score: -(dist + w*(parent_norm - child_norm)); vacsie = viac rodic
# w z model karty ~ ladene na val; skusime rozsah a vyberieme najlepsi na kalibraciu (fair k HiT)
def hit_scores(c, pool, w):
    uc = HIT[c]; nc = np.linalg.norm(uc)
    out = {}
    for p in pool:
        up = HIT[p]; npn = np.linalg.norm(up)
        d = poincare_dist(uc, up, curv)
        out[p] = -(d + w * (npn - nc))
    return out

def cos(a, b): return float(a @ b / (np.linalg.norm(a)*np.linalg.norm(b) + 1e-9))

def eval_metric(gold, score_fn):
    aus = []
    for g in gold:
        c = g["child"]
        if c not in HIT: continue
        pool = [p for p in g["pool"] if p in HIT and p != c]
        gset = set(g["parents"]) & set(pool)
        if not gset or len(pool) < 2: continue
        sc = score_fn(c, pool)
        a = auroc([sc[p] for p in gset], [sc[p] for p in pool if p not in gset])
        if a is not None: aus.append(a)
    return (sum(aus)/len(aus) if aus else float("nan")), len(aus)

print("\nlab     | FLAT gemma | FLAT hit-cos | HiT subsumption (best w)")
print("-" * 66)
for lab, path in GOLDS.items():
    gold = load_gold(path)
    flat_gemma, n = eval_metric(gold, lambda c, pool: {p: cos(GEMMA[c], GEMMA[p]) for p in pool})
    flat_hit, _ = eval_metric(gold, lambda c, pool: {p: cos(HIT[c], HIT[p]) for p in pool})
    best_w, best_a = 0.0, -1
    for w in [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]:
        a, _ = eval_metric(gold, lambda c, pool, w=w: hit_scores(c, pool, w))
        if a > best_a: best_a, best_w = a, w
    print(f"{lab:7s} | {flat_gemma:10.3f} | {flat_hit:12.3f} | {best_a:.3f} (w={best_w}, n={n})")

print("\n=== CITAJ: ak HiT subsumption < FLAT gemma vo vsetkych laboch -> DOMENA je strop, navzdy. ===")
