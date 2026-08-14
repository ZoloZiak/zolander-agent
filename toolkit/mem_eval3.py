#!/usr/bin/env python3
"""mem_eval3.py — eval 3-lens panelu: YAR (Lorentz) + BM25 + EmbeddingGemma (cosine).

Cielom je ROZHODNUT cez differentiation contract, ci Gemma ako 3. lens zasluzi miesto:
  - kolko BITOV prida Gemma NAD (BM25+YAR)?  (prah 0.05 z Royse §5.3)
  - korelacie vsetkych parov (D1, prah 0.6)
  - eval: bm25 / yar / gemma solo, a panelove kombinacie (Recall@1/3/5, MRR)

Gemma vektory su predpocitane (embed_gemma_corpus.py -> gemma_corpus.npz / gemma_gold.npz),
takze tento eval NEvola GPU — cita cache. YAR+BM25 skore sa zberaju ako v mem_diff.py.

Bezi pod .venv-yar (kvoli YAR embed + hs). Gemma cast je len numpy nad cache.
"""
import os
import sys
import json
import math
import numpy as np

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
TOOLKIT = os.path.join(HOME, "zolander", "toolkit")
sys.path.insert(0, TOOLKIT)

GCORP = os.path.join(STATE, "gemma_corpus.npz")
GGOLD = os.path.join(STATE, "gemma_gold.npz")
FETCH = 20
TOPK_DISC = 3


def _norm(pairs):
    if not pairs:
        return {}
    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {i: 1.0 for i, _ in pairs}
    return {i: (s - lo) / (hi - lo) for i, s in pairs}


def rank_of(target, ordered):
    for i, mid in enumerate(ordered, 1):
        if mid == target:
            return i
    return 0


def metrics(ranks):
    n = len(ranks)
    return (sum(1 for r in ranks if r == 1) / n,
            sum(1 for r in ranks if 1 <= r <= 3) / n,
            sum(1 for r in ranks if 1 <= r <= 5) / n,
            sum((1.0 / r) for r in ranks if r > 0) / n)


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0


def _H(counts):
    tot = sum(counts)
    if tot == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / tot
            h -= p * math.log2(p)
    return h


def cond_H(samples, cond, y="y"):
    groups = {}
    for s in samples:
        k = tuple(s[c] for c in cond)
        groups.setdefault(k, [0, 0])[s[y]] += 1
    tot = len(samples)
    return sum((n0 + n1) / tot * _H([n0, n1]) for n0, n1 in groups.values())


