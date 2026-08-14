#!/usr/bin/env python3
"""mem_diff.py — differentiation contract + cross-term test (Calculus of Association).

Aplikuje dve myslienky z Royse 2026 na nas hybrid (YAR semantic + BM25 lexikal):

  A) DIFFERENTIATION CONTRACT (ich §5.3):
     D1 distinctness  — korelacia YAR vs BM25 skore naprie (query,kandidat) parmi.
                        Ak |corr| > 0.6 => redundantne, druhy lens nema zmysel.
     D2 marginal info — kolko BITOV o "je kandidat spravny target" prida YAR NAD RAMEC
                        BM25. Ich prah: >=0.05 bitu = oplati sa drzat. Diskretizacia
                        top-k, mala vzorka (24 query) => INDIKATIVNE, nie dokaz.

  B) CROSS-TERM (ich §2.3): pridaj interakcny clen rho = YAR_norm * BM25_norm ako
     TRETI signal do fuzie (asociacia medzi asociaciami). Sweep vahy, zmeraj ci
     dvihne Recall@1 nad hybrid bez neho.

Bezi pod .venv-yar. Zdielana zberna logika s mem_eval.py.
Spustenie: SSL_CERT_FILE=... ~/zolander/.venv-yar/bin/python mem_diff.py
"""
import os
import sys
import json
import math

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
TOOLKIT = os.path.join(HOME, "zolander", "toolkit")
sys.path.insert(0, TOOLKIT)

FETCH = 20
TOPK_DISC = 3   # diskretizacia pre D2: "je kandidat v top-3 podla zdroja"


def _norm(pairs):
    if not pairs:
        return {}
    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {i: 1.0 for i, _ in pairs}
    return {i: (s - lo) / (hi - lo) for i, s in pairs}


def rank_of(target, ordered_ids):
    for i, mid in enumerate(ordered_ids, 1):
        if mid == target:
            return i
    return 0


def metrics(ranks):
    n = len(ranks)
    r1 = sum(1 for r in ranks if r == 1) / n
    r3 = sum(1 for r in ranks if 1 <= r <= 3) / n
    r5 = sum(1 for r in ranks if 1 <= r <= 5) / n
    mrr = sum((1.0 / r) for r in ranks if r > 0) / n
    return r1, r3, r5, mrr


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def _entropy(counts):
    tot = sum(counts)
    if tot == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / tot
            h -= p * math.log2(p)
    return h


def cond_entropy(samples, cond_keys, y_key):
    """H(y | cond_keys) na zozname dict-vzoriek. y binarne."""
    groups = {}
    for s in samples:
        k = tuple(s[c] for c in cond_keys)
        groups.setdefault(k, [0, 0])
        groups[k][s[y_key]] += 1
    tot = len(samples)
    h = 0.0
    for k, (n0, n1) in groups.items():
        w = (n0 + n1) / tot
        h += w * _entropy([n0, n1])
    return h


def collect(gold):
    from embed_yar import embed_one
    import zol_mem
    import mem_lexical
    per_q = []
    for g in gold:
        q, target = g["query"], g["id"]
        vec = embed_one(q)
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        sem = {r.get("id"): 1.0 / (1.0 + r.get("distance", 9e9)) for r in res}
        lex = {mid: sc for mid, sc, _ in mem_lexical.search(q, topk=FETCH)}
        per_q.append({"target": target, "sem": sem, "lex": lex})
    return per_q


