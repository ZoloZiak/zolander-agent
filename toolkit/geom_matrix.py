#!/usr/bin/env python3
"""geom_matrix.py — NEPRIESTRELNA matica: 3 laby x prompt-varianty x goldy.

Ziadne LLM volania: cita len HOTOVE skore (geom_data.json r_* polia) a goldy
(gold_pairs*.jsonl). Pre kazdy gold spocita per-child AUROC pre:
  - flat_cosine (nezavisi od polomeru)
  - hyper_discrete_layer (nezavisi od polomeru — L0..L3 int)
  - hyper_continuous_<RF> pre KAZDE dostupne radius pole (r_opus/r_gpt/r_gemini/..._b)
Potom bootstrap (5000) na parovych rozdieloch per-child AUROC:
  P(flat>disc), P(disc>flat), a pre kazde RF P(cont>disc), P(flat>cont).
+ DIAGNOSTIKA: kolko %% goldu ma layer(parent) vyssi/rovny/nizsi nez dieta.

Cielom je vidiet ci verdikt (ktora geometria vyhrava) je STABILNY napriec
labmi (kto stavia gold) aj promptami (ako sa pytame). Ak sa kyve -> geometria
nie je robustny signal, ground truth je rozmazana.
"""
import json, os, math, random
from collections import defaultdict

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
DATA = os.path.join(STATE, "geom_data.json")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

# goldy: meno -> subor. Zaradia sa len tie co existuju.
GOLDS = {
    "opus_A":   "gold_pairs.jsonl",
    "gpt_A":    "gold_pairs_gpt.jsonl",
    "gemini_A": "gold_pairs_gemini.jsonl",
    "gpt_B":    "gold_pairs_gpt_b.jsonl",
    "gemini_B": "gold_pairs_gemini_b.jsonl",
}
# radius polia pre continuous variant (zaradia sa len co su v data)
RFIELDS = ["r_opus", "r_gpt", "r_gemini", "r_gpt_b", "r_gemini_b"]

def cos(a, b): return sum(x*y for x, y in zip(a, b))
def to_lor(u, r):
    ch, sh = math.cosh(r), math.sinh(r)
    return (ch, [sh*x for x in u])
def ldist(A, B):
    x0, xr = A; y0, yr = B
    val = -(-x0*y0 + sum(a*b for a, b in zip(xr, yr)))
    val = 1.0 if val < 1 else (1e6 if val > 1e6 else val)
    return math.acosh(val)

def auroc_pairs(pos, neg):
    if not pos or not neg: return None
    cnt = tie = 0
    for pp in pos:
        for ng in neg:
            if pp > ng: cnt += 1
            elif pp == ng: tie += 1
    return (cnt + 0.5*tie)/(len(pos)*len(neg))

def load():
    data = {int(k): v for k, v in json.load(open(DATA, encoding="utf-8")).items() if "gemma" in v}
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l: r = json.loads(l); rows[r["id"]] = r
    return data, rows

def build_scorers(data, rows, present_rf):
    r_disc = {i: 0.3 + ((3 - LORD.get(rows[i].get("layer"), 0))/3.0) for i in data}
    lor_d = {i: to_lor(data[i]["gemma"], r_disc[i]) for i in data}
    lor_c = {}
    for rf in present_rf:
        r_cont = {i: 0.3 + (1.0 - data[i][rf]) for i in data if rf in data[i]}
        lor_c[rf] = {i: to_lor(data[i]["gemma"], r_cont[i]) for i in r_cont}

    def make(name):
        if name == "flat_cosine":
            return lambda c, j: cos(data[c]["gemma"], data[j]["gemma"])
        if name == "hyper_discrete_layer":
            return lambda c, j: -ldist(lor_d[c], lor_d[j])
        rf = name[len("hyper_continuous_"):]
        L = lor_c[rf]
        return lambda c, j: (-ldist(L[c], L[j]) if (c in L and j in L) else -9e9)
    return make

def per_child_auroc(gold, cfn, data):
    """vrati list per-child AUROC (parent vs pool-non-parent)."""
    out = []
    for g in gold:
        c = g["child"]; pool = [p for p in g["pool"] if p in data and p != c]
        gset = set(g["parents"]) & set(pool)
        if not gset or len(pool) < 2: continue
        sc = lambda j: cfn(c, j)
        pos = [sc(p) for p in gset]
        neg = [sc(p) for p in pool if p not in gset]
        a = auroc_pairs(pos, neg)
        if a is not None: out.append(a)
    return out

