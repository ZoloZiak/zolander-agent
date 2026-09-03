#!/usr/bin/env python3
"""_wn_curve.py — GATE 2a: krivka ucenia Lorentz hlavy na REALNYCH WordNet is-a paroch.

Reuse train_lorentz_head.py 1:1 (monkeypatch globalov GEMMA/TEST_CH/DIM_IN). Ziadny fork
validovaneho kodu. Otazka: ked pridavam CISTE ludske is-a pary (nie Opus, nula cirkularity),
blizi sa Lorentz hlava k flat cosine (sklon HORE = data su paka) alebo plocho (strop=embedder)?

Cita state/wn_gold.json + state/wn_vecs.json. Nic nezapisuje do produkcie.
"""
import os, sys, json, random
sys.path.insert(0, os.path.expanduser("~/projects/zolander/toolkit"))
import torch
import train_lorentz_head as T

STATE = os.path.expanduser("~/projects/zolander/state")
gold = json.load(open(os.path.join(STATE, "wn_gold.json")))
vecs = json.load(open(os.path.join(STATE, "wn_vecs.json")))

# --- monkeypatch harness globalov na WordNet ---
GEMMA = {w: torch.tensor(v, dtype=torch.float32) for w, v in vecs.items()}
T.GEMMA = GEMMA
T.DIM_IN = len(next(iter(GEMMA.values())))
train_gold = [g for g in gold["train"] if g["child"] in GEMMA]
test_gold = [g for g in gold["test"] if g["child"] in GEMMA]
TRAIN_CH = {g["child"] for g in train_gold}
TEST_CH = {g["child"] for g in test_gold}
T.TRAIN_CH = TRAIN_CH
T.TEST_CH = TEST_CH

# flat baseline na test (nemeni sa s velkostou trenu)
flat_a, flat_n = T.eval_flat(test_gold, TEST_CH)
print(f"DIM_IN={T.DIM_IN}  train_deti={len(TRAIN_CH)}  test_deti={len(TEST_CH)}")
print(f"FLAT COSINE baseline (test): AUROC={flat_a:.3f} (n={flat_n})")

SIZES = [25, 50, 100, 200, 400, 800, len(TRAIN_CH)]
SEEDS = [0, 1, 2]
FULL = sorted(TRAIN_CH)

print("\nsize | HEAD AUROC(test) | HEAD-FLAT margin")
print("-" * 50)
rows = []
for size in SIZES:
    margins = []
    head_aus = []
    for sd in SEEDS:
        rr = random.Random(1000 * sd + size)
        subset = set(rr.sample(FULL, min(size, len(FULL))))
        head, ni = T.train(train_gold, subset, seed=sd)
        a, _ = T.eval_head(head, test_gold, TEST_CH)
        head_aus.append(a)
        margins.append(a - flat_a)
    m = sum(margins) / len(margins)
    ha = sum(head_aus) / len(head_aus)
    rows.append((size, m))
    print(f"{size:5d} | {ha:14.3f} | {m:+.3f}")

# sklon linearnou regresiou (margin vs log2 velkosti)
import math
xs = [math.log2(s) for s, _ in rows]
ys = [m for _, m in rows]
n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sum((x-mx)**2 for x in xs)
print(f"\n=== SKLON (margin na zdvojnasobenie dat) = {slope:+.4f} ===")
last = rows[-1][1]
print(f"posledny bod (size={rows[-1][0]}): margin={last:+.3f}")
if last > 0.01:
    print("-> HLAVA BIJE FLAT na WordNete: geometria hierarchiu VIE naucit -> tvoj token-plan ma zmysel.")
elif slope > 0.01:
    print("-> margin stale rastie so vzorkou: data su paka, viac by pomohlo.")
else:
    print("-> PLOCHO/DOLE aj na 1200 cistych WordNet detoch: strop je EMBEDDER, nie hlad po datach.")
