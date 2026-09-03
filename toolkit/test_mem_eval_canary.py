#!/usr/bin/env python3
"""Offline tests for Knowledge-Gap Canaries (arXiv 2608.26385) helpers.

Canary questions are provably absent from the KB. A confident/evidenced answer is
therefore wrong (-4); abstention is neutral (0). Correct +1 is kept for normal
non-canary scoring symmetry.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mem_eval as me  # noqa: E402

fails = []


def check(name, cond):
    print(f"  {'ok' if cond else 'FAIL'}  {name}")
    if not cond:
        fails.append(name)


print("=== Knowledge-Gap Canary scoring ===")

try:
    check("correct = +1", me.canary_score("correct") == 1)
    check("abstain = 0", me.canary_score("abstain") == 0)
    check("answered/wrong = -4", me.canary_score("answered") == -4)

    empty = me.score_canary_results([])
    check("empty results -> abstain", empty["decision"] == "abstain" and empty["score"] == 0)

    weak = me.score_canary_results([{"id": 1, "score": 0.12}], min_score=0.35)
    check("weak evidence -> abstain", weak["decision"] == "abstain" and weak["score"] == 0)

    strong = me.score_canary_results([{"id": 7, "score": 0.91}], min_score=0.35)
    check("strong evidence on absent answer -> wrong", strong["decision"] == "answered" and strong["score"] == -4 and strong["top_id"] == 7)

    canaries = [{"query": "neexistujúci fakt A"}, {"query": "neexistujúci fakt B"}]
    by_query = {
        "neexistujúci fakt A": [],
        "neexistujúci fakt B": [{"id": 9, "score": 0.7}],
    }
    report = me.evaluate_canary_results(canaries, by_query, min_score=0.35)
    check("aggregate total = -4", report["total_score"] == -4)
    check("aggregate counts", report["abstain"] == 1 and report["answered"] == 1)
except AttributeError as exc:
    fails.append("missing helper: " + str(exc))
    print("FAIL missing helper:", exc)


print("\n=== Live canary runner (run_canaries + recall_fn seam) ===")

try:
    # recall_fn(query) -> list[{id, score}]. Dependency-injected, aby test bežal
    # offline bez DB. CLI napojí reálny embed+search recall_fn.
    calls = []

    def recall_absent(query):
        # KB nemá odpoveď na canary → prázdny recall = korektné abstain
        calls.append(query)
        return []

    def recall_confident(query):
        # systém vytiahol silný "dôkaz" na fakt čo v KB NIE je → halucinácia (-4)
        calls.append(query)
        return [{"id": 42, "score": 0.88}]

    def recall_weak(query):
        calls.append(query)
        return [{"id": 7, "score": 0.12}]  # pod prahom → abstain

    cans = [{"query": "kto je prezident Antarktídy"}, {"query": "aké je moje PIN k neexistujúcej karte"}]

    # 1) recall_fn sa REÁLNE volá pre každú canary query
    calls.clear()
    r_abs = me.run_canaries(cans, recall_absent, min_score=0.35)
    check("run_canaries volá recall_fn pre každú query", calls == [c["query"] for c in cans])

    # 2) absent recall → všetko abstain, total 0, ready True (žiadny error)
    check("absent → total_score 0", r_abs["total_score"] == 0)
    check("absent → abstain==count", r_abs["abstain"] == len(cans) and r_abs.get("answered", 0) == 0)
    check("absent → ready True (žiadny backend error)", r_abs.get("ready") is True)

    # 3) confident recall na absent fakt → answered/-4 každý (najhorší prípad: halucinácia)
    r_conf = me.run_canaries(cans, recall_confident, min_score=0.35)
    check("confident → total_score -4*n", r_conf["total_score"] == -4 * len(cans))
    check("confident → answered==count", r_conf["answered"] == len(cans))

    # 4) weak recall pod prahom → abstain (nie answered)
    r_weak = me.run_canaries(cans, recall_weak, min_score=0.35)
    check("weak pod prahom → abstain", r_weak["abstain"] == len(cans) and r_weak.get("answered", 0) == 0)

    # 5) recall_fn padne pre JEDNU query → error decision, beh sa NEZHODÍ, ostatné spracované,
    #    a error NESMIE byť tichým "abstain" (to by maskovalo pád DB ako správne abstinovanie)
    def recall_flaky(query):
        if "PIN" in query:
            raise RuntimeError("DB down 127.0.0.1:50051")
        return []

    r_flaky = me.run_canaries(cans, recall_flaky, min_score=0.35)
    check("flaky → error decision existuje", r_flaky.get("error", 0) == 1)
    check("flaky → druhá query spracovaná (abstain)", r_flaky.get("abstain", 0) == 1)
    check("flaky → ready False (backend nespoľahlivý)", r_flaky.get("ready") is False)
    check("flaky → error sa NEráta ako answered ani abstain-success", r_flaky["total_score"] == 0)

    # 6) prázdny canary korpus → prázdny report, ready False (niet čo merať)
    r_empty = me.run_canaries([], recall_absent, min_score=0.35)
    check("prázdny korpus → count 0, ready False", r_empty["count"] == 0 and r_empty.get("ready") is False)
except AttributeError as exc:
    fails.append("missing run_canaries: " + str(exc))
    print("FAIL missing run_canaries:", exc)

print(f"\n{'VYSLEDOK: vsetky canary testy OK' if not fails else 'VYSLEDOK: FAIL ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
