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
STATE = os.path.join(HOME, "projects", "zolander", "state")
GOLD = os.environ.get("EVAL_GOLD", os.path.join(STATE, "mem_eval_gold.json"))
CANARIES = os.path.join(STATE, "mem_eval_canaries.json")
TOOLKIT = os.path.join(HOME, "projects", "zolander", "toolkit")
sys.path.insert(0, TOOLKIT)

W_GRID = [0.0, 0.5, 0.8, 1.0, 1.3, 1.6, 2.0, 3.0]  # 0.0 = de facto yar_only kontrola


CANARY_SCORES = {"correct": 1, "abstain": 0, "answered": -4, "wrong": -4}


def canary_score(decision):
    """Penalty-aware canary score (2608.26385): correct +1, abstain 0, wrong -4."""
    return CANARY_SCORES.get(decision, -4)


def score_canary_results(results, min_score=0.35):
    """Score one knowledge-gap canary from recall results.

    Canary answer is absent from KB by construction. Empty/weak evidence = abstain.
    Strong retrieved evidence means the system would likely answer from unsupported
    memory/parametric prior, so score it as answered/wrong (-4).
    """
    if not results:
        return {"decision": "abstain", "score": canary_score("abstain"), "top_id": None}
    top = max(results, key=lambda r: float(r.get("score", 0) or 0))
    top_score = float(top.get("score", 0) or 0)
    if top_score < min_score:
        return {"decision": "abstain", "score": canary_score("abstain"), "top_id": top.get("id"), "top_score": top_score}
    return {"decision": "answered", "score": canary_score("answered"), "top_id": top.get("id"), "top_score": top_score}


def evaluate_canary_results(canaries, results_by_query, min_score=0.35):
    """Aggregate canary scoring for a list of {query} entries and precomputed results."""
    rows = []
    counts = {"correct": 0, "abstain": 0, "answered": 0}
    total = 0
    for c in canaries:
        q = c["query"]
        row = score_canary_results(results_by_query.get(q, []), min_score=min_score)
        row["query"] = q
        rows.append(row)
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
        total += row["score"]
    return {"total_score": total, "count": len(rows), "rows": rows, **counts}


def run_canaries(canaries, recall_fn, min_score=0.35):
    """Live knowledge-gap canary runner (2608.26385).

    Spojí recall + scoring: pre KAŽDÚ canary query zavolá recall_fn(query) a
    obodová výsledok penalty-aware škálou (correct +1 / abstain 0 / answered -4).

    Canary otázky sú KONŠTRUKČNE mimo KB — správna odpoveď systému je ABSTAIN
    (prázdny/slabý recall). Silný recall na neexistujúci fakt = systém by
    odpovedal z nepodloženej pamäte/parametrického prioru → answered/-4.

    recall_fn je dependency-injected (query -> list[{id, score}]), aby test bežal
    offline; CLI napojí reálny embed+search recall.

    KRITICKÉ: keď recall_fn PADNE (napr. DB down), NErátame to ako "abstain" —
    to by maskovalo pád backendu ako správne abstinovanie. Zaznamenáme samostatnú
    `error` kategóriu (score 0, nezarátaný do abstain/answered) a `ready=False`.
    `ready=True` len keď je korpus neprázdny a žiaden recall nezlyhal → skóre je
    dôveryhodné. Fail-hard na úrovni jednej query, fail-visible na úrovni reportu.

    Returns: {total_score, count, rows, correct, abstain, answered, error, ready}.
    """
    rows = []
    counts = {"correct": 0, "abstain": 0, "answered": 0, "error": 0}
    total = 0
    had_error = False
    for c in canaries:
        q = c["query"] if isinstance(c, dict) else c
        try:
            results = recall_fn(q) or []
            row = score_canary_results(results, min_score=min_score)
        except Exception as exc:
            had_error = True
            row = {"decision": "error", "score": 0, "top_id": None,
                   "error": str(exc)[-200:]}
        row["query"] = q
        rows.append(row)
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
        total += row["score"]
    ready = bool(canaries) and not had_error
    return {"total_score": total, "count": len(rows), "rows": rows,
            "ready": ready, **counts}


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


def main_canary():
    """Live knowledge-gap canary runner nad state/mem_eval_canaries.json.

    Canary otázky sú KONŠTRUKČNE mimo KB. recall_fn robí reálny YAR embed +
    hs search a vracia raw 1/(1+distance) ako absolútny proxy istoty (NIE min-max
    norm — tá spraví top vždy 1.0 a všetko by vyzeralo answered). Nízka istota na
    absentnú otázku = správne abstain; vysoká = systém by odpovedal z ničoho (-4).

    Prah min_score je zatiaľ NEKALIBROVANÝ default (0.35) — výstup tlačí RAW top
    skóre každej canary, nech je vidno distribúciu a dá sa prah overiť dátami,
    nie odhadom. Sieť: len lokálny YAR embed + hs search. Beží pod .venv-yar.
    """
    from embed_yar import embed_one
    import zol_mem

    if not os.path.exists(CANARIES):
        print(json.dumps({"error": f"canary korpus neexistuje: {CANARIES}"},
                         ensure_ascii=False))
        return 1
    canaries = json.load(open(CANARIES))
    min_score = 0.35
    for a in sys.argv:
        if a.startswith("--min-score="):
            min_score = float(a.split("=", 1)[1])
    FETCH = 10

    def recall_fn(query):
        vec = embed_one(query)
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        # RAW absolútny proxy istoty (NIE min-max) — canary bez matchu = veľká vzdialenosť
        return [{"id": r.get("id"), "score": 1.0 / (1.0 + r.get("distance", 9e9))}
                for r in res]

    report = run_canaries(canaries, recall_fn, min_score=min_score)

    print(f"\n=== KNOWLEDGE-GAP CANARY EVAL — {report['count']} otázok mimo KB ===\n")
    print(f"{'#':>3}  {'decision':<10}{'top_score':>10}  query")
    print("-" * 72)
    for row in report["rows"]:
        ts = row.get("top_score")
        ts_s = f"{ts:.3f}" if isinstance(ts, (int, float)) else "—"
        print(f"{report['rows'].index(row) + 1:>3}  {row['decision']:<10}{ts_s:>10}  "
              f"{row['query'][:44]}")
    print("-" * 72)
    print(f"total_score={report['total_score']}  (ideál 0 = samé abstain; "
          f"každé answered = -4)")
    print(f"abstain={report.get('abstain', 0)}  answered={report.get('answered', 0)}  "
          f"error={report.get('error', 0)}  ready={report.get('ready')}  "
          f"min_score={min_score}")
    if report.get("answered"):
        print("\n⚠  Niektoré canary vrátili silný recall — buď (a) prah min_score je "
              "nízko a treba kalibrovať, alebo (b) KB naozaj obsahuje príbuzný fakt "
              "(vtedy to nie je čistá canary). Pozri top_score distribúciu vyššie.")
    return 0


if __name__ == "__main__":
    if "--canary" in sys.argv:
        sys.exit(main_canary())
    sys.exit(main())
