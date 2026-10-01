#!/usr/bin/env python3
"""crosslab_score.py — re-skoruj POLOMER nezavislym labom (nie opus/Anthropic).

Caveat z nezavisleho goldu: polomer aj gold boli z opusu -> naskok continuous>discrete
mohol byt opus self-konzistencia, nie tvrda pravda. Tento skript re-skoruje polomer
IDENTICKYM promptom ako build_geom_data.py, len INYM MODELOM (gpt = OpenAI, mimo
Anthropic rodiny). Vysledok ide do noveho pola (r_gpt) v geom_data.json -> r_opus ostava.

Ak potom gold_eval s radius=r_gpt STALE ukaze continuous>discrete proti OPUS-goldu,
polomer (OpenAI) a gold (Anthropic) su z roznych labov -> self-konzistencia vylucena.
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.expanduser("~/projects/zolo2.0/toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from palantir_client import chat

STATE = os.path.expanduser("~/projects/zolander/state")
OUT = os.path.join(STATE, "geom_data.json")

# VARIANT A (povodny): abstraktnost ako vseobecnost/nadradenost
SYSTEM_A = (
    "Si merací aparát na ABSTRAKTNOSŤ textu. Abstraktnosť = ako všeobecný/nadradený je "
    "výrok. 0.0 = úplne konkrétny fakt/udalosť/riadok kódu. 1.0 = najvšeobecnejší princíp/"
    "svetonázor. Medzi tým plynulá škála. Skóruj IBA abstraktnosť, NIE dôležitosť. Vráť čistý JSON."
)
# VARIANT B (iny ramec: pozicia v strome pojmov, coverage — NIE slovo 'abstraktnost')
SYSTEM_B = (
    "Si taxonomista. Pre každý výrok urči jeho ÚROVEŇ V STROME POJMOV ako číslo 0.0-1.0. "
    "0.0 = LIST stromu: najkonkrétnejší detail/jedna udalosť/jeden fakt, pod ktorým už nič nie je. "
    "1.0 = KOREŇ stromu: zastrešuje veľké množstvo iných výrokov ako ich kategória/princíp. "
    "Otázka NIE JE 'aké je to abstraktné', ale 'koľko iných vecí by mohlo byť POD tým v strome'. "
    "Vráť čistý JSON."
)
PROMPT_A = ('Oskóruj abstraktnosť (0.0-1.0) KAŽDÉHO výroku. Vráť JSON objekt '
            '{"<id>": <float>, ...} pre VŠETKY id nižšie, nič iné:\n\n')
PROMPT_B = ('Urči úroveň v strome pojmov (0.0=list, 1.0=koreň) KAŽDÉHO výroku. Vráť JSON objekt '
            '{"<id>": <float>, ...} pre VŠETKY id nižšie, nič iné:\n\n')
VARIANTS = {"a": (SYSTEM_A, PROMPT_A), "b": (SYSTEM_B, PROMPT_B)}

def score(items, model, variant="a"):
    system, phead = VARIANTS[variant]
    lines = "\n".join(f'{it["id"]}: {(it["text"] or "")[:220]}' for it in items)
    prompt = phead + lines
    # GPT je OpenAI vetva (max_completion_tokens rieši klient). Gemini je reasoning-model
    # (thinking zozerie budget -> pasca) -> velky budget. max_tokens vyssi pre istotu.
    mt = 9000 if model in ("gpt", "gemini", "gpt55", "flash") else 1500
    txt = chat(prompt, model=model, max_tokens=mt, system=system).strip()
    a, b = txt.find("{"), txt.rfind("}")
    if a < 0 or b < 0:
        raise ValueError(f"ziadny JSON v odpovedi (model={model}): {txt[:80]!r}")
    return {int(k): float(v) for k, v in json.loads(txt[a:b+1]).items()}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt")
    ap.add_argument("--variant", default="a", choices=["a", "b"], help="prompt variant a=abstraktnost, b=strom pojmov")
    ap.add_argument("--field", default=None, help="vystupne pole; default r_<model>[_<variant>]")
    args = ap.parse_args()
    suffix = "" if args.variant == "a" else f"_{args.variant}"
    field = args.field or f"r_{args.model}{suffix}"

    data = {int(k): v for k, v in json.load(open(OUT, encoding="utf-8")).items()}
    rows = [v for v in data.values() if (v.get("text") or "").strip()]
    need = [r for r in rows if field not in data.get(r["id"], {})]
    print(f"[crosslab] model={args.model} variant={args.variant} field={field} treba={len(need)}/{len(rows)}", file=sys.stderr)

    for i in range(0, len(need), 15):
        chunk = need[i:i+15]
        for attempt in range(3):
            try:
                sc = score([{"id": r["id"], "text": r["text"]} for r in chunk], args.model, args.variant)
                for r in chunk:
                    if r["id"] in sc:
                        data[r["id"]][field] = sc[r["id"]]
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ! batch fail: {e}", file=sys.stderr)
        json.dump({str(k): v for k, v in data.items()}, open(OUT, "w", encoding="utf-8"),
                  ensure_ascii=False)
        print(f"[crosslab] {min(i+15,len(need))}/{len(need)}", file=sys.stderr)

    done = sum(1 for v in data.values() if field in v)
    print(json.dumps({"model": args.model, "field": field, "scored": done,
                      "total": len(rows)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