def bootstrap_gt(a, b, n=5000, seed=7):
    """P(mean(a) > mean(b)) na parovych rozdieloch (a,b zarovnane per-child)."""
    m = min(len(a), len(b))
    d = [a[i]-b[i] for i in range(m)]
    if not d: return None
    rnd = random.Random(seed)
    wins = 0
    for _ in range(n):
        s = sum(d[rnd.randrange(m)] for _ in range(m))
        if s > 0: wins += 1
    return round(wins/n, 3)

def diag(gold, rows):
    up = same = down = 0
    for g in gold:
        cl = LORD.get(rows[g["child"]].get("layer"), -1)
        for p in g["parents"]:
            pl = LORD.get(rows[p].get("layer"), -1)
            if pl > cl: up += 1
            elif pl == cl: same += 1
            else: down += 1
    tot = up+same+down or 1
    return {"pairs": up+same+down, "HIGHER": round(up/tot,3), "SAME": round(same/tot,3), "LOWER": round(down/tot,3)}

def main():
    data, rows = load()
    present_rf = [rf for rf in RFIELDS if any(rf in v for v in data.values())]
    make = build_scorers(data, rows, present_rf)
    variants = ["flat_cosine", "hyper_discrete_layer"] + [f"hyper_continuous_{rf}" for rf in present_rf]

    result = {"present_radius_fields": present_rf, "golds": {}}
    for gname, gfile in GOLDS.items():
        path = os.path.join(STATE, gfile)
        if not os.path.exists(path): continue
        gold = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        gold = [g for g in gold if g.get("parents")]
        if not gold: continue

        pc = {v: per_child_auroc(gold, make(v), data) for v in variants}
        means = {v: (round(sum(pc[v])/len(pc[v]),3) if pc[v] else None) for v in variants}

        # bootstrap: flat vs disc + kazde continuous vs disc + flat vs continuous
        boot = {"P(flat>disc)": bootstrap_gt(pc["flat_cosine"], pc["hyper_discrete_layer"]),
                "P(disc>flat)": bootstrap_gt(pc["hyper_discrete_layer"], pc["flat_cosine"])}
        for rf in present_rf:
            cv = f"hyper_continuous_{rf}"
            boot[f"P(cont[{rf}]>disc)"] = bootstrap_gt(pc[cv], pc["hyper_discrete_layer"])
            boot[f"P(flat>cont[{rf}])"] = bootstrap_gt(pc["flat_cosine"], pc[cv])

        result["golds"][gname] = {
            "n_children": len(gold),
            "DIAGNOSTIKA": diag(gold, rows),
            "mean_AUROC": means,
            "bootstrap": boot,
        }

    json.dump(result, open(os.path.join(STATE, "geom_matrix.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # === META-ANALYZA: koreluje SAME-layer %% (volnost hierarchie) s vitazom? ===
    # Hypoteza: cim viac laterálnych (same-layer) väzieb v golde, tym viac flat vyhrava strom.
    # margin = AUROC(flat) - AUROC(disc). Kladny = flat lepsi. Ocakavame: rastie so SAME%.
    pts = []
    for gname, gg in result["golds"].items():
        same = gg["DIAGNOSTIKA"]["SAME"]
        m = gg["mean_AUROC"]
        if m["flat_cosine"] is None or m["hyper_discrete_layer"] is None: continue
        margin = round(m["flat_cosine"] - m["hyper_discrete_layer"], 3)
        pts.append({"gold": gname, "n": gg["n_children"], "SAME": same, "flat_minus_disc": margin,
                    "P(flat>disc)": gg["bootstrap"]["P(flat>disc)"]})
    pts.sort(key=lambda x: x["SAME"])
    # Spearman rho (SAME vs margin) manualne (male N)
    def spearman(xs, ys):
        n = len(xs)
        if n < 3: return None
        def rank(v):
            s = sorted(range(n), key=lambda i: v[i]); r = [0]*n
            for pos, i in enumerate(s): r[i] = pos+1
            return r
        rx, ry = rank(xs), rank(ys)
        d2 = sum((rx[i]-ry[i])**2 for i in range(n))
        return round(1 - 6*d2/(n*(n*n-1)), 3)
    rho = spearman([p["SAME"] for p in pts], [p["flat_minus_disc"] for p in pts])
    result["META"] = {
        "hypoteza": "vyssie SAME-layer%% (volnejsia hierarchia) -> flat vyhrava; nizsie -> strom vyhrava",
        "spearman_SAME_vs_flatMargin": rho,
        "body_zoradene_podla_SAME": pts,
    }
    json.dump(result, open(os.path.join(STATE, "geom_matrix.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
