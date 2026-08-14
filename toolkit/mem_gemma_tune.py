#!/usr/bin/env python3
"""mem_gemma_tune.py — jemne ladenie Gemma prispevku do fuzie.

Ciel: existuje konfiguracia kde Gemma prekona bm25+yar (0.876 MRR)? Testuje:
  - jemny sweep vah bm25/yar/gemma
  - Gemma len ako tie-break (mala vaha)
  - RRF fuzia (rank-based) vs score fusion — ci na 3 lensoch RRF pomoze
  - max-fusion (ber max skore naprie lensmi) namiesto suctu
Cita cache (gemma_corpus/gold .npz) + YAR/BM25 zbiera naostro. Bez zapisu do produkcie.
"""
import os
import sys
import json
import itertools
import numpy as np

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
sys.path.insert(0, os.path.join(HOME, "zolander", "toolkit"))
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

    def score_fuse(ws):
        ranks = []
        for pq in per_q:
            n = {k: _norm(list(pq[k].items())) for k in ("sem", "lex", "gem")}
            ids = set().union(*[set(n[k]) for k in n])
            fused = {i: sum(ws.get(k, 0) * n[k].get(i, 0) for k in n) for i in ids}
            ranks.append(rank_of(pq["t"], [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]))
        return metrics(ranks)

    def rrf_fuse(keys, K=60):
        ranks = []
        for pq in per_q:
            rr = {}
            for k in keys:
                order = [i for i, _ in sorted(pq[k].items(), key=lambda kv: -kv[1])]
                for rank, i in enumerate(order):
                    rr[i] = rr.get(i, 0.0) + 1.0 / (K + rank)
            ranks.append(rank_of(pq["t"], [i for i, _ in sorted(rr.items(), key=lambda kv: -kv[1])]))
        return metrics(ranks)

    print("=== BASELINE ===")
    r1, r3, mrr = score_fuse({"lex": 1.3, "sem": 1.0})
    print(f"bm25+yar (1.3/1.0)         R@1={r1:.2f} R@3={r3:.2f} MRR={mrr:.3f}")

    print("\n=== SCORE FUSION sweep (bm25 + yar + gemma) ===")
    best = (None, 0, 0, 0)
    for wl in (1.0, 1.3, 1.6):
        for wy in (0.0, 0.3, 0.5, 1.0):
            for wg in (0.0, 0.3, 0.5, 0.8, 1.0):
                r1, r3, mrr = score_fuse({"lex": wl, "sem": wy, "gem": wg})
                if mrr > best[3] or (mrr == best[3] and r1 > best[1]):
                    best = ((wl, wy, wg), r1, r3, mrr)
    print(f"NAJLEPSI score: bm25={best[0][0]} yar={best[0][1]} gemma={best[0][2]}"
          f" -> R@1={best[1]:.2f} R@3={best[2]:.2f} MRR={best[3]:.3f}")

    print("\n=== RRF FUSION (rank-based) ===")
    for keys, name in [(["lex", "sem"], "bm25+yar"),
                       (["lex", "gem"], "bm25+gemma"),
                       (["lex", "sem", "gem"], "all3")]:
        r1, r3, mrr = rrf_fuse(keys)
        print(f"RRF {name:14} R@1={r1:.2f} R@3={r3:.2f} MRR={mrr:.3f}")

    print("\n=== VERDIKT ===")
    if best[3] > mrr and best[3] >= 0.876:
        print(f"Gemma v najlepsej score-konfig MRR={best[3]:.3f} vs baseline 0.876")
        print("PREKONAVA baseline" if best[3] > 0.876 else "NEprekonava baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
