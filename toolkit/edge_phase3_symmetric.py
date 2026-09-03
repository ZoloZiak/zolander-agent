#!/usr/bin/env python3
"""edge_phase3_symmetric.py — NENAVODNY cross-lab re-test epistemickeho klastra.

Preco: edge_phase3.py mal navodny prompt (hub oznaceny ako 'APEX/rodic') -> modely
anchorovali na is_a. Tento skript odstranuje kotvu:
  - kazdy par (hub, dieta) sa predlozi ako neutralne "Vyrok A" / "Vyrok B",
  - PORADIE A/B sa NAHODNE prehodi (seed fix) -> pozicna neutralita,
  - ziadne slovo rodic/dieta/apex/hierarchia,
  - otazka: subsumuje jeden druhy a KTORY, alebo su siblings?
Mapuje odpoved spat na (hub,dieta) bez ohladu na to, ci hub bol A alebo B.
opus + gemini nezavisle. Zhoda = verdikt; spor sa oznaci (neaplikuje sa).

Iba CITA + LLM. Zapise state/edge_phase3_symmetric.json. NIC nemeni v grafe."""
import os, sys, json, time, random

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "edge_phase3_symmetric.json")
sys.path.insert(0, os.path.join(HOME, "projects", "__PROJECT__", "toolkit"))
from palantir_client import chat

# hlavny hub epistemickeho klastra + jeho 17 INVERTED deti (voci #685)
HUB = 685
KIDS = [347, 449, 478, 487, 490, 492, 509, 512, 515, 552, 559, 567, 570, 640, 667, 670, 677]
random.seed(42)

SYS = ("Si expert na lexikalnu semantiku a subsumpciu (is-a / hyponymia). Dostanes dva "
       "vyroky A a B. Rozhodni ci jeden je STRIKTNE VSEOBECNEJSIA kategoria a druhy jeho "
       "instancia/podtyp, alebo su na ROVNAKEJ urovni vseobecnosti (susedne tvrdenia o tej "
       "istej teme = siblings). NEPREDPOKLADAJ ze niektory je nadradeny. Odpovedas VYLUCNE "
       "platnym JSON.")

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
    """pairs: list of (idA, idB) uz v nahodnom poradi."""
    lines = ["Pre KAZDY par urci vztah medzi Vyrokom A a Vyrokom B:", ""]
    for i, (a, b) in enumerate(pairs):
        lines.append(f"PAR {i}:")
        lines.append(f"  A: {txt(rows,a)}")
        lines.append(f"  B: {txt(rows,b)}")
        lines.append("")
    lines.append('Pre kazdy par vrat relation: "A_subsumes_B" (A je vseobecnejsia '
                 'kategoria, B jej instancia), "B_subsumes_A" (opak), alebo "siblings" '
                 '(rovnaka uroven vseobecnosti).')
    lines.append('FORMAT: {"pairs":[{"par":0,"relation":"..."},{"par":1,"relation":"..."},...]}')
    return "\n".join(lines)

def call(model, prompt, budget=4000):
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

def main():
    rows = load_idx()
    # priprav pary v nahodnom poradi; zapamataj kde je hub
    order = []   # (parIdx, idA, idB, hub_is_A)
    pairs = []
    for i, k in enumerate(KIDS):
        if random.random() < 0.5:
            a, b, hub_is_A = HUB, k, True
        else:
            a, b, hub_is_A = k, HUB, False
        pairs.append((a, b))
        order.append((i, a, b, hub_is_A))

    prompt = build(rows, pairs)
    print(f"HUB #{HUB}, {len(KIDS)} parov, prompt {len(prompt)} zn.")
    opus = call("opus", prompt)
    time.sleep(1.5)
    gem = call("gemini", prompt, budget=12000)
    print(f"opus ok={opus['ok']} gemini ok={gem['ok']}")

    def relmap(res):
        if not res.get("ok"): return {}
        return {p["par"]: p.get("relation") for p in res["parsed"].get("pairs", [])}

    om, gm = relmap(opus), relmap(gem)

    # normalizuj na vztah dieta->hub: is_a (dieta instancia hubu) / reverse / siblings
    def norm(rel, hub_is_A):
        if rel == "siblings": return "sibling"
        if rel == "A_subsumes_B":  # A vseobecnejsie
            return "is_a" if hub_is_A else "reverse"   # ak hub=A a subsumuje -> dieta is_a hub
        if rel == "B_subsumes_A":
            return "reverse" if hub_is_A else "is_a"
        return None

    from collections import Counter
    rows_out = []
    ccons = Counter()
    for (i, a, b, hub_is_A) in order:
        k = KIDS[i]
        o = norm(om.get(i), hub_is_A); g = norm(gm.get(i), hub_is_A)
        agree = (o == g and o is not None)
        if agree: ccons[o] += 1
        r = rows[k]
        rows_out.append({"child": k, "r_opus": r.get("layer_score"),
                         "opus": o, "gemini": g, "consensus": o if agree else None,
                         "hub_pos": "A" if hub_is_A else "B"})
    print("\ndieta | r_opus | opus | gemini | KONSENZUS")
    for x in rows_out:
        mark = "" if x["consensus"] else "  <-- SPOR"
        print(f"  #{x['child']} r={x['r_opus']}  {x['opus']}/{x['gemini']} "
              f"-> {x['consensus']}{mark}")
    print(f"\nKONSENZUS distribucia: {dict(ccons)}  (z {len(KIDS)})")

    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "hub": HUB,
           "opus_raw": opus, "gemini_raw": gem, "rows": rows_out,
           "consensus": dict(ccons)}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapisane: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
