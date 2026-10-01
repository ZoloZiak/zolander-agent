#!/usr/bin/env python3
"""edge_classify_clusters.py — CROSS-LAB rozhodnutie pre INVERTED/SAME_LAYER huby.

Faza 2/3 plan (edge-cleanup): NEROB flip/reclass naslepo. Analyza (layer_score/r_opus)
ukazala ze huby #685/#558 NIE su abstraktnejsie nez ich deti -> mozno to nie je is-a
strom ale suroroenecka komunita meta-principov. Tuto otazku NEsmie rozhodnut 1 model
(cirkularita) -> pytam sa OPUS aj GEMINI nezavisle (cross-lab, pravidlo __USER__).

Pre kazdy hub: dam model hub-text + vsetky jeho deti (parent hrany mieriace nan) a pytam
sa pre klaster: is-a strom (deti su instancie hubu) ALEBO surodenci (rovnaka uroven
abstrakcie -> parent->related)? + per-dieta klasifikacia + ci hub patri vyssie (reclass).

LEN CITA graf + vola LLM. Zapise navrh do state/edge_cluster_verdict.json. NIC v grafe nemeni.
Bezi pod .venv-yar/bin/python (palantir_client z zolo2.0/toolkit).
"""
import os, sys, json

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
OUT = os.path.join(STATE, "edge_cluster_verdict.json")
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from palantir_client import chat

HUBS = [685, 558]

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def load_edges():
    out = []
    for l in open(EDGES, encoding="utf-8"):
        l = l.strip()
        if l:
            try: out.append(json.loads(l))
            except Exception: pass
    return out

def children_of(hub, edges):
    """VSETKY parent hrany mieriace na hub (to==hub, edge==parent)."""
    return [e["from"] for e in edges if e.get("edge") == "parent" and e.get("to") == hub]

SYS = (
    "Si expert na klasifikaciu vedomostnych hierarchii (is-a taxonomie). Rozlisujes ostro:\n"
    "- IS-A (parent): dieta JE instancia/podtyp/konkretizacia rodica; rodic je ABSTRAKTNEJSI "
    "nadradeny koncept ktory dieta subsumuje. Napr. 'pes' is-a 'zviera'.\n"
    "- SUROSENCI (nie is-a): dva koncepty na ROVNAKEJ urovni abstrakcie, prislusny k tej istej "
    "teme, ale ani jeden nie je nadradeny druhemu. Vztah je asociacia, nie hierarchia.\n"
    "Odpovedas VYLUCNE platnym JSON, ziadny text navyse."
)

def build_prompt(hub, kids, rows):
    hub_txt = rows[hub]["text"].replace("\n", " ").strip()
    lines = []
    for k in kids:
        t = rows[k]["text"].replace("\n", " ").strip()
        lines.append(f'  {{"id": {k}, "layer": "{rows[k].get("layer")}", "text": "{t[:280]}"}}')
    kids_block = "[\n" + ",\n".join(lines) + "\n]"
    return f"""Mam uzol RODIC a zoznam DETI ktore su nan napojene ako 'parent' hrany (deti -> rodic).
Otazka: je RODIC skutocny ABSTRAKTNEJSI nadradeny koncept, ktoreho deti su jeho instancie (is-a strom),
ALEBO je RODIC len jeden z partie SUROSENCOV na rovnakej urovni abstrakcie (potom hrany nie su is-a a maju byt 'related')?

RODIC #{hub} (layer={rows[hub].get('layer')}):
"{hub_txt}"

DETI ({len(kids)}):
{kids_block}

Vrat JSON presne v tomto tvare:
{{
  "cluster_verdict": "is_a_tree" | "siblings" | "mixed",
  "hub_is_true_apex": true | false,
  "hub_should_be_layer": "L1" | "L2" | "L3" | "same",
  "reasoning": "<1-3 vety preco>",
  "children": [
    {{"id": <int>, "relation": "is_a" | "sibling", "note": "<kratko>"}}
  ]
}}
- "is_a_tree": vacsina deti su naozaj instancie rodica (rodic je abstraktnejsi).
- "siblings": vacsina deti su surodenci rodica (rovnaka uroven) -> hrany prekvalifikovat na related.
- "mixed": cast is-a, cast surodenci -> rozhodni per dieta v poli children.
- Ak by mal existovat INY apex nez tento hub, napis to do reasoning.
- V poli children uved KAZDE dieta z inputu s jeho relation."""

def call(model, prompt):
    raw = ""
    try:
        raw = chat(prompt, model=model, max_tokens=4000, system=SYS)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return {"ok": True, "parsed": json.loads(raw), "raw_len": len(raw)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": raw[:500]}

def main():
    rows = load_idx()
    edges = load_edges()
    result = {}
    for hub in HUBS:
        kids = children_of(hub, edges)
        prompt = build_prompt(hub, kids, rows)
        print(f"[#{hub}] deti={len(kids)}  prompt={len(prompt)} znakov  -> volam opus + gemini...", flush=True)
        r_opus = call("opus", prompt)
        print(f"  opus: ok={r_opus['ok']}", flush=True)
        r_gem = call("gemini", prompt)
        print(f"  gemini: ok={r_gem['ok']}", flush=True)
        result[str(hub)] = {"hub_text": rows[hub]["text"][:200], "hub_layer": rows[hub].get("layer"),
                            "n_children": len(kids), "children_ids": kids,
                            "opus": r_opus, "gemini": r_gem}
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nHOTOVO -> {OUT}")

    # rychly konsenzus sumar
    for hub in HUBS:
        h = result[str(hub)]
        o = h["opus"].get("parsed", {}) if h["opus"]["ok"] else {}
        g = h["gemini"].get("parsed", {}) if h["gemini"]["ok"] else {}
        print(f"\n#{hub}: opus_verdict={o.get('cluster_verdict')} apex={o.get('hub_is_true_apex')} layer={o.get('hub_should_be_layer')}")
        print(f"        gem_verdict ={g.get('cluster_verdict')} apex={g.get('hub_is_true_apex')} layer={g.get('hub_should_be_layer')}")

if __name__ == "__main__":
    main()