def main():
    from embed_yar import embed_one
    import zol_mem
    import mem_lexical

    gold = json.load(open(GOLD))
    gc = np.load(GCORP)
    gg = np.load(GGOLD)
    g_ids = list(gc["ids"])
    g_vecs = gc["vecs"]            # (319,768) L2-normalizovane
    q_vecs = gg["qvecs"]           # (24,768)
    # cosine = dot (uz normalizovane); pre kazdu query maticovo
    sims_all = q_vecs @ g_vecs.T   # (24,319)

    per_q = []
    for qi, g in enumerate(gold):
        q, target = g["query"], g["id"]
        vec = embed_one(q)
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        sem = {r.get("id"): 1.0 / (1.0 + r.get("distance", 9e9)) for r in res}
        lex = {mid: sc for mid, sc, _ in mem_lexical.search(q, topk=FETCH)}
        # gemma: top FETCH podla cosine
        sims = sims_all[qi]
        order = np.argsort(-sims)[:FETCH]
        gem = {int(g_ids[j]): float(sims[j]) for j in order}
        per_q.append({"target": target, "sem": sem, "lex": lex, "gem": gem})

    # ---- differentiation: bity kazdeho lensu nad ostatnymi dvoma ----
    disc = []
    corr = {"sem-lex": ([], []), "sem-gem": ([], []), "lex-gem": ([], [])}
    for pq in per_q:
        tops = {}
        for key in ("sem", "lex", "gem"):
            tops[key] = {i for i, _ in sorted(pq[key].items(), key=lambda kv: -kv[1])[:TOPK_DISC]}
        n = {k: _norm(list(pq[k].items())) for k in ("sem", "lex", "gem")}
        ids = set(n["sem"]) | set(n["lex"]) | set(n["gem"])
        for i in ids:
            if i in n["sem"] and i in n["lex"]:
                corr["sem-lex"][0].append(n["sem"][i]); corr["sem-lex"][1].append(n["lex"][i])
            if i in n["sem"] and i in n["gem"]:
                corr["sem-gem"][0].append(n["sem"][i]); corr["sem-gem"][1].append(n["gem"][i])
            if i in n["lex"] and i in n["gem"]:
                corr["lex-gem"][0].append(n["lex"][i]); corr["lex-gem"][1].append(n["gem"][i])
            disc.append({"sem": 1 if i in tops["sem"] else 0,
                         "lex": 1 if i in tops["lex"] else 0,
                         "gem": 1 if i in tops["gem"] else 0,
                         "y": 1 if i == pq["target"] else 0})

    print("\n=== DIFFERENTIATION CONTRACT (3 lensy) ===")
    print("D1 korelacie (prah 0.6):")
    for k, (xs, ys) in corr.items():
        c = pearson(xs, ys)
        print(f"    {k:9} corr={c:+.3f}  {'REDUNDANT' if abs(c) > 0.6 else 'ok'}")
    print("D2 marginalne bity (co lens prida NAD zvysne dva, prah 0.05):")
    H_all = cond_H(disc, ["sem", "lex", "gem"])
    for lens in ("sem", "lex", "gem"):
        others = [x for x in ("sem", "lex", "gem") if x != lens]
        ig = cond_H(disc, others) - H_all
        name = {"sem": "YAR", "lex": "BM25", "gem": "GEMMA"}[lens]
        print(f"    {name:6} prida nad ostatne = {ig:.4f} bitu  "
              f"{'DRZAT' if ig >= 0.05 else 'slabe'}")

    # ---- eval: solo + panelove kombinacie ----
    def evalc(weights):
        ranks = []
        for pq in per_q:
            ns = {k: _norm(list(pq[k].items())) for k in ("sem", "lex", "gem")}
            ids = set().union(*[set(ns[k]) for k in ns])
            fused = {i: sum(weights.get(k, 0) * ns[k].get(i, 0) for k in ns) for i in ids}
            ordered = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
            ranks.append(rank_of(pq["target"], ordered))
        return metrics(ranks)

    print("\n=== EVAL (Recall@1/3/5, MRR) ===")
    combos = [
        ("yar solo", {"sem": 1}),
        ("bm25 solo", {"lex": 1}),
        ("gemma solo", {"gem": 1}),
        ("bm25+yar (W1.3)", {"lex": 1.3, "sem": 1}),
        ("bm25+gemma", {"lex": 1.3, "gem": 1}),
        ("yar+gemma", {"sem": 1, "gem": 1}),
        ("all3 (1.3/1/1)", {"lex": 1.3, "sem": 1, "gem": 1}),
        ("all3 (1.3/0.5/1)", {"lex": 1.3, "sem": 0.5, "gem": 1}),
        ("bm25+gemma+yar0.3", {"lex": 1.3, "gem": 1, "sem": 0.3}),
    ]
    print(f"{'konfig':<22}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'MRR':>7}")
    for name, w in combos:
        r1, r3, r5, mrr = evalc(w)
        print(f"{name:<22}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}")

    # ---- CROSS-ENCODER RERANK nad najlepsou kombinaciou (bm25+gemma) ----
    if "--ce" in sys.argv:
        from mem_ce import rerank_ce
        corpus = {int(g_ids[i]): None for i in range(len(g_ids))}
        # dotiahni texty z mem_index
        txt = {}
        for line in open(os.path.join(STATE, "mem_index.jsonl"), encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                txt[r["id"]] = r.get("text", "")
            except Exception:
                pass

        def eval_ce(w, topn=8):
            ranks = []
            for pq, g in zip(per_q, gold):
                ns = {k: _norm(list(pq[k].items())) for k in ("sem", "lex", "gem")}
                ids = set().union(*[set(ns[k]) for k in ns])
                fused = {i: sum(w.get(k, 0) * ns[k].get(i, 0) for k in ns) for i in ids}
                top = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])][:topn]
                cands = [{"id": i, "text": txt.get(i, "")} for i in top]
                order = rerank_ce(g["query"], cands)
                ranks.append(rank_of(pq["target"], order))
            return metrics(ranks)

        print("\n=== + CROSS-ENCODER RERANK (top-8, multiling mMiniLMv2) ===")
        for name, w in [("bm25+gemma +CE", {"lex": 1.3, "gem": 1}),
                        ("all3 +CE", {"lex": 1.3, "gem": 1, "sem": 0.3})]:
            r1, r3, r5, mrr = eval_ce(w)
            print(f"{name:<22}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
