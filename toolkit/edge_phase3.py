#!/usr/bin/env python3
"""edge_phase3.py — CROSS-LAB + gpt-tiebreak pre zvysne INVERTED/SAME_LAYER (faza 3, D+B).

Dva klastre cez LLM:
  EPISTEMIC: hub-kandidati [685,558] + ich deti (princ
ipy o realite/overitelnosti).
  IDENTITY : hub-kandidati [611,494] + identity/preference fakty o __USER__/Zolanderovi.
Pre kazde dieta modely vratia relation: is_a | sibling | reverse.
Pri IDENTITY navyse navrhnu apex_text + apex_layer (plan B: novy spolocny uzol).
Zhoda opus∩gemini = verdikt. Spor -> gpt TIEBREAK (3-lab, tvoje pravidlo cross-lab).

Male zvysky (near-dup #686/#498, #672<-#572/#592, #569<-#512) NEriesi LLM -> spracuje
faza-3 apply zvlast ako 'related' (near-duplicate/cross-ref, netreba model).

Iba CITA + vola LLM. Zapise state/edge_phase3_verdict.json. NIC v grafe nemeni.
Bezi pod .venv-yar (palantir_client)."""
import os, sys, json, time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "edge_phase3_verdict.json")
sys.path.insert(0, os.path.join(HOME, "projects", "__PROJECT__", "toolkit"))
from palantir_client import chat

# klaster -> (hub kandidati, deti). Deti su UNIA cez huby (dedup).
CLUSTERS = {
    "epistemic": {
        "hubs": [685, 558],
        "kids": [347, 449, 478, 487, 490, 492, 509, 512, 515, 552, 559, 567,
                 570, 640, 667, 670, 677],
        "ask_apex": False,
    },
    "identity": {
        "hubs": [611, 494],
        "kids": [418, 425, 430, 431, 432, 440, 443, 444, 474, 612, 629, 600, 37],
        "ask_apex": True,
    },
}

SYS = ("Si expert na klasifikaciu is-a (hyponym/hypernym) hierarchii v pamatovom grafe "
       "AI agenta. Rozhoduj triezvo. is-a hrana dieta->rodic je platna LEN ak rodic je "
       "striktne vseobecnejsia KATEGORIA a dieta jej instancia/podtyp. Ak su tvrdenia na "
       "rovnakej urovni vseobecnosti (susedne principy/fakty o tej istej teme) su to "
       "SIBLINGS, nie is-a. Odpovedas VYLUCNE platnym JSON, ziadny text navyse.")

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def txt(rows, mid):
    r = rows.get(mid)
    return (r.get("text") or "").replace("\n", " ").strip() if r else "??"

def build_prompt(rows, hubs, kids, ask_apex):
    lines = ["KANDIDATI NA APEX (rodic):"]
    for h in hubs:
        lines.append(f"  #{h} [{rows[h].get('layer')}]: {txt(rows,h)}")
    lines.append("\nDETI (kandidati na potomkov):")
    for k in kids:
        lines.append(f"  #{k} [{rows[k].get('layer')}]: {txt(rows,k)}")
    q = [
        "\nULOHA:",
        "1) Je toto pravy is-a strom s JEDNYM apexom z kandidatov, alebo mnozina SIBLINGOV "
        "(tvrdenia na rovnakej urovni)? Pole \"structure\": \"tree\" | \"siblings\".",
        "2) Pre KAZDE dieta vrat relation voci najlepsiemu apex-kandidatovi: "
        "\"is_a\" (dieta je instancia/podtyp apexu) | \"sibling\" (rovnaka uroven) | "
        "\"reverse\" (dieta je v skutocnosti VSEOBECNEJSIE nez apex).",
    ]
    if ask_apex:
        q.append("3) Ak structure=siblings a tieto tvrdenia zdielaju spolocnu NADRADENU "
                 "kategoriu, navrhni novy apex: \"apex_text\" (kratka slovenska veta "
                 "definujuca kategoriu) + \"apex_layer\" (L1|L2|L3, musi byt vseobecnejsia "
                 "nez deti) + \"apex_members\" (zoznam id detí ktore pod novy apex patria "
                 "ako is-a). Ak zmysluplny spolocny apex NEEXISTUJE, apex_text=null.")
    q.append('\nFORMAT (striktne): {"structure":"...","children":[{"id":37,"relation":"..."},'
             '...]' + (',"apex_text":"...","apex_layer":"...","apex_members":[...]' if ask_apex else '')
             + '}')
    return "\n".join(lines + q)

