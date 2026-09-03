#!/usr/bin/env python3
"""test_judge_scale.py — LLM-judge censored-scale detektor (2608.27309).

Paper: LLM judgovia trpia clipping / ceiling-floor efektom — natláčajú skóre
k okrajom škály (samé 1.0 alebo samé 0.0), čím sa stráca rozlišovacia sila a
konsenzus (MoA hook) je falošne vysoký. Detektor to chytí PRED tým, než sa
z takých skóre spraví "konsenzus".

Kontrakt judge_scale.audit(scores, lo=0.0, hi=1.0) -> dict:
  { n, censored, ceiling_frac, floor_frac, spread, verdict, reason }
  verdict ∈ {"OK","CENSORED_CEILING","CENSORED_FLOOR","DEGENERATE"}.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge_scale import audit  # noqa: E402


def _check(name, cond):
    if not cond:
        print(f"FAIL judge_scale: {name}")
        sys.exit(1)


def main():
    # 1) Zdravé rozložené skóre = OK
    r = audit([0.2, 0.5, 0.7, 0.9, 0.35, 0.6])
    _check("rozložené skóre → OK", r["verdict"] == "OK")
    _check("spread nenulový", r["spread"] > 0.1)

    # 2) Všetko na strope = CENSORED_CEILING
    r = audit([1.0, 1.0, 0.98, 1.0, 0.99])
    _check("samé stropy → CENSORED_CEILING", r["verdict"] == "CENSORED_CEILING")
    _check("ceiling_frac vysoká", r["ceiling_frac"] >= 0.6)

    # 3) Všetko na dne = CENSORED_FLOOR
    r = audit([0.0, 0.0, 0.02, 0.0])
    _check("samé dná → CENSORED_FLOOR", r["verdict"] == "CENSORED_FLOOR")

    # 4) Konštantné skóre (nulový spread) = DEGENERATE
    r = audit([0.5, 0.5, 0.5, 0.5])
    _check("konštanta → DEGENERATE", r["verdict"] == "DEGENERATE")

    # 5) Robustnosť: prázdne / 1 prvok
    _check("prázdny → OK/n0", audit([])["n"] == 0)
    _check("1 prvok nespadne", "verdict" in audit([0.7]))

    # 6) Iná škála (1..5 Likert) funguje cez lo/hi
    r = audit([5, 5, 5, 4.9], lo=1, hi=5)
    _check("Likert strop → CENSORED_CEILING", r["verdict"] == "CENSORED_CEILING")

    # 7) Kontrakt kľúčov
    for k in ("n", "censored", "ceiling_frac", "floor_frac", "spread",
              "verdict", "reason"):
        _check(f"kľúč {k}", k in audit([0.3, 0.6]))

    print("PASS judge_scale: OK/ceiling/floor/degenerate/Likert/robustnosť")


if __name__ == "__main__":
    main()