def main():
    gold = json.load(open(GOLD))
    per_q = collect(gold)

    # ---------- A) DIFFERENTIATION CONTRACT ----------
    # D1: korelacia normalizovanych skore naprie vsetkymi (query,kandidat) parmi,
    #     kde kandidat ma skore v OBOCH zdrojoch (inak neporovnatelne).
    xs, ys = [], []
    disc_samples = []  # pre D2
    for pq in per_q:
        sn = _norm(list(pq["sem"].items()))
        ln = _norm(list(pq["lex"].items()))
        # top-k mnoziny podla RAW poradia zdroja
        sem_top = {i for i, _ in sorted(pq["sem"].items(), key=lambda kv: -kv[1])[:TOPK_DISC]}
        lex_top = {i for i, _ in sorted(pq["lex"].items(), key=lambda kv: -kv[1])[:TOPK_DISC]}
        ids = set(sn) | set(ln)
        for i in ids:
            if i in sn and i in ln:
                xs.append(sn[i]); ys.append(ln[i])
            disc_samples.append({
                "yar": 1 if i in sem_top else 0,
                "bm25": 1 if i in lex_top else 0,
                "y": 1 if i == pq["target"] else 0,
            })
    d1 = pearson(xs, ys)

    # D2: marginalne bity YAR nad BM25 = H(y|bm25) - H(y|bm25,yar)
    H_y = _entropy([sum(1 for s in disc_samples if s["y"] == 0),
                    sum(1 for s in disc_samples if s["y"] == 1)])
    H_y_bm = cond_entropy(disc_samples, ["bm25"], "y")
    H_y_bm_yar = cond_entropy(disc_samples, ["bm25", "yar"], "y")
    ig_yar_over_bm = H_y_bm - H_y_bm_yar
    # a symetricky: co prida BM25 nad YAR (kontrola)
    H_y_yar = cond_entropy(disc_samples, ["yar"], "y")
    ig_bm_over_yar = H_y_yar - H_y_bm_yar

    print("\n=== A) DIFFERENTIATION CONTRACT (YAR vs BM25) ===")
    print(f"D1 distinctness: corr(YAR,BM25) = {d1:+.3f}   "
          f"(prah redundancie |corr|>0.60 -> {'REDUNDANTNE' if abs(d1) > 0.6 else 'OK, roznorode'})")
    print(f"D2 marginal info (indikativne, {len(gold)} query, top-{TOPK_DISC} disc.):")
    print(f"    H(y)                    = {H_y:.4f} bitu")
    print(f"    H(y|BM25)               = {H_y_bm:.4f}")
    print(f"    H(y|BM25,YAR)           = {H_y_bm_yar:.4f}")
    print(f"    -> YAR prida nad BM25   = {ig_yar_over_bm:.4f} bitu   "
          f"(prah 0.05 -> {'DRZAT' if ig_yar_over_bm >= 0.05 else 'SLABE, kandidat na vyhod'})")
    print(f"    -> BM25 prida nad YAR   = {ig_bm_over_yar:.4f} bitu   (kontrola, ma byt vysoke)")

    # ---------- B) CROSS-TERM TEST ----------
    def eval_fused(w_lex, w_cross):
        ranks = []
        for pq in per_q:
            sn = _norm(list(pq["sem"].items()))
            ln = _norm(list(pq["lex"].items()))
            ids = set(sn) | set(ln)
            fused = {}
            for i in ids:
                a, b = sn.get(i, 0.0), ln.get(i, 0.0)
                fused[i] = a + w_lex * b + w_cross * (a * b)
            ordered = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
            ranks.append(rank_of(pq["target"], ordered))
        return metrics(ranks)

    print("\n=== B) CROSS-TERM (rho = YAR_norm * BM25_norm) ===")
    print(f"{'w_lex':>6}{'w_cross':>9}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'MRR':>7}")
    base = None
    best = None
    for w_lex in (1.0, 1.3):
        for w_cross in (0.0, 0.5, 1.0, 1.5, 2.0):
            r1, r3, r5, mrr = eval_fused(w_lex, w_cross)
            tag_base = (w_lex == 1.3 and w_cross == 0.0)
            print(f"{w_lex:>6}{w_cross:>9}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}"
                  f"{'  <- baseline (bez cross)' if tag_base else ''}")
            if tag_base:
                base = (r1, mrr)
            if best is None or mrr > best[2] or (mrr == best[2] and r1 > best[3]):
                best = (w_lex, w_cross, mrr, r1)
    print("-" * 50)
    print(f"NAJLEPSI: w_lex={best[0]} w_cross={best[1]} -> MRR {best[2]:.3f}, R@1 {best[3]:.2f}")
    if base:
        print(f"BASELINE (w_lex=1.3, w_cross=0): R@1 {base[0]:.2f}, MRR {base[1]:.3f}")
        if best[3] > base[0] or best[2] > base[1]:
            print("=> CROSS-TERM POMAHA (aspon nezhorsuje) — zvazit zapojenie")
        else:
            print("=> CROSS-TERM nepomaha na tomto korpuse — nezapajat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
