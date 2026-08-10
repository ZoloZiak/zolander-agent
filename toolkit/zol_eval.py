#!/usr/bin/env python3
"""zol_eval.py — cross-model self-eval (anti-self-preference) + konvergenčná slučka.

PRINCÍP (vedúcko): model NIKDY nehodnotí SÁM seba. Hodnotitelia = vždy tie DVA modely
z trojice {opus, gpt, gemini}, ktoré NEgenerovali. Opus píše → gemini+gpt hodnotia;
gemini píše → opus+gpt; atď. Rovnaký ensemble vzor ako multi_model_chapter.py (§11).

Cez Palantir trojicu (palantir_client.chat). Skóre 0-1 na 4 kritériá + celkom + dôvod.
AGREGÁCIA = MIN z dvoch hodnotiteľov (prísnejší gate = menej falošných "hotovo").
Konfigurovateľné cez ZOL_EVAL_AGG=min|avg.

Doladené po spike (2026-08-10): robustný JSON parse (salvage), judges=ostatné dva
(nie fixný pár), min agregácia, fail-open na zlyhaný judge (nezhodí slučku).

API (knižnica):
  from zol_eval import evaluate, refine_loop
  score = evaluate(zadanie, odpoved, generator="opus")   # -> {celkom, per_judge, ...}
  final = refine_loop(zadanie, generator="opus", threshold=0.75, max_rounds=2)

CLI (test):
  echo '{"zadanie":"...","odpoved":"...","generator":"opus"}' | zol_eval.py score
  echo '{"zadanie":"...","generator":"opus","threshold":0.75}' | zol_eval.py loop
"""
import os
import sys
import re
import json

sys.path.insert(0, os.path.expanduser("~/zolo2.0/toolkit"))

TRIO = ("opus", "gpt", "gemini")
AGG = os.environ.get("ZOL_EVAL_AGG", "min")  # min (prísne) | avg
GEN_MAX_TOKENS = int(os.environ.get("ZOL_EVAL_GEN_TOKENS", "900"))  # spike: 400 useklo
EVAL_MAX_TOKENS = int(os.environ.get("ZOL_EVAL_JUDGE_TOKENS", "400"))

EVAL_SYSTEM = """Si prísny hodnotiteľ kvality textu. Dostaneš ZADANIE a ODPOVEĎ.
Ohodnoť odpoveď podľa 4 kritérií, každé 0.0-1.0:
- vernost: odpovedá na zadanie, nič si nevymýšľa
- vecnost: konkrétna, bez vaty a omáčky
- ton: sedí (priamy mentor, žiadne lichôtky/pochlebovanie)
- uzitocnost: reálne pomôže, nie prázdne slová
Vráť LEN validný JSON, nič iné pred ani za:
{"vernost":0.0,"vecnost":0.0,"ton":0.0,"uzitocnost":0.0,"celkom":0.0,"dovod":"1 veta"}"""

GEN_SYSTEM = ("Si Zolander, priamy mentor pre veducka. Odpovedaj vecne, s dovodom, "
              "ziadne lichotky. Odpoved dokonci, nenechaj ju useknutu.")


def _judges_for(generator):
    """Hodnotitelia = dva modely z trojice, ktoré NEgenerovali (žiadny self-review)."""
    return [m for m in TRIO if m != generator]


def _parse_score(raw):
    """Robustný parse JSON skóre. Salvage: nájdi prvý {...} blok, doplň chýbajúce."""
    r = (raw or "").strip()
    if r.startswith("```"):
        r = r.split("```", 2)[1] if "```" in r else r
        r = r[4:] if r.startswith("json") else r
        r = r.strip("` \n")
    # nájdi JSON objekt kdekoľvek v texte
    m = re.search(r"\{[^{}]*\"celkom\"[^{}]*\}", r, re.DOTALL)
    blob = m.group(0) if m else (r[r.find("{"):r.rfind("}") + 1] if "{" in r else "")
    try:
        o = json.loads(blob)
    except Exception:
        # posledná záchrana: vytiahni celkom= číslo regexom
        mm = re.search(r"celkom\"?\s*[:=]\s*([01](?:\.\d+)?)", r)
        if mm:
            return {"celkom": float(mm.group(1)), "dovod": "salvage-partial", "_salvaged": True}
        return None
    # normalizuj celkom (ak chýba, priemer zložiek)
    if "celkom" not in o:
        parts = [o.get(k) for k in ("vernost", "vecnost", "ton", "uzitocnost") if isinstance(o.get(k), (int, float))]
        o["celkom"] = round(sum(parts) / len(parts), 3) if parts else 0.0
    return o


