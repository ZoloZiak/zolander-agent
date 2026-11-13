#!/usr/bin/env python3
"""Test mechanickej double-take brany should_double_take (LLM-free, deterministicke).
Overuje ze trivialne vstupy sa preskocia a vazne rozhodovacie otazky spustia double-take.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens import should_double_take

# (text, ocakavane_serious)
CASES = [
    ("ahoj", False),
    ("ok dik", False),
    ("čau, ako sa mas", False),
    ("hej", False),
    ("Mam odist z firmy alebo zostat este rok kvoli istote?", True),
    ("Oplati sa mi investovat cas do tohto projektu alebo je to slepa ulicka?", True),
    ("Preco stale odkladam rozrobene veci a ako to zmenit dlhodobo?", True),
    ("Mal by som zmenit pracu ked ma to prestalo bavit?", True),
    ("Aka je strategia na dlhodobe smerovanie zolo projektu, za a proti?", True),
    ("kolko je hodin", False),
    ("dakujem pekne", False),
    ("Toto rozhodnutie ma velke dosledky pre buducnost, mam risknut vztah kvoli kariere?", True),
]

allok = True
for text, expect in CASES:
    serious, dovod, score = should_double_take(text)
    ok = serious == expect
    allok &= ok
    mark = "PASS" if ok else "FAIL"
    print(f"{mark} | serious={serious} (skore={score}) | {text[:55]}")
    if not ok:
        print(f"       ocakaval som {expect}, dovod: {dovod}")

print("\nCELKOVO:", "PASS" if allok else "FAIL")
sys.exit(0 if allok else 1)
