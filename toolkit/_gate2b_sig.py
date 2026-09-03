#!/usr/bin/env python3
"""_gate2b_sig.py — signifikancia flat(EN) vs HiT-subsumption(EN). Paired bootstrap cez deti.
Chceme vediet: je zvysny rozdiel 0.04-0.05 REALNY alebo sum? Nerobit overclaim ani v jednom smere.
"""
import os, json
os.environ.pop("HF_HUB_OFFLINE", None); os.environ.pop("TRANSFORMERS_OFFLINE", None)
import numpy as np, urllib.request

STATE = os.path.expanduser("~/projects/zolander/state")
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items()}
EN = {int(k): v for k, v in json.load(open(os.path.join(STATE, "mem_en.json"))).items()}
GOLDS = {"opus": "gold_pairs.jsonl", "gpt": "gold_pairs_gpt.jsonl", "gemini": "gold_pairs_gemini.jsonl"}

def load_gold(path):
    out = []
    for l in open(os.path.join(STATE, path), encoding="utf-8"):
        l = l.strip()
        if l:
            g = json.loads(l)
            if g.get("parents"): out.append(g)
    return out

def auroc(pos, neg):
    if not pos or not neg: return None
    c = t = 0
    for p in pos:
        for n in neg:
            if p > n: c += 1
            elif p == n: t += 1
    return (c + 0.5*t) / (len(pos)*len(neg))

def gemma_embed(texts):
    req = urllib.request.Request("http://127.0.0.1:8901/embed",
        data=json.dumps({"texts": texts, "mode": "document"}).encode(),
        headers={"Content-Type": "application/json"})
    return np.array(json.load(urllib.request.urlopen(req, timeout=120))["vectors"], dtype="float32")

ids = sorted(i for i in EN if i in data)
GEM = {}
for s in range(0, len(ids), 128):
    ch = ids[s:s+128]; v = gemma_embed([EN[i] for i in ch])
    for k, i in enumerate(ch): GEM[i] = v[k]

from hierarchy_transformers import HierarchyTransformer
model = HierarchyTransformer.from_pretrained("Hierarchy-Transformers/HiT-MiniLM-L12-WordNetNoun")
emb = model.encode([EN[i] for i in ids], convert_to_numpy=True, show_progress_bar=False)
HIT = {i: emb[k] for k, i in enumerate(ids)}
curv = float(model.manifold.c)

def pdist(u, v, c):
    d = u - v
    return np.arccosh(max(1 + 2*c*(d@d)/max((1-c*(u@u))*(1-c*(v@v)),1e-9), 1.0))
def cos(a, b): return float(a@b/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9))

def per_child(gold, fn):
    """vrati list (child_auroc_flat, child_auroc_hit)."""
    rows = []
    for g in gold:
        c = g["child"]
        if c not in HIT: continue
        pool = [p for p in g["pool"] if p in HIT and p != c]
        gset = set(g["parents"]) & set(pool)
        if not gset or len(pool) < 2: continue
        rows.append(fn(c, pool, gset))
    return rows

def flat_a(c, pool, gset):
    sc = {p: cos(GEM[c], GEM[p]) for p in pool}
    return auroc([sc[p] for p in gset], [sc[p] for p in pool if p not in gset])
def hit_a(c, pool, gset):
    sc = {p: -pdist(HIT[c], HIT[p], curv) for p in pool}
    return auroc([sc[p] for p in gset], [sc[p] for p in pool if p not in gset])

rng = np.random.default_rng(0)
print("lab     | flat  | HiT   | diff  | 95% CI (flat-HiT)      | p(flat>HiT)")
print("-"*74)
for lab, path in GOLDS.items():
    gold = load_gold(path)
    flat = np.array([r for r in per_child(gold, flat_a) if r is not None])
    hit  = np.array([r for r in per_child(gold, hit_a)  if r is not None])
    diff = flat - hit
    n = len(diff)
    boots = np.array([diff[rng.integers(0, n, n)].mean() for _ in range(5000)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p_flat_wins = float((boots > 0).mean())
    print(f"{lab:7s} | {flat.mean():.3f} | {hit.mean():.3f} | {diff.mean():+.3f} | [{lo:+.3f}, {hi:+.3f}]        | {p_flat_wins:.3f}  (n={n})")

print("\nCI obsahuje 0 -> remiza (rozdiel je sum). CI cele nad 0 -> flat realne vyhrava.")
