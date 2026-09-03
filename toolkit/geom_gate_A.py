#!/usr/bin/env python3
"""geom_gate_A.py — KROK A (GATE) pre geometricky experiment.

Otazka: vie LLM KONZISTENTNE priradit abstraktnost ako float 0-1?
Ak NIE (poor test-retest r), premisa product-space AJ hyperboly PADA (pasca #1:
nekalibrovany sumovy ordinal) -> stroje netreba stavat. Falzifikacne, nie potvrdzovacne.

Metoda: stratifikovana vzorka 60 (L0/L1/L2/L3), LLM skoruje 2x NEZAVISLE s INOU
zoskupovacou schemou (pass1 = zoskupene po vrstve zamiesane, pass2 = ine zamiesanie
+ ine baliky) -> test robustnosti na kontext, nie memorovanie. Pearson + Spearman.

Beh: cez palantir_client (stdlib urllib, SSL fix v kliente). Model default gpt-mini
(rychly, lacny; gate je o konzistencii nie o "spravnej" hodnote)."""
import json, os, sys, random, statistics, argparse

sys.path.insert(0, os.path.expanduser("~/projects/__PROJECT__/toolkit"))
from palantir_client import chat

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "geom_gate_A.json")

SYSTEM = (
    "Si merací aparát na ABSTRAKTNOSŤ textu. Abstraktnosť = ako všeobecný/nadradený je "
    "výrok. 0.0 = úplne konkrétny fakt/udalosť/riadok kódu (napr. 'súbor X má bug na "
    "riadku 42', 'stretol som sa s Petrom v utorok'). 1.0 = najvšeobecnejší princíp/"
    "svetonázor (napr. 'realita je jediný arbiter pravdy'). Medzi tým plynulá škála. "
    "Skóruj IBA abstraktnosť, NIE dôležitosť ani pravdivosť. Vráť čistý JSON."
)

def load_sample(n_per_layer):
    rows = []
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            rows.append(json.loads(l))
    random.seed(42)
    by = {"L0": [], "L1": [], "L2": [], "L3": []}
    for r in rows:
        ly = r.get("layer")
        if ly in by and (r.get("text") or "").strip():
            by[ly].append(r)
    sample = []
    for ly, items in by.items():
        random.shuffle(items)
        sample.extend(items[:n_per_layer])
    return sample

def score_batch(items, model):
    """items = list {id,text}; vrati {id: float}."""
    lines = "\n".join(f'{it["id"]}: {(it["text"] or "")[:220]}' for it in items)
    prompt = (
        "Oskóruj abstraktnosť (0.0-1.0) KAŽDÉHO výroku. Vráť JSON objekt "
        '{"<id>": <float>, ...} pre VŠETKY id nižšie, nič iné:\n\n' + lines
    )
    txt = chat(prompt, model=model, max_tokens=(9000 if model in ("gemini","flash","gpt","gpt55") else 1500), system=SYSTEM).strip()
    # vytiahni JSON blok
    a, b = txt.find("{"), txt.rfind("}")
    obj = json.loads(txt[a:b+1])
    return {int(k): float(v) for k, v in obj.items()}

def score_pass(sample, model, seed, batch):
    random.seed(seed)
    order = sample[:]
    random.shuffle(order)
    scores = {}
    for i in range(0, len(order), batch):
        chunk = [{"id": r["id"], "text": r["text"]} for r in order[i:i+batch]]
        for attempt in range(2):
            try:
                scores.update(score_batch(chunk, model))
                break
            except Exception as e:
                if attempt == 1:
                    print(f"  ! batch fail: {e}", file=sys.stderr)
    return scores

def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sx = sum((x-mx)**2 for x in xs) ** 0.5
    sy = sum((y-my)**2 for y in ys) ** 0.5
    return cov/(sx*sy) if sx and sy else 0.0

def spearman(xs, ys):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0]*len(v)
        for rk, i in enumerate(s):
            r[i] = rk
        return r
    return pearson(rank(xs), rank(ys))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-mini")
    ap.add_argument("--n-per-layer", type=int, default=15)
    args = ap.parse_args()

    sample = load_sample(args.n_per_layer)
    print(f"[gate] vzorka={len(sample)} model={args.model}", file=sys.stderr)

    p1 = score_pass(sample, args.model, seed=1, batch=12)
    p2 = score_pass(sample, args.model, seed=99, batch=8)  # ine zamiesanie + ine baliky

    common = [r["id"] for r in sample if r["id"] in p1 and r["id"] in p2]
    xs = [p1[i] for i in common]
    ys = [p2[i] for i in common]

    # per-vrstva priemer (monotonia L0<L1<L2<L3?)
    idmap = {r["id"]: r["layer"] for r in sample}
    bylayer = {}
    for i in common:
        avg = (p1[i]+p2[i])/2
        bylayer.setdefault(idmap[i], []).append(avg)
    layer_means = {ly: round(statistics.mean(v), 3) for ly, v in sorted(bylayer.items())}

    result = {
        "model": args.model,
        "n_scored_both": len(common),
        "pearson_test_retest": round(pearson(xs, ys), 3) if len(common) > 2 else None,
        "spearman_test_retest": round(spearman(xs, ys), 3) if len(common) > 2 else None,
        "mean_abs_diff": round(statistics.mean(abs(a-b) for a, b in zip(xs, ys)), 3) if common else None,
        "layer_means": layer_means,
        "round_number_bias": round(sum(1 for v in xs+ys if round(v*10) == v*10)/len(xs+ys), 3) if common else None,
        "p1": {str(i): p1[i] for i in common},
        "p2": {str(i): p2[i] for i in common},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    # kratke zhrnutie na stdout
    print(json.dumps({k: v for k, v in result.items() if k not in ("p1", "p2")},
                     ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
