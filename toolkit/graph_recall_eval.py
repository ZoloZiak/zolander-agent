#!/usr/bin/env python3
"""graph_recall_eval.py — A/B: flat hybrid recall vs graph-expanded (RippleMem/GraphMemix/HERO/ŽL7).

Otázka (feasibility, Z1-disciplína): pridá graph expansion (related susedia top
seedov ako dôkazoví kandidáti) reálnu hodnotu recall-u, alebo len šum?
Meria sa NAOSTRO na state/mem_eval_gold.json, R@1/R@3/R@5/MRR + delta.

Metóda (identická s mem_eval, plus expanded variant):
  FLAT      : min-max fúzia sem(YAR) + W_LEX*lex(BM25), zorad, rank targetu.
  EXPANDED  : ako flat, ale top-N seedov rozšírime o related susedov z grafu;
              sused dostane seed_score * hop_decay; re-fúzia; rank targetu.

Verdikt (Z1-štýl, cross rôzne hop_decay):
  R@k stúpne          → VALIDATED, kandidát na produkčný hook
  R@k klesne          → INVALIDATED (expansion tlačí target nadol = šum)
  bez zmeny           → NEUTRAL (nemá zmysel platiť réžiou grafu)

Beží pod .venv-yar (YAR embed + hs search, lokálne). Sietovo len lokálny stack.
"""
import os
import sys
import json

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
TOOLKIT = os.path.join(ROOT, "toolkit")
sys.path.insert(0, TOOLKIT)

W_LEX = 1.6   # zmerané optimum z mem_eval
W_SEM = 1.0
FETCH = 20
DECAYS = [0.4, 0.55, 0.7]     # rôzne sily expansion — cross, nie jeden bod
MAX_SEEDS = 3
MAX_NEIGH = 2


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


def main():
    from embed_yar import embed_one
    import zol_mem
    import mem_lexical
    import zol_graph

    gold = json.load(open(GOLD))

    # 1) raz zozbieraj sem+lex skóre a fused ordering pre každú otázku
    per_q = []
    for g in gold:
        q, target = g["query"], g["id"]
        vec = embed_one(q)
        res = zol_mem.hs("search", zol_mem.MEM_COL, FETCH,
                         stdin=json.dumps({"vector": vec})) or []
        sem = {r.get("id"): 1.0 / (1.0 + r.get("distance", 9e9)) for r in res}
        lex = {mid: sc for mid, sc, _ in mem_lexical.search(q, topk=FETCH)}
        per_q.append({"target": target, "sem": sem, "lex": lex})

    def fused_order(pq):
        sn = _norm(list(pq["sem"].items()))
        ln = _norm(list(pq["lex"].items()))
        ids = set(sn) | set(ln)
        fused = {i: W_SEM * sn.get(i, 0) + W_LEX * ln.get(i, 0) for i in ids}
        return fused

    # FLAT baseline
    flat_ranks = []
    for pq in per_q:
        fused = fused_order(pq)
        ordered = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
        flat_ranks.append(rank_of(pq["target"], ordered))
    fr = metrics(flat_ranks)

    print(f"\n=== GRAPH-RECALL A/B — {len(gold)} gold otázok ===\n")
    print(f"{'režim':<22}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'MRR':>7}")
    print("-" * 50)
    print(f"{'FLAT (baseline)':<22}{fr[0]:>7.3f}{fr[1]:>7.3f}{fr[2]:>7.3f}{fr[3]:>7.3f}")

    results = {"flat": fr, "expanded": {}}

    # EXPANDED variant pre každý decay
    for decay in DECAYS:
        exp_ranks = []
        helped, hurt = 0, 0
        total_added = 0        # koľko susedov sa REÁLNE pridalo (mimo fetch set)
        total_boosted = 0      # koľko susedov už bolo vo fetch sete (len boost)
        target_touched = 0     # koľkokrát bol dotknutý uzol samotný target
        for pq in per_q:
            fused = dict(fused_order(pq))
            ordered = sorted(fused.items(), key=lambda kv: -kv[1])
            seen = set(fused)
            # top-N seedov → related susedia
            for sid, sscore in ordered[:MAX_SEEDS]:
                try:
                    edges = zol_graph.neighbors(sid, "related") or []
                except Exception:
                    continue
                added = 0
                for e in edges:
                    nid = e.get("to") if e.get("from") == sid else e.get("from")
                    if nid is None:
                        continue
                    if nid in seen:
                        # už v sade — expansion by ho len boostla (ale nepridá znova)
                        if nid not in fused:
                            continue
                    if nid == pq["target"]:
                        target_touched += 1
                    if nid in fused:
                        total_boosted += 1
                    else:
                        total_added += 1
                    if nid in seen and nid != sid:
                        pass
                    fused[nid] = fused.get(nid, 0.0) + sscore * decay
                    seen.add(nid)
                    added += 1
                    if added >= MAX_NEIGH:
                        break
            ordered2 = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
            r_before = flat_ranks[len(exp_ranks)]
            r_after = rank_of(pq["target"], ordered2)
            if r_after and (r_before == 0 or r_after < r_before):
                helped += 1
            elif r_before and (r_after == 0 or r_after > r_before):
                hurt += 1
            exp_ranks.append(r_after)
        er = metrics(exp_ranks)
        results["expanded"][decay] = {"metrics": er, "helped": helped, "hurt": hurt}
        d_mrr = er[3] - fr[3]
        print(f"{'EXP decay='+str(decay):<22}{er[0]:>7.3f}{er[1]:>7.3f}{er[2]:>7.3f}{er[3]:>7.3f}"
              f"   Δmrr={d_mrr:+.3f}  helped={helped} hurt={hurt}")
        print(f"    ↳ susedia: pridaných(mimo fetch)={total_added}, boostnutých(už vo fetch)={total_boosted}, "
              f"target dotknutý expansion={target_touched}x")

    print("-" * 50)
    # verdikt
    best_decay = max(results["expanded"], key=lambda d: results["expanded"][d]["metrics"][3])
    best = results["expanded"][best_decay]
    d_r1 = best["metrics"][0] - fr[0]
    d_mrr = best["metrics"][3] - fr[3]
    if d_mrr > 0.01 or d_r1 > 0.01:
        verdict = f"VALIDATED (najlepší decay={best_decay}, Δmrr={d_mrr:+.3f}, ΔR@1={d_r1:+.3f})"
    elif d_mrr < -0.01 or d_r1 < -0.01:
        verdict = f"INVALIDATED (expansion škodí, najlepší decay={best_decay} stále Δmrr={d_mrr:+.3f})"
    else:
        verdict = f"NEUTRAL (žiadny merateľný rozdiel, Δmrr={d_mrr:+.3f}) — nezapínať, réžia bez zisku"
    print("VERDIKT:", verdict)
    print("\nPOZOR: gold n=24 je malá vzorka — verdikt je smerový, nie definitívny (Z1 lekcia).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