def evaluate(zadanie, odpoved, generator):
    """Cross-model skóre. Judges = ostatné dva modely. Fail-open na zlyhaný judge."""
    from palantir_client import chat
    judges = _judges_for(generator)
    per_judge = {}
    scores = []
    prompt = f"ZADANIE:\n{zadanie}\n\nODPOVEĎ:\n{odpoved}"
    for j in judges:
        try:
            # gemini je reasoning model — spotrebuje tokeny na "thinking" PRED JSON,
            # takže s malým limitom sa JSON useknle (spike/live bug). Daj mu rezervu.
            jt = EVAL_MAX_TOKENS + 16000 if j in ("gemini", "flash") else EVAL_MAX_TOKENS
            raw = chat(prompt, model=j, system=EVAL_SYSTEM, max_tokens=jt)
            s = _parse_score(raw)
            if s and isinstance(s.get("celkom"), (int, float)):
                per_judge[j] = s
                scores.append(float(s["celkom"]))
            else:
                per_judge[j] = {"error": "parse_failed", "raw": (raw or "")[:120]}
        except Exception as e:
            per_judge[j] = {"error": repr(e)}
    if not scores:
        # oba judge zlyhali -> fail-open: nevieme skórovať, vráť None celkom
        return {"celkom": None, "generator": generator, "judges": judges,
                "per_judge": per_judge, "note": "vsetci judgeri zlyhali"}
    agg = min(scores) if AGG == "min" else round(sum(scores) / len(scores), 3)
    return {"celkom": agg, "agg": AGG, "n_judges": len(scores),
            "generator": generator, "judges": judges, "per_judge": per_judge}


def refine_loop(zadanie, generator="opus", threshold=0.75, max_rounds=2):
    """Generuj → skóruj → ak < prah, daj feedback a prepíš. Max N kôl. Fail-open."""
    from palantir_client import chat
    history = []
    odpoved = chat(zadanie, model=generator, system=GEN_SYSTEM, max_tokens=GEN_MAX_TOKENS).strip()
    for rnd in range(1, max_rounds + 1):
        ev = evaluate(zadanie, odpoved, generator)
        cel = ev.get("celkom")
        history.append({"round": rnd, "celkom": cel, "judges": ev.get("per_judge")})
        if cel is None or cel >= threshold:
            return {"odpoved": odpoved, "celkom": cel, "rounds": rnd,
                    "converged": cel is not None and cel >= threshold, "history": history}
        # feedback z dôvodov judgeov -> prepíš
        dovody = " | ".join(str(s.get("dovod", "")) for s in ev["per_judge"].values() if isinstance(s, dict))
        revise = (f"{zadanie}\n\n[Tvoja predch. odpoveď dostala {cel:.2f}/1.0. Výhrady "
                  f"hodnotiteľov: {dovody}. Prepracuj odpoveď aby ich vyriešila.]")
        odpoved = chat(revise, model=generator, system=GEN_SYSTEM, max_tokens=GEN_MAX_TOKENS).strip()
    # posledné kolo po vyčerpaní: skóruj finálnu verziu
    ev = evaluate(zadanie, odpoved, generator)
    history.append({"round": max_rounds + 1, "celkom": ev.get("celkom"), "final": True})
    return {"odpoved": odpoved, "celkom": ev.get("celkom"), "rounds": max_rounds,
            "converged": False, "history": history, "note": "vycerpane kola (FORCE_ACCEPTED)"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    obj = json.loads(sys.stdin.read() or "{}")
    if cmd == "score":
        print(json.dumps(evaluate(obj["zadanie"], obj["odpoved"],
              obj.get("generator", "opus")), ensure_ascii=False, indent=2))
    elif cmd == "loop":
        print(json.dumps(refine_loop(obj["zadanie"], obj.get("generator", "opus"),
              float(obj.get("threshold", 0.75)), int(obj.get("max_rounds", 2))),
              ensure_ascii=False, indent=2))
    else:
        print(f"neznamy prikaz: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