def parse(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    s, e = raw.find("{"), raw.rfind("}")
    return json.loads(raw[s:e+1])

def call(model, prompt, budget=6000):
    try:
        raw = chat(prompt, model=model, max_tokens=budget, system=SYS)
        return {"ok": True, "parsed": parse(raw), "raw_len": len(raw or "")}
    except Exception as ex:
        return {"ok": False, "err": f"{type(ex).__name__}: {ex}", "raw_len": 0}

def rel_map(res):
    if not res.get("ok"):
        return {}
    return {c["id"]: c.get("relation") for c in res["parsed"].get("children", [])}

def main():
    rows = load_idx()
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "clusters": {}}
    for cname, cfg in CLUSTERS.items():
        hubs, kids, ask_apex = cfg["hubs"], cfg["kids"], cfg["ask_apex"]
        prompt = build_prompt(rows, hubs, kids, ask_apex)
        print(f"\n### CLUSTER {cname}: {len(kids)} deti, hubs={hubs} (prompt {len(prompt)} zn.)")
        opus = call("opus", prompt)
        time.sleep(1.5)
        gem = call("gemini", prompt, budget=8000)
        om, gm = rel_map(opus), rel_map(gem)
        print(f"  opus ok={opus['ok']} gemini ok={gem['ok']}")
        # per-dieta konsenzus + tiebreak
        decisions, tiebreaks = {}, []
        for k in kids:
            o, g = om.get(k), gm.get(k)
            if o and g and o == g:
                decisions[k] = {"relation": o, "by": "opus+gemini"}
            else:
                tiebreaks.append((k, o, g))
        # gpt tiebreak na spory (jeden dotaz na cely klaster)
        gpt_res = None
        if tiebreaks:
            tb_ids = [k for k, _, _ in tiebreaks]
            tp = build_prompt(rows, hubs, tb_ids, ask_apex=False)
            tp += ("\n\nPOZOR: opus a gemini sa NEZHODLI na tychto detoch. Rozhodni ty ako "
                   "tretí nezavisly rozhodca, striktne.")
            print(f"  TIEBREAK gpt na {len(tb_ids)} spornych: {tb_ids}")
            gpt_res = call("gpt", tp)
            gptm = rel_map(gpt_res)
            for k, o, g in tiebreaks:
                gp = gptm.get(k)
                # vitaz = ten s kym sa gpt zhodne; ak gpt=o -> o, ak gpt=g -> g, inak gpt
                if gp == o:
                    decisions[k] = {"relation": o, "by": "opus+gpt", "gemini": g}
                elif gp == g:
                    decisions[k] = {"relation": g, "by": "gemini+gpt", "opus": o}
                else:
                    decisions[k] = {"relation": gp or "sibling", "by": "gpt-only",
                                    "opus": o, "gemini": g}
        out["clusters"][cname] = {
            "hubs": hubs,
            "structure": {"opus": opus.get("parsed", {}).get("structure") if opus["ok"] else None,
                          "gemini": gem.get("parsed", {}).get("structure") if gem["ok"] else None},
            "opus": opus, "gemini": gem, "gpt_tiebreak": gpt_res,
            "decisions": {str(k): v for k, v in decisions.items()},
        }
        # sumar
        from collections import Counter
        c = Counter(v["relation"] for v in decisions.values())
        print(f"  DECISIONS: {dict(c)}")
        if ask_apex:
            for lab, res in (("opus", opus), ("gemini", gem)):
                if res["ok"]:
                    p = res["parsed"]
                    print(f"  APEX({lab}): {p.get('apex_text')!r} [{p.get('apex_layer')}] "
                          f"members={p.get('apex_members')}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nZapisane: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
