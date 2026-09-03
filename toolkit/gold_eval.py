#!/usr/bin/env python3
"""gold_eval.py — retrieval eval proti NEZAVISLEMU goldu (gold_pairs.jsonl).

KROK 2 (DIAGNOSTIKA, najdolezitejsie cislo): kolko %% opus-goldu ma layer(parent)>layer(child)?
  vysoke -> layer je dobry proxy, povodny verdikt STOJI.
  nizke  -> layer klame, opus SPOJITY polomer ma priestor -> mozny ZVRAT.

KROK 3: pre kazde dieta skoruj VSETKYCH kandidatov z jeho poolu (fer, rovnaka mnozina)
  4 variantmi. Metrika: da pravemu rodicovi vyssie skore nez ne-rodicom v poole?
  -> per-child AUROC (parent vs pool-non-parent) + MRR pravemu rodicovi."""
import json, os, sys, math, random, argparse
from collections import defaultdict

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
DATA = os.path.join(STATE, "geom_data.json")
GOLD = os.path.join(STATE, "gold_pairs.jsonl")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
# polomer pre spojity variant: default r_opus, cez --radius-field aj r_gpt (cross-lab)
RF = "r_opus"

def cos(a, b): return sum(x*y for x, y in zip(a, b))
def to_lor(u, r):
    ch, sh = math.cosh(r), math.sinh(r)
    return (ch, [sh*x for x in u])
def ldist(A, B):
    x0, xr = A; y0, yr = B
    val = -(-x0*y0 + sum(a*b for a, b in zip(xr, yr)))
    val = 1.0 if val < 1 else (1e6 if val > 1e6 else val)
    return math.acosh(val)

def main():
    global RF
    ap = argparse.ArgumentParser()
    ap.add_argument("--radius-field", default="r_opus", help="pole polomeru: r_opus (default) alebo r_gpt (cross-lab)")
    ap.add_argument("--gold", default=GOLD, help="gold subor (default gold_pairs.jsonl)")
    args = ap.parse_args()
    RF = args.radius_field
    data = {int(k): v for k, v in json.load(open(DATA, encoding="utf-8")).items() if "gemma" in v}
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l: r = json.loads(l); rows[r["id"]] = r
    gold = [json.loads(l) for l in open(args.gold, encoding="utf-8") if l.strip()]
    gold = [g for g in gold if g["parents"]]  # len deti s aspon 1 rodicom

    # polomery (RF = radius field: r_opus default alebo r_gpt cross-lab)
    r_cont = {i: 0.3 + (1.0 - data[i][RF]) for i in data if RF in data[i]}
    r_disc = {i: 0.3 + ((3 - LORD.get(rows[i].get("layer"), 0))/3.0) for i in data}
    lor_c = {i: to_lor(data[i]["gemma"], r_cont[i]) for i in r_cont}
    lor_d = {i: to_lor(data[i]["gemma"], r_disc[i]) for i in data}

    # === KROK 2: DIAGNOSTIKA — sudi opus-gold zhodne s layerom? ===
    up = same = down = 0
    for g in gold:
        cl = LORD.get(rows[g["child"]].get("layer"), -1)
        for p in g["parents"]:
            pl = LORD.get(rows[p].get("layer"), -1)
            if pl > cl: up += 1
            elif pl == cl: same += 1
            else: down += 1
    tot = up + same + down
    diag = {"gold_pairs": tot,
            "parent_layer_HIGHER": round(up/tot, 3) if tot else 0,
            "parent_layer_SAME": round(same/tot, 3) if tot else 0,
            "parent_layer_LOWER": round(down/tot, 3) if tot else 0}

    # === KROK 3: retrieval v ramci poolu ===
    def scorers(c):
        ang = lambda j: cos(data[c]["gemma"], data[j]["gemma"])
        prod = lambda j: cos(data[c]["gemma"], data[j]["gemma"]) + 0.5*(data[j].get(RF,0)-data[c].get(RF,0))
        hypc = lambda j: -ldist(lor_c[c], lor_c[j]) if (c in lor_c and j in lor_c) else -9e9
        hypd = lambda j: -ldist(lor_d[c], lor_d[j])
        return {"flat_cosine": ang, "product_space": prod,
                "hyper_continuous_opus": hypc, "hyper_discrete_layer": hypd}

    def evaluate(name_fn):
        rr = []; aurocs = []
        for g in gold:
            c = g["child"]; pool = [p for p in g["pool"] if p in data and p != c]
            gset = set(g["parents"]) & set(pool)
            if not gset or len(pool) < 2: continue
            sc = name_fn(c)
            ranked = sorted(pool, key=sc, reverse=True)
            best = min((ranked.index(p) for p in gset), default=None)
            if best is not None: rr.append(1.0/(best+1))
            # per-child AUROC parent vs non-parent v poole
            pos = [sc(p) for p in gset]
            neg = [sc(p) for p in pool if p not in gset]
            if pos and neg:
                cnt = tie = 0
                for pp in pos:
                    for ng in neg:
                        if pp > ng: cnt += 1
                        elif pp == ng: tie += 1
                aurocs.append((cnt + 0.5*tie)/(len(pos)*len(neg)))
        return {"n": len(rr), "MRR": round(sum(rr)/len(rr), 3) if rr else 0,
                "mean_AUROC": round(sum(aurocs)/len(aurocs), 3) if aurocs else 0}

    variants = ["flat_cosine", "product_space", "hyper_continuous_opus", "hyper_discrete_layer"]
    ret = {v: evaluate(lambda c, v=v: scorers(c)[v]) for v in variants}

    out = {"radius_field": RF, "n_gold_children": len(gold), "DIAGNOSTIKA_layer_vs_opusGold": diag,
           "retrieval_in_pool": ret}
    json.dump(out, open(os.path.join(STATE, "gold_eval.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
