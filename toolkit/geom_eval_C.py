#!/usr/bin/env python3
"""geom_eval_C.py — KROK C: falzifikacny test HYPERBOLA vs PRODUCT-SPACE vs PLOCHY cosine.

Uloha (zmieseny retrieval, z docs riadok 74): pre concrete->abstract parent par je
DIETA dotaz, ciel = najst spravneho ABSTRAKTNEHO RODICA. To je presne to co hyperbola
ma vediet natvne (rodic pri origine ~ blizko vsetkemu v uhlovom sektore), a co
product-space musi robit 2 dotazmi / rucnou vahou.

LATKA (z docs riadok 86): hyperbola MUSI porazit product-space. Ak nie -> 2 polia vyhraju.

3 varianty skorovania podobnosti dieta->kandidat:
  (1) FLAT   = cosine(uhol) len. Ignoruje polomer.
  (2) PRODUCT= cosine(uhol) + bonus za to ze kandidat je ABSTRAKTNEJSI (r_kand > r_dieta).
               dve oddelene suradnice kombinovane per-dotaz (retrieval chce rodica HORE).
  (3) HYPER  = composed-Lorentz: bod = exp-map(uhol, polomer). Lorentzova vzdialenost.
               uhol+polomer zapecene do JEDNEJ metriky s nelinearnym prepojenim.

Kandidati rodica = vsetky uzly s vrstvou VYSSIE nez dieta (realisticky: hladam strechu).
Metriky: hit@1, hit@3, MRR (najdem spravneho rodica?) + AUROC parent-vs-random (baseline
0.692 cone / 0.742 distance z predosleho spike).

VSTUP: state/geom_data.json (Gemma uhol + r_opus). Ziadny YAR (to bola stara stena)."""
import json, os, sys, math, random, argparse

STATE = os.path.expanduser("~/projects/zolander/state")
DATA = os.path.join(STATE, "geom_data.json")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDG = os.path.join(STATE, "mem_edges.jsonl")
OUT = os.path.join(STATE, "geom_eval_C.json")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

def cos(a, b):
    return sum(x*y for x, y in zip(a, b))  # Gemma je L2-normalizovana -> dot = cos

# --- composed-Lorentz: exp-map z uhla (smer na sfere) + polomer (radialna suradnica) ---
def to_lorentz(unit, r):
    """unit = 768D jednotkovy vektor (smer), r = polomer >=0 (abstraktnost -> hlbka).
    Bod na hyperboloide: (cosh r, sinh r * unit). Lorentz: -x0*y0 + sum(xi*yi) = -1."""
    ch, sh = math.cosh(r), math.sinh(r)
    return (ch, [sh*u for u in unit])

def lorentz_dist(A, B):
    x0, xr = A; y0, yr = B
    mink = -x0*y0 + sum(a*b for a, b in zip(xr, yr))
    val = -mink
    if val < 1.0: val = 1.0
    elif val > 1e6: val = 1e6
    return math.acosh(val)

