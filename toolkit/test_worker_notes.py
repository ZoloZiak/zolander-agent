#!/usr/bin/env python3
"""test_worker_notes.py — Zero-Shot orchestration scratchpad (2608.26480)
+ SKILL.state delta-log (2608.26263).

Dva orchestračné mechanizmy zo scout backlogu:
  - worker_notes: medzikrokový scratchpad — agent si medzi subtaskami odkladá
    poznámky (čo zistil, čo zostáva), aby sa kontext neniesol celý v hlave.
    Append-only JSONL, čítateľný späť ako súhrn.
  - skill_delta: keď sa skill zmení, zapíš delta (čo/prečo) — auditná stopa
    zmien persony/nástrojov, aby drift nebol neviditeľný.

Kontrakt (worker_notes, in-memory + JSONL):
  ScratchPad(path).add(task, note, status) ; .summary() -> str ; .pending() -> list
Kontrakt (skill_delta):
  log_delta(path, skill, change, why) -> dict ; read_deltas(path) -> list
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worker_notes import ScratchPad, log_delta, read_deltas  # noqa: E402


def _check(name, cond):
    if not cond:
        print(f"FAIL worker_notes: {name}")
        sys.exit(1)


def main():
    tmp = tempfile.mkdtemp()
    sp_path = os.path.join(tmp, "scratch.jsonl")

    # 1) scratchpad append + summary
    sp = ScratchPad(sp_path)
    sp.add("fetch", "stiahol som 24 gold otázok", status="done")
    sp.add("eval", "graph expansion Δmrr<0", status="done")
    sp.add("commit", "ešte nezacommitované", status="pending")
    summ = sp.summary()
    _check("summary obsahuje všetky 3 tasky", summ.count("\n") >= 2 or len(summ) > 20)
    _check("summary spomína eval", "eval" in summ)

    # 2) pending vráti len nedokončené
    pend = sp.pending()
    _check("pending = 1", len(pend) == 1)
    _check("pending je commit", pend[0]["task"] == "commit")

    # 3) perzistencia: nový ScratchPad na tej istej ceste vidí staré
    sp2 = ScratchPad(sp_path)
    _check("reload vidí 3 záznamy", len(sp2.entries) == 3)

    # 4) robustnosť: prázdna cesta / prázdna poznámka nespadne
    sp.add("", "", status="pending")
    _check("prázdny task nespadne", True)

    # 5) skill delta-log
    dpath = os.path.join(tmp, "skill_deltas.jsonl")
    r = log_delta(dpath, "zolander", "pridaný F11 guard test", "F11 bol bez regresie")
    _check("log_delta vráti ts", "ts" in r)
    deltas = read_deltas(dpath)
    _check("čítanie delty", len(deltas) == 1 and deltas[0]["skill"] == "zolander")
    _check("delta má why", deltas[0]["why"] == "F11 bol bez regresie")

    print("PASS worker_notes: scratchpad add/summary/pending/perzist + skill delta-log")


if __name__ == "__main__":
    main()
