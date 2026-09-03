#!/usr/bin/env python3
"""edge_phase3_apex_tiebreak.py — 3. model (gpt) rozhodne: treba spolocny apex uzol?

Kontext: opus=ano(apex L2), gemini=nie(len siblings). gpt je tiebreak. NENAVODNE:
gpt nedostane opusov navrh ani slovo 'novy uzol/treba' -> ziadna kotva. Dostane hole
identity fakty a rozhodne sam ci existuje zmysluplna NADRADENA kategoria hodna
samostatneho uzla, alebo su to len tematicki siblings (staci asociacia).

Vysledok: 2/3 vitazi. Iba CITA + 1 LLM volanie. Zapise do edge_phase3_apex_tiebreak.json."""
import os, sys, json, time

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "edge_phase3_apex_tiebreak.json")
sys.path.insert(0, os.path.join(HOME, "projects", "__PROJECT__", "toolkit"))
from palantir_client import chat

KIDS = [418, 425, 430, 431, 432, 440, 443, 444, 474, 612, 629, 600, 37]

SYS = ("Si expert na organizaciu znalostnych grafov. Rozhodujes triezvo a konzervativne: "
       "novy abstraktny uzol v grafe ma zmysel LEN ak existuje skutocna NADRADENA kategoria, "
       "ktorej su vsetky (alebo vacsina) vyrokov instanciami/podtypmi (is-a), a ktora "
       "prinasa retrieval hodnotu. Ak su to len tematicky pribuzne tvrdenia na rovnakej "
       "urovni, novy uzol NETREBA (staci asociativne prepojenie). Odpovedas VYLUCNE JSON.")

def load_idx():
    rows = {}
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l); rows[r["id"]] = r
    return rows

def main():
    rows = load_idx()
    lines = ["Mnozina tvrdeni z pamate AI agenta:", ""]
    for k in KIDS:
        t = (rows[k].get("text") or "").replace("\n", " ").strip()
        lines.append(f"  #{k}: {t}")
    lines += [
        "",
        "OTAZKA: Zdielaju tieto tvrdenia jednu skutocnu NADRADENU kategoriu (is-a), "
        "ktoru by sa oplatilo zhmotnit ako samostatny abstraktny uzol v grafe? Alebo su "
        "to len tematicky pribuzne SIBLINGS na rovnakej urovni, kde staci asociativne "
        "prepojenie bez noveho uzla?",
        "",
        'FORMAT: {"need_apex": true|false, "reason": "...", '
        '"apex_text": "..." alebo null, "apex_layer": "L1|L2|L3" alebo null, '
        '"members": [zoznam id ktore by pod apex patrili ako is_a]}',
    ]
    prompt = "\n".join(lines)
    print(f"{len(KIDS)} identity faktov, prompt {len(prompt)} zn.")
    raw = chat(prompt, model="gpt", max_tokens=3000, system=SYS)
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"): raw = raw[4:]
    s, e = raw.find("{"), raw.rfind("}")
    parsed = json.loads(raw[s:e+1])
    print("\ngpt need_apex:", parsed.get("need_apex"))
    print("reason:", parsed.get("reason"))
    print("apex_text:", parsed.get("apex_text"))
    print("apex_layer:", parsed.get("apex_layer"))
    print("members:", parsed.get("members"))
    vote = {"opus": True, "gemini": False, "gpt": bool(parsed.get("need_apex"))}
    yes = sum(vote.values())
    print(f"\nHLASOVANIE need_apex: {vote} -> {yes}/3 ZA")
    print("VERDIKT:", "VYTVOR APEX" if yes >= 2 else "LEN RELATED (bez uzla)")
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "gpt": parsed,
               "vote": vote, "yes": yes,
               "verdict": "apex" if yes >= 2 else "related"},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapisane: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
