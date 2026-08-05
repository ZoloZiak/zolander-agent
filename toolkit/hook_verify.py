#!/usr/bin/env python3
"""hook_verify.py — DETERMINISTICKY pre-finish zamok pre kod-claimy (Zolander).

Zapaja sa na Hermes hook `pre_verify` (agent/verify_hooks.py + shell_hooks.py):
fired RAZ za turn ked agent editoval kod a chysta sa vyhlasit hotovo. Hermes
posle na stdin JSON:
  {"hook_event_name":"pre_verify","session_id":...,"cwd":...,
   "extra":{"coding":bool,"attempt":int,"changed_paths":[...],...}}

Ak hook vypise {"action":"continue","message":"..."} -> agent NEDOSTANE skoncit,
dostane message a pokracuje jeden turn navyse (bounded max_verify_nudges=3).
Cokolvek ine -> turn skonci normalne.

PROBLEM ktory riesi: anti-hallucination skill je soft — model moze vyhlasit
"hotovo" aj ked ním zmeneny subor je syntakticky rozbity. Toto je tvrdy zamok:
MECHANICKA kontrola (kompiluju sa zmenene .py/.json?) bezi ako KOD, nezavisle
od toho co model tvrdi. Neoverujem vety v prirodzenom jazyku (to hook nevie),
overujem mechanicky fakt: parsuju sa zmenene subory.

FAIL-OPEN: po attempt>=2 uz nenudim (nech neblokujem donekonecna ak sa to
nevie opravit — clovek to dorobi). Hook nikdy nespadne (except -> ticho).
"""
import sys
import os
import json
import py_compile

MAX_NUDGE_ATTEMPT = 2  # po tolkych pokusoch nechaj skoncit (fail-open)


def _check_py(path: str) -> str:
    """Vrati chybovu hlasku ak .py nekompiluje, inak ''."""
    try:
        py_compile.compile(path, doraise=True)
        return ""
    except py_compile.PyCompileError as exc:
        return str(exc).strip().splitlines()[-1][:300]
    except Exception:
        return ""  # subor zmizol / necitatelny -> netlac


def _check_json(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return ""
    except json.JSONDecodeError as exc:
        return f"JSON: {exc}"[:300]
    except Exception:
        return ""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return

    extra = payload.get("extra") or {}
    if not extra.get("coding"):
        return  # nie kod -> nic
    if int(extra.get("attempt") or 0) >= MAX_NUDGE_ATTEMPT:
        return  # fail-open

    changed = extra.get("changed_paths") or []
    if not isinstance(changed, list):
        return

    broken = []
    for p in changed:
        if not isinstance(p, str) or not os.path.isfile(p):
            continue
        if p.endswith(".py"):
            err = _check_py(p)
        elif p.endswith(".json"):
            err = _check_json(p)
        else:
            continue
        if err:
            broken.append(f"  {p}: {err}")

    if not broken:
        return  # vsetko parsuje -> nechaj skoncit

    msg = ("[Zolander pre-verify zamok] Zmenene subory NEPARSUJU — oprav "
           "syntax PRED tym nez vyhlasis hotovo:\n" + "\n".join(broken))
    print(json.dumps({"action": "continue", "message": msg}, ensure_ascii=False))


if __name__ == "__main__":
    main()
