#!/usr/bin/env python3
"""_adapt_train.py — FÉR test: preklopí trénovanie na NAŠICH is-a hranách remízu nad flat?

Reuse train_lorentz_head.py 1:1 (disjunktny split deti = LEAK-FREE, cross-lab, multi-seed).
Menim len VSTUPNE FEATURES cez monkeypatch:
  - Arm G: Gemma-EN (nas najsilnejsi multiling zaklad, EN aby ziaden jazykovy konfaund)
  - Arm H: HiT-EN (model co uz hierarchiu z WordNetu pozna)
Oba normalizovane na jednotku (w=0 uz dokazane -> norma/hlbka nic nepridava -> testujeme SMER).
Bar = flat Gemma-EN cosine. Ziadny leak: train deti disjunktne od test deti (harness to drzi).
"""
import os, sys, json
os.environ.pop("HF_HUB_OFFLINE", None); os.environ.pop("TRANSFORMERS_OFFLINE", None)
import numpy as np, urllib.request, torch

TOOL = os.path.expanduser("~/projects/zolander/toolkit")
STATE = os.path.expanduser("~/projects/zolander/state")
sys.path.insert(0, TOOL)
import train_lorentz_head as T   # importuje harness (globaly GEMMA/DIM_IN/TRAIN_CH/TEST_CH)

EN = {int(k): v for k, v in json.load(open(os.path.join(STATE, "mem_en.json"))).items()}
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items()}
ids = sorted(i for i in EN if i in data)

# --- citaj zacacheovane features z disku (odolne voci padu daemona) ---
GEM = {int(k): np.array(v, dtype="float32")
       for k, v in json.load(open(os.path.join(STATE, "feat_gemma_en.json"))).items()}
HIT = {int(k): np.array(v, dtype="float32")
       for k, v in json.load(open(os.path.join(STATE, "feat_hit_en.json"))).items()}

def unit(v):
    v = np.asarray(v, dtype="float32"); n = np.linalg.norm(v); return v / (n + 1e-9)

FEATS = {
    "Gemma-EN": ({i: torch.tensor(unit(GEM[i])) for i in ids}, len(next(iter(GEM.values())))),
    "HiT-EN":   ({i: torch.tensor(unit(HIT[i])) for i in ids}, len(next(iter(HIT.values())))),
}

labs = ["opus", "gpt", "gemini"]
golds = {k: T.load_gold(T.GOLDS[k]) for k in labs}
SEEDS = [0, 1, 2]

def mean(xs): return sum(xs) / len(xs)
def std(xs):
    m = mean(xs); return (sum((x-m)**2 for x in xs)/len(xs))**0.5

# --- flat Gemma-EN bar (fer, pravé cosine na jednotkovych) ---
T.GEMMA = FEATS["Gemma-EN"][0]; T.DIM_IN = FEATS["Gemma-EN"][1]
flat = {}
print(f"train_deti={len(T.TRAIN_CH)}  test_deti(held-out)={len(T.TEST_CH)}  seeds={SEEDS}")
print("\n=== BAR: flat Gemma-EN cosine (held-out test deti) ===")
for tl in labs:
    a, n = T.eval_flat(golds[tl], T.TEST_CH); flat[tl] = a
    print(f"  test={tl:7s} flat={a:.3f} (n={n})")

for arm, (feats, dim) in FEATS.items():
    T.GEMMA = feats; T.DIM_IN = dim
    cell = {trl: {tel: [] for tel in labs} for trl in labs}
    for trl in labs:
        for sd in SEEDS:
            head, ni = T.train(golds[trl], T.TRAIN_CH, seed=sd)
            for tel in labs:
                a, _ = T.eval_head(head, golds[tel], T.TEST_CH)
                cell[trl][tel].append(a)
    diag = [mean(cell[l][l]) for l in labs]
    cross = [mean(cell[a][b]) for a in labs for b in labs if a != b]
    dfl = [mean(cell[l][l]) - flat[l] for l in labs]
    cfl = [mean(cell[a][b]) - flat[b] for a in labs for b in labs if a != b]
    print(f"\n=== ARM {arm}: Lorentz hlava trenovana na nasich is-a hranach (dim_in={dim}) ===")
    print(f"{'train/test':12s} " + " ".join(f"{tl:>9s}" for tl in labs))
    for trl in labs:
        print(f"{trl:12s} " + " ".join(f"{mean(cell[trl][tel]):9.3f}" for tel in labs))
    print(f"  IN-LAB  (disjunktne deti) head={mean(diag):.3f}  HEAD-FLAT={mean(dfl):+.3f}")
    print(f"  CROSS-LAB                 head={mean(cross):.3f}  HEAD-FLAT={mean(cfl):+.3f}")

print("\n=== CITAJ: HEAD-FLAT kladne (najma CROSS-LAB) -> trening NA NASICH hranach preklopil remizu. ===")
