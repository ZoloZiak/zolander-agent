#!/usr/bin/env python3
"""Izolovany test _parse_groups (bez LLM). Overuje validaciu zoskupenia:
prijme len ked kazdy index 0..n-1 je pokryty prave raz."""
import sys, os
sys.path.insert(0, "/Users/__USER__/zolander/toolkit")
from cluster_llm import _parse_groups

def check(desc, raw, n, expect):
    got = _parse_groups(raw, n)
    ok = got == expect
    print(("PASS" if ok else "FAIL"), "|", desc, "->", got)
    return ok

allok = True
# platne zoskupenie
allok &= check("valid 2 skupiny", '{"groups": [[0,2],[1]]}', 3, [[0,2],[1]])
# vsetko do jednej
allok &= check("valid 1 skupina", '{"groups": [[0,1,2]]}', 3, [[0,1,2]])
# same singletony
allok &= check("valid singletony", '{"groups": [[0],[1],[2]]}', 3, [[0],[1],[2]])
# LLM prida omacku okolo JSON
allok &= check("JSON v texte", 'Tu je vysledok: {"groups": [[0],[1]]} hotovo', 2, [[0],[1]])
# CHYBA: duplicita indexu -> None
allok &= check("duplicita -> None", '{"groups": [[0,1],[1]]}', 2, None)
# CHYBA: chybajuci index -> None
allok &= check("chyba index -> None", '{"groups": [[0]]}', 2, None)
# CHYBA: index mimo rozsah -> None
allok &= check("mimo rozsah -> None", '{"groups": [[0,5]]}', 2, None)
# CHYBA: nevalidny JSON -> None
allok &= check("zly JSON -> None", 'ziadny json tu nie je', 3, None)
# CHYBA: prazdne groups -> None
allok &= check("prazdne -> None", '{"groups": []}', 3, None)

print("\nCELKOVO:", "PASS" if allok else "FAIL")
sys.exit(0 if allok else 1)
