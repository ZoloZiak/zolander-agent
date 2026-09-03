#!/usr/bin/env python3
"""mem_ablation.py — ablacia lensov v recall fuzii. LEN MERANIE, ziadny zapis/mazanie.

Otazka veducka: "bezime cosine AJ lorentz paralelne — co sa zmeni ked lorentz (YAR)
vypnem?" Odpoved: NEzahadzujeme nic, len zmeriame rozdiel medzi konfiguraciami.

Pouziva IDENTICKU fuznu logiku ako produkcia (zol_mem.recall): min-max score fusion
s vahami W_SEM=1.0 (YAR lorentz), W_LEX=1.6 (bm25), W_GEM=0.8 (gemma cosine).
Zdroje skore: YAR naostro (zol_mem.hs search nad zol_mem), BM25 naostro (mem_lexical),
Gemma z cache (gemma_corpus.npz / gemma_gold.npz — ziadny daemon netreba).

Metriky: R@1, R@3, MRR nad mem_eval_gold.json (ten isty gold ako tune).
"""
import os
import sys
import json
import numpy as np

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
sys.path.insert(0, os.path.join(HOME, "projects", "zolander", "toolkit"))
FETCH = 20


def _norm(pairs):
    if not pairs:
        return {}
    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {i: 1.0 for i, _ in pairs}
    return {i: (s - lo) / (hi - lo) for i, s in pairs}


def rank_of(t, order):
    for i, m in enumerate(order, 1):
        if m == t:
            return i
    return 0


def metrics(ranks):
    n = len(ranks)
    return (sum(1 for r in ranks if r == 1) / n,
            sum(1 for r in ranks if 1 <= r <= 3) / n,
            sum((1.0 / r) for r in ranks if r > 0) / n)


def main():
    from embed_yar import embed_one
    import zol_mem
    import mem_lexical

    gold = json.load(open(GOLD))
    gc = np.load(STATE + "/gemma_corpus.npz")
    gg = np.load(STATE + "/gemma_gold.npz")
    g_ids = list(gc["ids"]); g_vecs = gc["vecs"]; q_vecs = gg["qvecs"]
    sims_all = q_vecs @ g_vecs.T

    # Zber vsetkych troch lensov RAZ (naostro YAR+BM25, Gemma z cache)
    per_q = []
    for qi, g in enumerate(gold):
        vec = embed_one(g["query"])
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        sem = {r.get("id"): 1.0 / (1.0 + r.get("distance", 9e9)) for r in res}
        lex = {mid: sc for mid, sc, _ in mem_lexical.search(g["query"], topk=FETCH)}
        sims = sims_all[qi]
        order = np.argsort(-sims)[:FETCH]
        gem = {int(g_ids[j]): float(sims[j]) for j in order}
        per_q.append({"t": g["id"], "sem": sem, "lex": lex, "gem": gem})

    def fuse(ws):
        """Identicka min-max score fuzia ako zol_mem.recall."""
        ranks = []
        cov = 0  # v kolkych dotazoch mal aspon jeden zapnuty lens ciel v top FETCH
        for pq in per_q:
            active = [k for k in ("sem", "lex", "gem") if ws.get(k, 0) > 0]
            n = {k: _norm(list(pq[k].items())) for k in active}
            ids = set().union(*[set(n[k]) for k in n]) if n else set()
            fused = {i: sum(ws.get(k, 0) * n[k].get(i, 0) for k in active) for i in ids}
            order = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
            ranks.append(rank_of(pq["t"], order))
            if pq["t"] in ids:
                cov += 1
        return metrics(ranks) + (cov / len(per_q),)

    # Produkcne vahy
    WL, WY, WG = 1.6, 1.0, 0.8
    configs = [
        ("FULL (produkcia: bm25+yar+gemma)", {"lex": WL, "sem": WY, "gem": WG}),
        ("BEZ YAR/Lorentz (bm25+gemma)",     {"lex": WL, "sem": 0.0, "gem": WG}),
        ("BEZ Gemma (bm25+yar)",             {"lex": WL, "sem": WY, "gem": 0.0}),
        ("BEZ BM25 (yar+gemma)",             {"lex": 0.0, "sem": WY, "gem": WG}),
        ("LEN YAR/Lorentz",                  {"lex": 0.0, "sem": WY, "gem": 0.0}),
        ("LEN Gemma cosine",                 {"lex": 0.0, "sem": 0.0, "gem": WG}),
        ("LEN BM25",                         {"lex": WL, "sem": 0.0, "gem": 0.0}),
    ]

    print(f"# gold dotazov: {len(gold)}   (FETCH={FETCH})")
    print(f"{'konfiguracia':38s} {'R@1':>5s} {'R@3':>5s} {'MRR':>6s} {'pokrytie':>8s}")
    print("-" * 68)
    results = {}
    for name, ws in configs:
        r1, r3, mrr, cov = fuse(ws)
        results[name] = (r1, r3, mrr, cov)
        print(f"{name:38s} {r1:5.2f} {r3:5.2f} {mrr:6.3f} {cov:7.1%}")

    full = results["FULL (produkcia: bm25+yar+gemma)"]
    noyar = results["BEZ YAR/Lorentz (bm25+gemma)"]
    print("\n=== ROZDIEL: vypnutie YAR/Lorentz z fuzie ===")
    print(f"FULL          MRR={full[2]:.3f}  R@1={full[0]:.2f}  R@3={full[1]:.2f}")
    print(f"BEZ YAR       MRR={noyar[2]:.3f}  R@1={noyar[0]:.2f}  R@3={noyar[1]:.2f}")
    dmrr = noyar[2] - full[2]
    print(f"delta MRR = {dmrr:+.3f}  ({'YAR pomaha' if dmrr < -0.005 else 'YAR NEpomaha (dead weight vo fuzii)' if abs(dmrr) <= 0.005 else 'BEZ YAR je LEPSI'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
