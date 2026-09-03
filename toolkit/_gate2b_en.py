#!/usr/bin/env python3
"""_gate2b_en.py — GATE 2b BEZ JAZYKOVEHO KONFAUNDU.
Oba modely dostanu TU ISTU ANGLICTINU (preklad z mem_en.json):
  - HiT (anglicky WordNet enkoder) encode(EN)
  - Gemma (multiling) embed EN cez daemon :8901
Ak HiT prehra flat cosine aj na ANGLICTINE -> verdikt drzi (domena, nie jazyk).
Ak vyhra -> Gate 2b bol kontaminovany jazykom.
"""
import os, json, sys, urllib.request
os.environ.pop("HF_HUB_OFFLINE", None); os.environ.pop("TRANSFORMERS_OFFLINE", None)
import numpy as np

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
    return (c + 0.5 * t) / (len(pos) * len(neg))

# --- Gemma embed EN cez daemon ---
def gemma_embed(texts):
    req = urllib.request.Request("http://127.0.0.1:8901/embed",
        data=json.dumps({"texts": texts, "mode": "document"}).encode(),
        headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=120))
    return np.array(r["vectors"], dtype="float32")

ids = sorted(i for i in EN if i in data)
print(f"EN textov: {len(ids)}")
GEM_EN = {}
B = 128
for s in range(0, len(ids), B):
    chunk = ids[s:s+B]
    vecs = gemma_embed([EN[i] for i in chunk])
    for k, i in enumerate(chunk): GEM_EN[i] = vecs[k]
print("Gemma EN embed OK")

# --- HiT encode EN ---
from hierarchy_transformers import HierarchyTransformer
model = HierarchyTransformer.from_pretrained("Hierarchy-Transformers/HiT-MiniLM-L12-WordNetNoun")
emb = model.encode([EN[i] for i in ids], convert_to_numpy=True, show_progress_bar=False)
HIT = {i: emb[k] for k, i in enumerate(ids)}
curv = float(model.manifold.c) if hasattr(model.manifold, "c") else 1.0
print(f"HiT EN encode OK, dim={emb.shape[1]}, c={curv}")

def poincare_dist(u, v, c=1.0):
    diff = u - v
    num = 2 * c * (diff @ diff)
    den = (1 - c * (u @ u)) * (1 - c * (v @ v))
    return np.arccosh(max(1 + num / max(den, 1e-9), 1.0))

def hit_scores(cc, pool, w):
    uc = HIT[cc]; nc = np.linalg.norm(uc); out = {}
    for p in pool:
        up = HIT[p]; npn = np.linalg.norm(up)
        out[p] = -(poincare_dist(uc, up, curv) + w * (npn - nc))
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

print("\nlab     | FLAT gemma(EN) | FLAT hit-cos(EN) | HiT subsumption(EN, best w)")
print("-" * 72)
for lab, path in GOLDS.items():
    gold = load_gold(path)
    fg, n = eval_metric(gold, lambda c, pool: {p: cos(GEM_EN[c], GEM_EN[p]) for p in pool})
    fh, _ = eval_metric(gold, lambda c, pool: {p: cos(HIT[c], HIT[p]) for p in pool})
    bw, ba = 0.0, -1
    for w in [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]:
        a, _ = eval_metric(gold, lambda c, pool, w=w: hit_scores(c, pool, w))
        if a > ba: ba, bw = a, w
    print(f"{lab:7s} | {fg:14.3f} | {fh:16.3f} | {ba:.3f} (w={bw}, n={n})")

print("\n=== Ak HiT subsumption < FLAT gemma(EN) aj TERAZ -> domena je strop, jazyk to nebol. ===")
