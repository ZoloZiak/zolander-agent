#!/usr/bin/env python3
"""salience_bump.py — Weighted Memory Tree salience bump (2608.20631) + ŽL6 gate.

Často zasiahnuté pamäte (recall_hits telemetria) dostanú mierny salience bump,
aby stúpali v rankingu. KĽÚČOVÉ: má VSTAVANÝ data-readiness gate — odmietne
aplikovať bump, kým je telemetrický signál pririedky alebo degenerovaný.
To je väzenie (claim_ledger disciplína) zapečené priamo do kódu: netvrď, že
"salience je kalibrovaná", keď dáta na kalibráciu nestačia.

Prečo gate: pri 19/405 pokrytí a uniformných top počtoch (dnešný reálny stav)
by bump preučil na hŕstku opakovaných daemon-dotazov, nie na skutočnú užitočnosť.

Čistý stdlib, offline.
"""
import math

# readiness prahy — pod nimi je bump zakázaný
_MIN_COVERAGE = 0.20      # aspoň 20 % pamäte musí mať nejaký hit
_MIN_DISTINCT_LEVELS = 3  # aspoň 3 rôzne hit-počty (inak je signál uniformný)
_MAX_BUMP = 0.15          # strop bumpu (salience je typicky 0..1)


def compute(hit_counts, n_total, max_bump=_MAX_BUMP):
    """Spočítaj salience bumpy s vstavaným readiness gate.

    hit_counts: {mem_id: pocet_hitov}. n_total: veľkosť pamäte.
    Vráť dict; applied je NEPRÁZDNY len keď ready=True.
    """
    hc = {k: v for k, v in (hit_counts or {}).items()
          if isinstance(v, (int, float)) and v > 0}
    n_total = max(0, int(n_total or 0))
    coverage = (len(hc) / n_total) if n_total else 0.0
    distinct_levels = len(set(hc.values()))

    base = {"ready": False, "reason": "", "coverage": round(coverage, 4),
            "applied": {}, "verdict": "NOT_READY", "max_bump": max_bump,
            "distinct_levels": distinct_levels}

    if not hc:
        base["reason"] = "žiadna telemetria — nič na kalibráciu"
        return base
    if coverage < _MIN_COVERAGE:
        base["reason"] = (f"pokrytie {coverage:.1%} < {_MIN_COVERAGE:.0%} — "
                          f"len {len(hc)}/{n_total} ID má hit, bump by preučil na hŕstku")
        return base
    if distinct_levels < _MIN_DISTINCT_LEVELS:
        base["reason"] = (f"len {distinct_levels} rôzne hit-úrovne — uniformný signál, "
                          f"bump by nerozlišoval (žiadna informácia)")
        return base

    # READY — aplikuj log-škálovaný, ohraničený bump
    mx = max(hc.values())
    applied = {}
    for mid, cnt in hc.items():
        # log škála: diminishing returns, strop max_bump pri najviac zasiahnutom
        frac = math.log1p(cnt) / math.log1p(mx)
        applied[mid] = round(max_bump * frac, 4)
    base.update(ready=True, applied=applied, verdict="APPLIED",
                reason=f"pokrytie {coverage:.1%}, {distinct_levels} úrovní — kalibrovateľné")
    return base


if __name__ == "__main__":
    import json
    import sys
    payload = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    hc = {int(k): v for k, v in payload.get("hit_counts", {}).items()}
    print(json.dumps(compute(hc, payload.get("n_total", 0)),
                     ensure_ascii=False, indent=2))