def load():
    data = {int(k): v for k, v in json.load(open(DATA, encoding="utf-8")).items()
            if "gemma" in v and "r_opus" in v}
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    edges = []
    for l in open(EDG, encoding="utf-8"):
        l = l.strip()
        if l: edges.append(json.loads(l))
    return data, rows, edges

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r-scale", type=float, default=1.0,
                    help="skala polomeru: radialny rozptyl")
    ap.add_argument("--product-w", type=float, default=0.3,
                    help="vaha abstraktnostneho bonusu v product-space")
    ap.add_argument("--r-mode", choices=["abstract_far", "abstract_near"], default="abstract_near",
                    help="abstract_near = KOREN pri origine (r=konkretnost, hierarchicky spravne); "
                         "abstract_far = abstraktne daleko (moja povodna CHYBA, ponechane na kontrolu)")
    args = ap.parse_args()

    data, rows, edges = load()
    have = set(data)
    # concrete->abstract parent pary (dieta -> spravny rodic), oba s datami
    gold = []
    for e in edges:
        if e.get("edge") != "parent": continue
        f, t = e.get("from"), e.get("to")
        if f in have and t in have:
            lf, lt = LORD.get(rows[f].get("layer"), -1), LORD.get(rows[t].get("layer"), -1)
            if lt > lf:
                gold.append((f, t))
    # dedup: jedno dieta moze mat viac rodicov -> mnozina spravnych na dieta
    from collections import defaultdict
    parents = defaultdict(set)
    for f, t in gold:
        parents[f].add(t)
    children = sorted(parents)
    print(f"[eval] uzlov s datami={len(have)} gold_deti={len(children)} gold_hran={len(gold)}", file=sys.stderr)

    # predpocitaj lorentz body. HIERARCHICKY SPRAVNE (abstract_near): koren pri
    # origine (mala r), listy pri hranici (velka r) -> r = KONKRETNOST = (1 - r_opus).
    # abstract_far = povodna chyba (r = r_opus), ponechane na kontrolny beh.
    def r_of_fn(i):
        conc = (1.0 - data[i]["r_opus"]) if args.r_mode == "abstract_near" else data[i]["r_opus"]
        return 0.3 + conc*args.r_scale
    r_of = {i: r_of_fn(i) for i in have}
    lor = {i: to_lorentz(data[i]["gemma"], r_of[i]) for i in have}
    # DISKRETNY STROM baseline (RFC r.420 latka): polomer = layer int (4 biny), NIE spojity opus.
    # conc_layer: L0=1.0 (konkretne, r velka), L3=0.0 (abstraktne, r mala pri origine).
    def r_disc_fn(i):
        li = LORD.get(rows[i].get("layer"), 0)
        conc = (3 - li)/3.0  # L0->1, L1->.667, L2->.333, L3->0
        return 0.3 + conc*args.r_scale
    lor_disc = {i: to_lorentz(data[i]["gemma"], r_disc_fn(i)) for i in have}

    def rank_parents(child, scorer, layer_filter=True):
        """kandidati = uzly ABSTRAKTNEJSIE (vyssia vrstva) nez dieta. Vrat zoradene id.
        layer_filter=False -> kandidat je HOCIKTORY uzol (zmieseny retrieval, docs r.74:
        jeden kNN vrati aj susedov AJ abstrakciu -> tu ma hyperbola mat nativnu vyhodu)."""
        lc = LORD.get(rows[child].get("layer"), -1)
        if layer_filter:
            cands = [i for i in have if i != child and LORD.get(rows[i].get("layer"), -1) > lc]
        else:
            cands = [i for i in have if i != child]
        scored = sorted(cands, key=lambda j: scorer(child, j), reverse=True)
        return scored

    def s_flat(c, j):
        return cos(data[c]["gemma"], data[j]["gemma"])
    def s_product(c, j):
        ang = cos(data[c]["gemma"], data[j]["gemma"])
        # bonus ak kandidat abstraktnejsi (rodic ma byt HORE); skala rozdielu polomeru
        return ang + args.product_w * (data[j]["r_opus"] - data[c]["r_opus"])
    def s_hyper(c, j):
        return -lorentz_dist(lor[c], lor[j])  # blizsie = vyssie skore
    def s_hyper_disc(c, j):
        return -lorentz_dist(lor_disc[c], lor_disc[j])  # diskretny strom (RFC latka)

    def eval_variant(scorer, layer_filter=True):
        h1 = h3 = 0; rr = 0.0; n = 0
        for c in children:
            ranked = rank_parents(c, scorer, layer_filter=layer_filter)
            if not ranked: continue
            n += 1
            gold_set = parents[c]
            # rank spravnehno rodica (najlepsi z gold_set)
            best = min((ranked.index(g) for g in gold_set if g in ranked), default=None)
            if best is None: continue
            if best == 0: h1 += 1
            if best < 3: h3 += 1
            rr += 1.0/(best+1)
        return {"n": n, "hit@1": round(h1/n, 3), "hit@3": round(h3/n, 3), "MRR": round(rr/n, 3)}

    # AUROC parent-vs-random (konzistentne s predoslym spike 0.692/0.742)
    def auroc(score_fn):
        random.seed(7)
        pos = [score_fn(f, t) for f, t in gold]
        allids = list(have)
        neg = []
        for _ in range(len(gold)):
            a, b = random.sample(allids, 2)
            neg.append(score_fn(a, b))
        # AUROC = P(pos > neg)
        cnt = tie = 0
        for p in pos:
            for ng in neg:
                if p > ng: cnt += 1
                elif p == ng: tie += 1
        return round((cnt + 0.5*tie)/(len(pos)*len(neg)), 3)

    result = {
        "params": {"r_scale": args.r_scale, "product_w": args.product_w},
        "n_nodes": len(have), "n_gold_children": len(children), "n_gold_edges": len(gold),
        "retrieval": {
            "flat_cosine": eval_variant(s_flat),
            "product_space": eval_variant(s_product),
            "hyper_composed_lorentz": eval_variant(s_hyper),
            "hyper_discrete_layer": eval_variant(s_hyper_disc),
        },
        "retrieval_NOFILTER_mixed": {
            "_pozn": "bez layer filtra = zmieseny retrieval (docs r.74), hyperbolino domace ihrisko",
            "flat_cosine": eval_variant(s_flat, layer_filter=False),
            "product_space": eval_variant(s_product, layer_filter=False),
            "hyper_composed_lorentz": eval_variant(s_hyper, layer_filter=False),
            "hyper_discrete_layer": eval_variant(s_hyper_disc, layer_filter=False),
        },
        "auroc_parent_vs_random": {
            "flat_cosine": auroc(lambda a, b: cos(data[a]["gemma"], data[b]["gemma"])),
            "product_space": auroc(s_product),
            "hyper_composed_lorentz": auroc(lambda a, b: -lorentz_dist(lor[a], lor[b])),
            "hyper_discrete_layer": auroc(lambda a, b: -lorentz_dist(lor_disc[a], lor_disc[b])),
        },
        "prev_spike_baseline": {"cone_yar": 0.692, "distance_yar": 0.742},
    }
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
