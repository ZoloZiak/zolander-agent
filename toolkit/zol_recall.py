#!/usr/bin/env python3
"""zol_recall.py — INTERAKTÍVNY recall wrapper (fix B, spike 012 wire).

Problém: cmd_recall() default source='adhoc' (=NEznáme). Keď Zolander/človek
spustí recall uprostred rozhovoru cez surové `echo '{...}' | zol_mem.py recall`,
padne do 'adhoc' a mem_usage_audit ho nevie odlíšiť od starého strojového šumu.

Riešenie: tento wrapper VŽDY pošle source='interactive'. Používaj ho mid-konverzácia
namiesto surového volania — audit potom meria PRAVDU (koľko recallov je reálne
ľudských vs stroj). Default v cmd_recall ostáva 'adhoc' zámerne (neznáme = neznáme;
NEflipovať default na interactive, inak sa každý neotagovaný daemon zmení na
falošného 'človeka' — presne ten overclaim, ktorý spike 012 zabíja).

Beží pod /usr/bin/python3 (stdlib) — ťažký YAR recall deleguje do venv subprocess.

Použitie:
    /usr/bin/python3 toolkit/zol_recall.py "tvoj dotaz"
    /usr/bin/python3 toolkit/zol_recall.py "tvoj dotaz" 8        # topk=8
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPY = os.path.join(ROOT, ".venv-yar", "bin", "python")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")


def main(argv):
    if not argv:
        print('pouzitie: zol_recall.py "dotaz" [topk]', file=sys.stderr)
        return 2
    query = argv[0]
    try:
        topk = int(argv[1]) if len(argv) > 1 else 6
    except ValueError:
        topk = 6
    payload = json.dumps(
        {"query": query, "topk": topk, "source": "interactive"},
        ensure_ascii=False,
    )
    p = subprocess.run(
        [VPY, ZOL_MEM, "recall"],
        input=payload, capture_output=True, text=True, timeout=180,
    )
    sys.stdout.write(p.stdout)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-400:])
    return p.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
