#!/usr/bin/env python3
"""_lc_probe.py — KRIVKA UCENIA hlavy: margin (HEAD-FLAT) vs pocet trenovacich deti.

Reuse harness z train_lorentz_head.py. Meni len velkost TRAIN podmnoziny.
Otazka: ked pridavam data, blizi sa hlava k flat cosine (sklon HORE = oplati sa palit
tokeny na viac dat) alebo je plocho/dole (strop je domena, viac dat nepomoze)?

Zero LLM. Cita geom_data.json + gold_pairs_*.jsonl. Nic nezapisuje.
"""
import os, sys, json, random, statistics
sys.path.insert(0, os.path.expanduser("~/projects/zolander/toolkit"))
import train_lorentz_head as T

LABS = ["opus", "gpt", "gemini"]
GOLDS = {k: T.load_gold(T.GOLDS[k]) for k in LABS}
FULL_TRAIN = sorted(T.TRAIN_CH)
SIZES = [8, 16, 24, 32, 40, len(FULL_TRAIN)]
SEEDS = [0, 1, 2]

# flat baseline na TEST split (nemeni sa s velkostou trenu)
flat = {}
for tl in LABS:
    a, n = T.eval_flat(GOLDS[tl], T.TEST_CH)
    flat[tl] = a
print(f"FULL_TRAIN={len(FULL_TRAIN)}  TEST={len(T.TEST_CH)}  seeds={SEEDS}")
print("FLAT baseline (test):", {k: round(v, 3) for k, v in flat.items()})
print("\nsize | in-lab margin | cross-lab margin | hlava_AUROC(in) | flat(in)")
print("-" * 72)

rows = []
for size in SIZES:
    inlab_margins = []
    cross_margins = []
    for trl in LABS:
        for sd in SEEDS:
            # deterministicka podmnozina trenovacich deti danej velkosti
            rr = random.Random(1000 * sd + size)
            subset = set(rr.sample(FULL_TRAIN, min(size, len(FULL_TRAIN))))
            head, ni = T.train(GOLDS[trl], subset, seed=sd)
            for tel in LABS:
                a, _ = T.eval_head(head, GOLDS[tel], T.TEST_CH)
                m = a - flat[tel]
                if trl == tel:
                    inlab_margins.append(m)
                else:
                    cross_margins.append(m)
    inm = statistics.mean(inlab_margins)
    crm = statistics.mean(cross_margins)
    # priemerne hlava AUROC in-lab pre kontext
    rows.append((size, inm, crm))
    print(f"{size:4d} | {inm:+13.3f} | {crm:+16.3f} |")

# sklon: linearna regresia margin vs size (in-lab aj cross)
def slope(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0

xs = [r[0] for r in rows]
sl_in = slope(xs, [r[1] for r in rows])
sl_cr = slope(xs, [r[2] for r in rows])
print("\n=== SKLON (margin na +1 dieta) ===")
print(f"  in-lab   sklon = {sl_in:+.5f}  (za +50 deti ~ {sl_in*50:+.3f})")
print(f"  cross-lab sklon = {sl_cr:+.5f}  (za +50 deti ~ {sl_cr*50:+.3f})")

# projekcia: ak by sklon drzal, kolko deti na prekrocenie 0 (cross)
last = rows[-1]
print(f"\n  posledny bod (size={last[0]}): in-lab {last[1]:+.3f}, cross {last[2]:+.3f}")
if sl_cr > 0.0002 and last[2] < 0:
    need = last[0] + (-last[2]) / sl_cr
    print(f"  -> cross sklon KLADNY: extrapolacia prekroci 0 pri ~{need:.0f} detoch")
    print("     VERDIKT: viac dat by pomohlo -> palit tokeny na korpus MA zmysel.")
elif sl_cr <= 0.0002:
    print("  -> cross sklon ~0 alebo dole: viac dat NEZACHRANI, strop je domena/rozmazanost.")
    print("     VERDIKT: palit tokeny na viac osobnych faktov = do vetra. Treba INY typ dat.")
