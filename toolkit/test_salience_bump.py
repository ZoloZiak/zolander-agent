#!/usr/bin/env python3
"""test_salience_bump.py — Weighted Memory Tree salience bump (2608.20631) + ŽL6.

Mechanizmus: často zasiahnuté pamäte (recall_hits telemetria) dostanú mierny
salience bump, aby stúpali v rankingu. ALE — bump kalibrovaný na pririedkom
signáli preučí na hŕstku opakovaných dotazov. Preto má funkcia VSTAVANÝ
data-readiness gate (väzenie v kóde): odmietne aplikovať, kým signál nestačí.

Kontrakt salience_bump.compute(hit_counts, n_total, ...) -> dict:
  { ready: bool, reason, coverage, applied: {id: bump}, verdict }
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience_bump import compute  # noqa: E402


def _check(name, cond):
    if not cond:
        print(f"FAIL salience_bump: {name}")
        sys.exit(1)


def main():
    # 1) Pririedky signál (dnešný reálny stav: 19/405, uniformné topy) → NOT ready
    sparse = {599: 17, 436: 17, 420: 17, 500: 17, 11: 16}
    sparse.update({1000 + i: 3 for i in range(14)})  # 19 ID spolu
    r = compute(sparse, n_total=405)
    _check("pririedky signál → not ready", r["ready"] is False)
    _check("not ready → žiadny bump aplikovaný", len(r["applied"]) == 0)
    _check("coverage ~4.7%", r["coverage"] < 0.1)

    # 2) Dostatočné pokrytie + rozmanitosť → ready, bump aplikovaný
    rich = {i: (2 + (i % 5)) for i in range(150)}  # 150/405 pokrytie, rozptyl
    r = compute(rich, n_total=405)
    _check("bohatý signál → ready", r["ready"] is True)
    _check("ready → bumpy aplikované", len(r["applied"]) > 0)
    _check("bump je ohraničený zhora", max(r["applied"].values()) <= r["max_bump"])

    # 3) Uniformný signál (žiadny rozptyl) → not ready aj pri pokrytí
    uniform = {i: 10 for i in range(200)}
    r = compute(uniform, n_total=405)
    _check("uniformný signál → not ready", r["ready"] is False)

    # 4) Bump monotónny: viac hitov = väčší (alebo rovný) bump
    rich2 = {1: 2, 2: 8, 3: 20}
    rich2.update({100 + i: 3 for i in range(150)})
    r = compute(rich2, n_total=405)
    if r["ready"]:
        b = r["applied"]
        if 1 in b and 3 in b:
            _check("viac hitov → väčší bump", b[3] >= b[1])

    # 5) Robustnosť
    _check("prázdny signál → not ready", compute({}, n_total=405)["ready"] is False)
    _check("n_total=0 nespadne", "ready" in compute({1: 5}, n_total=0))

    # 6) Kontrakt
    r = compute({1: 5}, n_total=10)
    for k in ("ready", "reason", "coverage", "applied", "verdict", "max_bump"):
        _check(f"kľúč {k}", k in r)

    print("PASS salience_bump: readiness-gate (pririedky/uniform/bohatý) + ohraničený bump")


if __name__ == "__main__":
    main()
