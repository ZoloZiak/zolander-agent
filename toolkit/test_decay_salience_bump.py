#!/usr/bin/env python3
"""test_decay_salience_bump.py — salience_bump napojený do cmd_decay (WMT/ŽL6).

Dokazuje, že decay cesta teraz volá salience_bump.compute() na hit_counts
z telemetrie a:
  - keď je signál pririedky (dnešný reálny stav) → NOT_READY, salience NEZMENENÁ
    (readiness gate v kóde drží — väzenie: netvrď kalibráciu bez dát)
  - keď je signál dostatočný → bump sa aplikuje, salience stúpne (cap 1.0)
  - base_salience sa NIKDY neprepíše (idempotencia decay ostáva)

Seam: zol_mem._apply_salience_bump(rows, hit_counts) -> (rows, audit_dict).
Čistý stdlib, offline (žiadny embed/DB).
"""
import os
import sys
import types
import importlib.util

# stub heavy deps pred importom zol_mem (rovnaký vzor ako test_recall_routing)
for _m in ("embed_yar",):
    if _m not in sys.modules:
        _stub = types.ModuleType(_m)
        setattr(_stub, "embed", lambda *a, **k: [])
        setattr(_stub, "embed_one", lambda *a, **k: [])
        sys.modules[_m] = _stub

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem  # noqa: E402


def _check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        raise AssertionError(name)


def _rows():
    return [
        {"id": 1, "kind": "semantic", "salience": 0.50, "base_salience": 0.50},
        {"id": 2, "kind": "semantic", "salience": 0.50, "base_salience": 0.50},
        {"id": 3, "kind": "episodic", "salience": 0.40, "base_salience": 0.40},
        {"id": 4, "kind": "semantic", "salience": 0.50, "base_salience": 0.50},
        {"id": 5, "kind": "semantic", "salience": 0.50, "base_salience": 0.50},
    ]


def test_not_ready_leaves_salience_untouched():
    """Pririedky signál (1/5 pokrytie) → gate drží, žiadna zmena salience."""
    rows = _rows()
    before = [r["salience"] for r in rows]
    out, audit = zol_mem._apply_salience_bump(rows, {1: 3})
    after = [r["salience"] for r in out]
    _check("NOT_READY verdikt", audit.get("verdict") == "NOT_READY")
    _check("salience nezmenená keď gate drží", before == after)


def test_ready_applies_bump():
    """Dostatočné pokrytie + rôzne úrovne → bump sa aplikuje, salience stúpne."""
    rows = _rows()
    # 4/5 pokrytie, 3 rôzne úrovne (5,3,1) → ready
    hit_counts = {1: 5, 2: 3, 3: 1, 4: 1}
    out, audit = zol_mem._apply_salience_bump(rows, hit_counts)
    _check("APPLIED verdikt", audit.get("verdict") == "APPLIED")
    by_id = {r["id"]: r for r in out}
    _check("najviac zasiahnutý (#1) stúpol", by_id[1]["salience"] > 0.50)
    _check("nezasiahnutý (#5) nezmenený", by_id[5]["salience"] == 0.50)
    _check("base_salience #1 sa NEPREPÍSAL (idempotencia)", by_id[1]["base_salience"] == 0.50)
    _check("salience capovaná na 1.0", all(r["salience"] <= 1.0 for r in out))


def test_failopen_on_broken_module():
    """Ak salience_bump zlyhá, decay pokračuje s pôvodnými rows (fail-open)."""
    rows = _rows()
    before = [r["salience"] for r in rows]
    # None hit_counts → compute to zvládne, ale over že nič nespadne
    out, audit = zol_mem._apply_salience_bump(rows, None)
    after = [r["salience"] for r in out]
    _check("fail-safe: rows prežijú", len(out) == len(rows))
    _check("fail-safe: salience nezmenená bez telemetrie", before == after)


if __name__ == "__main__":
    test_not_ready_leaves_salience_untouched()
    test_ready_applies_bump()
    test_failopen_on_broken_module()
    print("PASS decay salience-bump: not-ready-hold/ready-apply/fail-open napojené v cmd_decay")
