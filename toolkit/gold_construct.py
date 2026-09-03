#!/usr/bin/env python3
"""gold_construct.py — NEZAVISLY gold pre geometricku falzifikaciu.

Ciel: gold-pary (dieta -> pravi rodicia) rozhodnute opusom NASLEPO na semantiku,
BEZ layeru/r_opus/cisel -> nezavisle od toho co meriame. Rozbije cirkularitu
"gold = vyssia vrstva" z predosleho testu (kde layer int mal domacu vyhodu).

FER-NOST (aby ziadny variant nedostal vyhodu):
- opus vidi LEN TEXTY (ziadny layer, r, id-poradie nesie info -> randomizovane)
- kandidat pool = UNION(top cosine, top hyper-disc, existujuce hrany, random)
  -> aj cosine-daleky pravy rodic ma sancu dostat sa pred opus (inak podhodnotim hyperbolu)
- rozhodnutie binarne: "je K abstraktnejsi NADRADENY koncept co zastresuje dieta?"

Resumovatelne: gold_pairs.jsonl (jeden riadok na dieta)."""
import json, os, sys, math, random, argparse

sys.path.insert(0, os.path.expanduser("~/projects/__PROJECT__/toolkit"))
from palantir_client import chat

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
DATA = os.path.join(STATE, "geom_data.json")
OUT = os.path.join(STATE, "gold_pairs.jsonl")
LORD = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

SYSTEM = (
    "Si expert na pojmovú hierarchiu. Rozhoduješ VÝHRADNE podľa významu textov, "
    "nič iné nemáš k dispozícii. Definícia: kandidát je NADRADENÝ koncept dieťaťa, "
    "ak je to VŠEOBECNEJŠÍ princíp/kategória/abstrakcia, ktorá dieťa zastrešuje "
    "(dieťa je konkrétny prípad / inštancia / dôsledok kandidáta). NIE je nadradený, "
    "ak je len tematicky príbuzný, rovnako konkrétny, alebo konkrétnejší. Vráť čistý JSON."
)
# VARIANT B: iny ramec — strom/is-a namiesto 'nadradeny koncept/subsumpcia'
SYSTEM_B = (
    "Predstav si STROM pojmov, kde konkrétne veci sú listy a všeobecné kategórie sú vetvy nad nimi. "
    "Pre dané DIEŤA vyber tých kandidátov, ktorí by v takom strome boli PRIAMO NAD ním ako jeho "
    "vetva/kategória (platí 'DIEŤA JE DRUH/PRÍPAD KANDIDÁTA' alebo 'DIEŤA PATRÍ POD KANDIDÁTA'). "
    "Vylúč kandidátov čo sú len vedľa (súrodenci), rovnako konkrétni, alebo pod dieťaťom. "
    "Vráť čistý JSON."
)
PROMPT_A = ("Ktoré z kandidátov [id] sú SKUTOČNE nadradené koncepty, čo zastrešujú dieťa? "
            'Buď prísny. Vráť JSON {"parents": [id, ...]} (prázdny zoznam ak žiadny).')
PROMPT_B = ("Ktorí kandidáti [id] by boli v strome pojmov PRIAMO NAD dieťaťom (dieťa je ich druh/prípad)? "
            'Buď prísny. Vráť JSON {"parents": [id, ...]} (prázdny zoznam ak žiadny).')
GVARIANTS = {"a": (SYSTEM, PROMPT_A), "b": (SYSTEM_B, PROMPT_B)}

def cos(a, b):
    return sum(x*y for x, y in zip(a, b))
def to_lor(u, r):
    ch, sh = math.cosh(r), math.sinh(r)
    return (ch, [sh*x for x in u])
