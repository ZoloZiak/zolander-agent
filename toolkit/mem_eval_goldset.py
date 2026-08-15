#!/usr/bin/env python3
"""mem_eval_goldset.py — vygeneruje eval gold-set pre recall.

Opus dostane vzorku realnych zaznamov z mem_index.jsonl a pre kazdy napise
REALISTICKU SK otazku INYMI slovami (parafraza, synonyma) — tak sa testuje ci
recall chyta VYZNAM, nie len zhodu slov. Vystup: state/mem_eval_gold.json
[{"id": <ocakavany zaznam>, "query": "<otazka>"}]. Opakovatelne (uloz raz, meraj vela ráz).

Bezi pod .venv-yar (palantir_client tam funguje, overene). Bez SSL pekla homebrew py3.13.
"""
import os
import re
import sys
import json

HOME = os.path.expanduser("~")
IDX = os.path.join(HOME, "projects", "zolander", "state", "mem_index.jsonl")
OUT = os.path.join(HOME, "projects", "zolander", "state", "mem_eval_gold.json")
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "projects", "zolo2.0", "toolkit")) if os.path.isdir(os.path.join(os.path.expanduser("~"),"projects","zolo2.0","toolkit")) else sys.path.insert(0, os.path.join(os.path.expanduser("~"),"zolo2.0","toolkit"))

# kolko zaznamov do gold-setu a ako husto vzorkovat naprie korpusom
N_SAMPLE = int(os.environ.get("EVAL_N", "24"))

_SYS = (
    "Si tvorca testovacich otazok pre pamatovy system. Dostanes ZOZNAM zapamatanych "
    "faktov s ich id. Pre KAZDY napis jednu realisticku otazku po slovensky, ktoru by "
    "polozil pouzivatel, KED HLADA PRAVE TENTO fakt — ale INYMI slovami nez je v texte "
    "(pouzi synonyma, ine formulacie, prirodzenu rec; NEkopiruj klucove slova doslovne). "
    "Otazka musi jednoznacne mierit na TEN fakt, nie vseobecne. Vrat IBA JSON pole "
    "[{\"id\": <cislo>, \"query\": \"<otazka>\"}], nic ine."
)


def load_rows():
    rows = []
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("text") and r.get("id") is not None:
            rows.append(r)
    return rows


def main():
    from palantir_client import chat
    rows = load_rows()
    # rovnomerne vzorkuj naprie korpusom (nie len zaciatok) pre roznorodost tem
    step = max(1, len(rows) // N_SAMPLE)
    sample = rows[::step][:N_SAMPLE]
    listing = "\n".join(f'- id={r["id"]}: {r["text"]}' for r in sample)
    prompt = f"Fakty:\n{listing}\n\nPre kazdy napis testovaciu otazku (parafraza)."
    out = chat(prompt, model="opus", max_tokens=4000, system=_SYS)
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        print("Opus nevratil JSON pole:", out[:300], file=sys.stderr)
        return 1
    gold = json.loads(m.group(0))
    # ponechaj len zaznamy co realne su v korpuse
    valid_ids = {r["id"] for r in rows}
    gold = [g for g in gold if g.get("id") in valid_ids and g.get("query")]
    json.dump(gold, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"OK: {len(gold)} gold otazok -> {OUT}")
    for g in gold[:5]:
        print(f"  #{g['id']}: {g['query']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
