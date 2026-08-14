#!/usr/bin/env python3
"""mem_eval.py — zmeria kvalitu recallu na gold-sete (state/mem_eval_gold.json).

Porovnava rezimy a robi SWEEP vahy W_LEX (nie odhad — meranie):
  - yar_only      : cisto semanticky (YAR Lorentz)
  - bm25_only     : cisto lexikalny (BM25 + stemmer)
  - hybrid W=x    : min-max score fusion pre kazdu vahu z W_GRID
Metriky: Recall@1, Recall@3, Recall@5, MRR (mean reciprocal rank).

EFEKTIVITA: kazdu query embedujem RAZ (YAR) a raz spravim BM25; vahy testujem
aritmetikou nad ulozenymi skore (ziadne re-embedovanie). Re-rank sa meria zvlast
(--rerank) lebo je drahy (Opus call per query).

Bezi pod .venv-yar. Sietovo: len YAR embed + hs search (lokalne). Opus len s --rerank.
"""
import os
import sys
import json

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
TOOLKIT = os.path.join(HOME, "zolander", "toolkit")
sys.path.insert(0, TOOLKIT)

W_GRID = [0.0, 0.5, 0.8, 1.0, 1.3, 1.6, 2.0, 3.0]  # 0.0 = de facto yar_only kontrola


def _norm(pairs):
    if not pairs:
        return {}
    vals = [s for _, s in pairs]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return {i: 1.0 for i, _ in pairs}
    return {i: (s - lo) / (hi - lo) for i, s in pairs}


def rank_of(target, ordered_ids):
    """1-based rank targetu v zozname; 0 ak nie je."""
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


def main():
    from embed_yar import embed_one
    import zol_mem
    import mem_lexical

    gold = json.load(open(GOLD))
    do_rerank = "--rerank" in sys.argv

    # 1) pre kazdu query zozbieraj RAW skore z oboch zdrojov (raz)
    per_q = []  # {target, sem:{id:score}, lex:{id:score}}
    FETCH = 20
    for g in gold:
        q, target = g["query"], g["id"]
        vec = embed_one(q)
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        sem = {r.get("id"): 1.0 / (1.0 + r.get("distance", 9e9)) for r in res}
        lex_raw = mem_lexical.search(q, topk=FETCH)  # [(id, score, doc)]
        lex = {mid: sc for mid, sc, _ in lex_raw}
        per_q.append({"target": target, "sem": sem, "lex": lex})

    def eval_hybrid(w_lex, w_sem=1.0):
        ranks = []
        for pq in per_q:
            sn = _norm(list(pq["sem"].items()))
            ln = _norm(list(pq["lex"].items()))
            ids = set(sn) | set(ln)
            fused = {i: w_sem * sn.get(i, 0) + w_lex * ln.get(i, 0) for i in ids}
            ordered = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
            ranks.append(rank_of(pq["target"], ordered))
        return ranks

    def eval_single(key):
        ranks = []
        for pq in per_q:
            ordered = [i for i, _ in sorted(pq[key].items(), key=lambda kv: -kv[1])]
            ranks.append(rank_of(pq["target"], ordered))
        return ranks

    print(f"\n=== RECALL EVAL — {len(gold)} gold otazok (parafraza) ===\n")
    print(f"{'rezim':<16}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'MRR':>7}")
    print("-" * 44)

    for name, ranks in [("yar_only", eval_single("sem")),
                        ("bm25_only", eval_single("lex"))]:
        r1, r3, r5, mrr = metrics(ranks)
        print(f"{name:<16}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}")

    print("-" * 44)
    best = None
    for w in W_GRID:
        r1, r3, r5, mrr = metrics(eval_hybrid(w))
        tag = f"hybrid W={w}"
        print(f"{tag:<16}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}")
        if best is None or mrr > best[1]:
            best = (w, mrr, r1, r3, r5)
    print("-" * 44)
    print(f"NAJLEPSIA vaha W_LEX = {best[0]}  (MRR {best[1]:.3f}, "
          f"R@1 {best[2]:.2f}, R@3 {best[3]:.2f}, R@5 {best[4]:.2f})")

    if do_rerank:
        from mem_rerank import rerank
        ranks = []
        for pq, g in zip(per_q, gold):
            sn = _norm(list(pq["sem"].items()))
            ln = _norm(list(pq["lex"].items()))
            ids = set(sn) | set(ln)
            fused = {i: sn.get(i, 0) + 1.3 * ln.get(i, 0) for i in ids}
            ordered = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])][:8]
            texts = {}
            for pqk in ("sem", "lex"):
                pass
            # dotiahni texty z korpusu
            corpus = {d["id"]: d["text"] for d in mem_lexical.load_corpus()}
            cands = [{"id": i, "text": corpus.get(i, "")} for i in ordered]
            order2 = rerank(g["query"], cands)
            ranks.append(rank_of(pq["target"], order2))
        r1, r3, r5, mrr = metrics(ranks)
        print("-" * 44)
        print(f"{'hybrid+rerank':<16}{r1:>7.2f}{r3:>7.2f}{r5:>7.2f}{mrr:>7.3f}"
              f"   (Opus, top-8, W=1.3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
