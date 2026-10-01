#!/usr/bin/env python3
"""edge_phase3_epistemic_3lab.py — DORIESENIE 24 zvysnych INVERTED (epistemicky klaster).

NENAVODNY 3-lab test (opus+gemini+gpt) + geometria (r_opus) ako nezavisly prior.
Kazda hrana (dieta, hub) sa predlozi ako neutralny par Vyrok A / Vyrok B v NAHODNOM
poradi, ziadne slovo rodic/dieta/apex. Otazka: subsumuje jeden druhy a KTORY, alebo
siblings?

PRAVIDLO ROZHODNUTIA (stanovene VOPRED, pred videnim LLM vystupu):
  g = geometria:  isa   ak r_hub - r_child >  MARGIN
                  rev   ak r_child - r_hub >  MARGIN
                  sib   inak (|delta| <= MARGIN)
  lab = vacsina z {opus,gemini,gpt} po norme na vztah dieta->hub
        (is_a_keep / reverse / sibling)
  ROZHODNUTIE:
    keep     ak g==isa  A lab==is_a_keep   (necha parent hranu, INVERTED bol false-positive layeru)
    reverse  ak g==rev  A lab==reverse      (otoci hranu: dieta sa stane rodicom hubu)
    related  inak                            (konzervativny default pri spore/sibling)

Iba CITA + LLM. Zapise state/edge_phase3_epistemic_3lab.json. NIC nemeni v grafe.
"""
import os, sys, json, time, random
from collections import Counter

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "edge_phase3_epistemic_3lab.json")
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from palantir_client import chat

MARGIN = 0.05
# 24 INVERTED hrany (dieta, hub)
EDGES = [(347,685),(449,685),(478,685),(487,685),(490,685),(492,685),(509,685),(512,685),
         (515,685),(552,685),(559,685),(567,685),(570,685),(640,685),(667,685),(670,685),
         (677,685),(558,685),(347,558),(490,558),(492,558),(512,558),(515,558),(552,558)]
random.seed(42)

SYS = ("Si expert na lexikalnu semantiku a subsumpciu (is-a / hyponymia). Dostanes dvojice "
       "vyrokov A a B. Pre kazdu dvojicu rozhodni ci jeden vyrok je STRIKTNE VSEOBECNEJSIA "
       "kategoria a druhy jeho instancia/specialny pripad, alebo su na ROVNAKEJ urovni "
       "vseobecnosti (susedne tvrdenia o tej istej teme = siblings). NEPREDPOKLADAJ ze "
       "niektory je nadradeny. Odpovedas VYLUCNE platnym JSON.")

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def txt(rows, mid):
    return (rows[mid].get("text") or "").replace("\n", " ").strip()

def build(rows, pairs):
    lines = ["Pre KAZDY par urci vztah medzi Vyrokom A a Vyrokom B:", ""]
    for i, (a, b) in enumerate(pairs):
        lines.append(f"PAR {i}:")
        lines.append(f"  A: {txt(rows,a)}")
        lines.append(f"  B: {txt(rows,b)}")
        lines.append("")
    lines.append('Pre kazdy par vrat relation: "A_subsumes_B" (A je vseobecnejsia kategoria, '
                 'B jej instancia), "B_subsumes_A" (opak), alebo "siblings" (rovnaka uroven).')
    lines.append('FORMAT: {"pairs":[{"par":0,"relation":"..."},...]}')
    return "\n".join(lines)

def call(model, prompt, budget):
    try:
        raw = chat(prompt, model=model, max_tokens=budget, system=SYS)
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"): raw = raw[4:]
        s, e = raw.find("{"), raw.rfind("}")
        return {"ok": True, "parsed": json.loads(raw[s:e+1])}
    except Exception as ex:
        return {"ok": False, "err": f"{type(ex).__name__}: {ex}"}

def norm(rel, hub_is_A):
    if rel == "siblings": return "sibling"
    if rel == "A_subsumes_B":
        return "is_a_keep" if hub_is_A else "reverse"
    if rel == "B_subsumes_A":
        return "reverse" if hub_is_A else "is_a_keep"
    return None

def main():
    rows = load_idx()
    # priprav pary v nahodnom poradi
    order, pairs = [], []
    for i, (child, hub) in enumerate(EDGES):
        if random.random() < 0.5:
            a, b, hub_is_A = hub, child, True
        else:
            a, b, hub_is_A = child, hub, False
        pairs.append((a, b)); order.append((i, hub_is_A))
    prompt = build(rows, pairs)
    print(f"{len(EDGES)} parov, prompt {len(prompt)} zn.")

    labs = {}
    for name, budget in [("opus", 8000), ("gemini", 16000), ("gpt", 16000)]:
        labs[name] = call(name, prompt, budget)
        print(f"  {name} ok={labs[name]['ok']}" + ("" if labs[name]["ok"] else f"  ERR={labs[name]['err']}"))
        time.sleep(1.5)

    def relmap(res):
        if not res.get("ok"): return {}
        return {p["par"]: p.get("relation") for p in res["parsed"].get("pairs", [])}
    lm = {k: relmap(v) for k, v in labs.items()}

    rows_out = []
    cfinal = Counter()
    for (i, hub_is_A) in order:
        child, hub = EDGES[i]
        rc, rh = rows[child].get("layer_score"), rows[hub].get("layer_score")
        delta = round((rh or 0) - (rc or 0), 3)
        g = "isa" if delta > MARGIN else ("rev" if delta < -MARGIN else "sib")
        votes = {n: norm(lm[n].get(i), hub_is_A) for n in ("opus", "gemini", "gpt")}
        vc = Counter(v for v in votes.values() if v)
        lab = vc.most_common(1)[0][0] if vc else None
        if g == "isa" and lab == "is_a_keep":
            decision = "keep"
        elif g == "rev" and lab == "reverse":
            decision = "reverse"
        else:
            decision = "related"
        cfinal[decision] += 1
        rows_out.append({"child": child, "hub": hub, "r_child": rc, "r_hub": rh,
                         "delta": delta, "geom": g, "votes": votes, "lab_majority": lab,
                         "decision": decision})

    print("\ndieta->hub | delta geom | opus/gem/gpt | lab | ROZHODNUTIE")
    for x in rows_out:
        v = x["votes"]
        print(f"  #{x['child']}->#{x['hub']}  d={x['delta']:+.2f} {x['geom']:>3} | "
              f"{v['opus']}/{v['gemini']}/{v['gpt']} | {x['lab_majority']} | {x['decision'].upper()}")
    print(f"\nROZHODNUTIA: {dict(cfinal)}  (z {len(EDGES)})")

    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "margin": MARGIN,
           "labs_ok": {k: v["ok"] for k, v in labs.items()},
           "rows": rows_out, "summary": dict(cfinal),
           "labs_raw": {k: v for k, v in labs.items()}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapisane: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