def ldist(A, B):
    x0, xr = A; y0, yr = B
    val = -(-x0*y0 + sum(a*b for a, b in zip(xr, yr)))
    val = 1.0 if val < 1 else (1e6 if val > 1e6 else val)
    return math.acosh(val)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="opus", help="model-rozhodca (opus default, gpt cross-lab)")
    ap.add_argument("--out", default=OUT, help="vystupny gold subor")
    ap.add_argument("--variant", default="a", choices=["a", "b"], help="a=nadradeny koncept, b=strom/is-a")
    args = ap.parse_args()
    out_path = args.out
    mdl = args.model
    gsystem, gphead = GVARIANTS[args.variant]
    random.seed(29)
    data = {int(k): v for k, v in json.load(open(DATA, encoding="utf-8")).items()
            if "gemma" in v}
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    have = [i for i in data if i in rows]
    text_of = {i: (rows[i].get("text") or "")[:240] for i in have}

    # existujuce parent hrany (na obohatenie poolu, NIE ako gold)
    edges = []
    ep = os.path.join(STATE, "mem_edges.jsonl")
    if os.path.exists(ep):
        for l in open(ep, encoding="utf-8"):
            l = l.strip()
            if l: edges.append(json.loads(l))
    parent_hint = {}
    for e in edges:
        if e.get("edge") == "parent":
            parent_hint.setdefault(e.get("from"), set()).add(e.get("to"))

    # lorentz body pre hyper-disc kandidatov (polomer = diskretny layer)
    r_disc = {i: 0.3 + ((3 - LORD.get(rows[i].get("layer"), 0))/3.0) for i in have}
    lor = {i: to_lor(data[i]["gemma"], r_disc[i]) for i in have}

    # deti = stratifikovana vzorka L0/L1/L2 (L3 su na vrchu, nemaju rodicov)
    by_layer = {"L0": [], "L1": [], "L2": []}
    for i in have:
        li = rows[i].get("layer")
        if li in by_layer:
            by_layer[li].append(i)
    for k in by_layer:
        random.shuffle(by_layer[k])
    children = by_layer["L0"][:30] + by_layer["L1"][:25] + by_layer["L2"][:20]

    done = set()
    if os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            l = l.strip()
            if l: done.add(json.loads(l)["child"])
    todo = [c for c in children if c not in done]
    print(f"[gold] model={mdl} deti_spolu={len(children)} hotovo={len(done)} treba={len(todo)}", file=sys.stderr)

    fout = open(out_path, "a", encoding="utf-8")
    for n, c in enumerate(todo, 1):
        # kandidat pool = union(top12 cosine, top12 hyper-disc, hrany, 8 random)
        others = [i for i in have if i != c]
        by_cos = sorted(others, key=lambda j: cos(data[c]["gemma"], data[j]["gemma"]), reverse=True)[:12]
        by_hyp = sorted(others, key=lambda j: -ldist(lor[c], lor[j]), reverse=True)[:12]
        rand = random.sample(others, min(8, len(others)))
        pool = list(dict.fromkeys(by_cos + by_hyp + list(parent_hint.get(c, [])) + rand))
        pool = [p for p in pool if p in text_of]
        random.shuffle(pool)  # proti positional biasu

        lines = "\n".join(f'[{p}] {text_of[p]}' for p in pool)
        prompt = (
            f"DIEŤA (konkrétny výrok):\n{text_of[c]}\n\n"
            f"KANDIDÁTI (možní nadradení):\n{lines}\n\n"
            + gphead
        )
        parents = []
        for attempt in range(3):
            try:
                mt = 9000 if mdl in ("gpt", "gemini", "gpt55", "flash") else 400
                txt = chat(prompt, model=mdl, max_tokens=mt, system=gsystem).strip()
                a, b = txt.find("{"), txt.rfind("}")
                obj = json.loads(txt[a:b+1])
                parents = [int(x) for x in obj.get("parents", []) if int(x) in text_of and int(x) != c]
                break
            except Exception as e:
                if attempt == 2:
                    print(f"[gold] FAIL child={c}: {str(e)[:100]}", file=sys.stderr)
        fout.write(json.dumps({"child": c, "pool": pool, "parents": parents,
                               "child_layer": rows[c].get("layer")}, ensure_ascii=False) + "\n")
        fout.flush()
        if n % 10 == 0:
            print(f"[gold] {n}/{len(todo)}", file=sys.stderr)
    fout.close()
    # sumar
    allrows = [json.loads(l) for l in open(out_path, encoding="utf-8") if l.strip()]
    tot_pairs = sum(len(r["parents"]) for r in allrows)
    print(json.dumps({"children": len(allrows), "gold_pairs": tot_pairs,
                      "children_with_parent": sum(1 for r in allrows if r["parents"])}))

if __name__ == "__main__":
    main()
