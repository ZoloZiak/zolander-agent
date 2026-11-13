#!/usr/bin/env python3
"""test_claim_ledger.py — väzenie musí zavrieť presne na mojich 3 zlyhaniach z 2026-08-31.

Voyager: skill/nástroj sa neuloží ako hotový, kým nefunguje na inom prípade než tom,
čo ho vyrobil. Väzenie postavila lož "5 CONFLICTov / IBIA neexistuje / prázdne vektory".
Tu ho testujem NA TÝCH TROCH zlyhaniach — ak by existovalo vtedy, muselo by ich chytiť.
"""
import os
import sys

ROOT = os.path.expanduser("~/projects/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
from claim_ledger import Ledger, checks, VERIFIED, REFUTED, UNVERIFIABLE  # noqa: E402


def _one(check, expect):
    status, ev = check()
    assert status == expect, f"čakané {expect}, dostal {status}: {ev}"
    return ev


def test_verified_passes():
    # Pravdivé, overiteľné tvrdenie MUSÍ prejsť.
    _one(checks.jsonl_field_all("state/mem_index.jsonl", "source"), VERIFIED)
    _one(checks.temporal_superseded(120, 109), VERIFIED)
    _one(checks.temporal_superseded(206, 611), VERIFIED)


def test_refuted_catches_lie():
    # Zlyhanie #1 replika: keby som tvrdil "IBIA source neexistuje" ako grep 0/410,
    # kontrola to VYVRÁTI (reálne je 410).
    _one(checks.grep_count("state/mem_index.jsonl", r'"source"', 0), REFUTED)
    # Zlyhanie MELD replika: "#120 superseded do #611" (bol do #109) -> REFUTED.
    _one(checks.temporal_superseded(120, 611), REFUTED)


def test_unverifiable_blocks_like_refuted():
    # Zlyhanie #3 replika: tvrdiť o súbore/ceste čo neexistuje NESMIE vyzerať ako 'OK'.
    _one(checks.jsonl_field_all("state/neexistuje_xyz.jsonl", "norm"), UNVERIFIABLE)


def test_gate_closes_on_any_nonverified():
    # Väzenie ako celok: jediné REFUTED/UNVERIFIABLE zavrie zámok.
    L = Ledger()
    L.claim("pravda", checks.temporal_superseded(120, 109))
    L.claim("lož", checks.temporal_superseded(120, 999))
    ok, _ = L.gate()
    assert not ok, "zámok mal ostať ZAVRETÝ pri jednom REFUTED"

    L2 = Ledger()
    L2.claim("pravda1", checks.temporal_superseded(120, 109))
    L2.claim("pravda2", checks.jsonl_field_all("state/mem_index.jsonl", "source"))
    ok2, _ = L2.gate()
    assert ok2, "zámok mal byť OTVORENÝ pri všetkých VERIFIED"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[PASS] {name}")
    print("OK — väzenie chytá presne moje 3 zlyhania + gate correctness.")
