#!/usr/bin/env python3
"""judge_scale.py — detektor cenzurovanej škály LLM-judgu (2608.27309).

LLM judgovia natláčajú skóre k okrajom škály (ceiling/floor clipping). Keď MoA
hook spraví "konsenzus" zo skóre, ktoré sú všetky nalepené na 1.0, konsenzus je
falošný — nemal rozlišovaciu silu. Tento audit to chytí a označí, aby sa taký
konsenzus bral s rezervou (alebo prehodnotila prompt-škála judgu).

Bez závislostí (čistý stdlib, offline). Volá sa nad zoznamom judge skóre.
"""

_EPS = 0.03          # ako blízko okraju sa už počíta za "na okraji"
_CENSOR_FRAC = 0.6   # podiel skóre na jednom okraji, čo spustí censored verdikt
_MIN_SPREAD = 0.05   # pod týmto rozptylom je škála degenerovaná (žiadne rozlíšenie)


def audit(scores, lo=0.0, hi=1.0):
    """Audit rozloženia judge skóre. Vráť dict s verdiktom."""
    xs = [float(s) for s in (scores or []) if isinstance(s, (int, float))]
    n = len(xs)
    base = {"n": n, "censored": False, "ceiling_frac": 0.0, "floor_frac": 0.0,
            "spread": 0.0, "verdict": "OK", "reason": ""}
    if n == 0:
        base["reason"] = "žiadne skóre"
        return base

    span = (hi - lo) or 1.0
    eps = _EPS * span
    ceiling = sum(1 for x in xs if x >= hi - eps) / n
    floor = sum(1 for x in xs if x <= lo + eps) / n
    spread = (max(xs) - min(xs)) / span

    base.update(ceiling_frac=round(ceiling, 3), floor_frac=round(floor, 3),
                spread=round(spread, 3))

    if n == 1:
        base["reason"] = "1 skóre — nedá sa posúdiť rozptyl"
        return base

    if spread < _MIN_SPREAD and ceiling < _CENSOR_FRAC and floor < _CENSOR_FRAC:
        base.update(verdict="DEGENERATE", censored=True,
                    reason=f"nulový rozptyl (spread={spread:.3f}) — judge nerozlišuje")
        return base
    if ceiling >= _CENSOR_FRAC:
        base.update(verdict="CENSORED_CEILING", censored=True,
                    reason=f"{ceiling:.0%} skóre nalepených na strop — clipping hore")
        return base
    if floor >= _CENSOR_FRAC:
        base.update(verdict="CENSORED_FLOOR", censored=True,
                    reason=f"{floor:.0%} skóre nalepených na dno — clipping dole")
        return base

    base["reason"] = "škála rozložená, rozlišuje"
    return base


if __name__ == "__main__":
    import json
    import sys
    data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else [1.0, 1.0, 0.99]
    print(json.dumps(audit(data), ensure_ascii=False, indent=2))
