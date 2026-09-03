#!/usr/bin/env python3
"""claim_ledger.py — väzenie proti tvrdeniam, ktoré dáta vyvrátia.

PREČO existuje (2026-08-31): v jednej úlohe som 3× tvrdil load-bearing fakt
("IBIA provenance neexistuje", "prázdne vektory = bug", "5 CONFLICTov") a dáta
ma zakaždým vyvrátili. Zakaždým som to MOHOL overiť lacným nástrojom a neurobil.
Toto je štrukturálna poistka podľa anti-hallucination-protocol §6.6:
  "goal moves pending->done LEN keď checker prečíta POZOROVANIE (nie moje tvrdenie)."

MODEL:
  Load-bearing tvrdenie (X hotové / X neexistuje / X rozbité) sa registruje s
  RE-SPUSTITEĽNOU kontrolou, ktorá číta ground truth NEZÁVISLE od môjho slova.
  Kontrola vráti jeden z troch stavov (§7.5 — empty != error != false):
    VERIFIED     — pozorovanie tvrdenie POTVRDILO
    REFUTED      — pozorovanie tvrdenie VYVRÁTILO
    UNVERIFIABLE — kontrola zlyhala/nedá sa spustiť (chýba cesta, výnimka)
  GATE: batch je "done" LEN ak VŠETKY tvrdenia sú VERIFIED.
  UNVERIFIABLE blokuje ROVNAKO ako REFUTED — nesmiem "mať pravdu z presvedčenia".

Použitie (v kóde alebo z CLI):
  from claim_ledger import Ledger, checks
  L = Ledger()
  L.claim("IBIA: 410/410 riadkov má source",
          checks.jsonl_field_all("state/mem_index.jsonl", "source"))
  L.claim("#120 superseded do #109",
          checks.temporal_superseded(120, 109))
  print(L.gate())          # vypíše tabuľku; exit-neutrálne
  assert L.all_verified()  # tvrdý zámok pred "hotovo"

CLI:  /usr/bin/python3 toolkit/claim_ledger.py --demo
"""
import os
import re
import sys
import json
import subprocess

ROOT = os.path.expanduser("~/projects/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))

VERIFIED = "VERIFIED"
REFUTED = "REFUTED"
UNVERIFIABLE = "UNVERIFIABLE"


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


class checks:
    """Továreň na kontroly. Každá vracia callable -> (stav, dôkaz:str).

    Kontrola NIKDY nevyhodí von výnimku — chytí ju a vráti UNVERIFIABLE
    (§7.5: 'bare except return []' je presne to, čo maskuje crash za 'nič tam nie je').
    Rozlišuje empty/error/false ako TRI rôzne stavy.
    """

    @staticmethod
    def file_line_contains(path, lineno, substr):
        def _c():
            try:
                p = _abs(path)
                if not os.path.exists(p):
                    return UNVERIFIABLE, f"{path} neexistuje"
                with open(p, encoding="utf-8") as f:
                    lines = f.readlines()
                if lineno > len(lines):
                    return REFUTED, f"{path} má len {len(lines)} riadkov, žiadaný {lineno}"
                actual = lines[lineno - 1]
                if substr in actual:
                    return VERIFIED, f"{path}:{lineno} obsahuje {substr!r}"
                return REFUTED, f"{path}:{lineno} = {actual.strip()[:80]!r}, nemá {substr!r}"
            except Exception as e:
                return UNVERIFIABLE, f"kontrola padla: {e!r}"
        return _c

    @staticmethod
    def grep_count(path, pattern, expected):
        """Počet riadkov matnevhodneúcich pattern == expected."""
        def _c():
            try:
                p = _abs(path)
                if not os.path.exists(p):
                    return UNVERIFIABLE, f"{path} neexistuje"
                rx = re.compile(pattern)
                n = sum(1 for line in open(p, encoding="utf-8") if rx.search(line))
                if n == expected:
                    return VERIFIED, f"{path}: {n} zhôd {pattern!r} == {expected}"
                return REFUTED, f"{path}: {n} zhôd {pattern!r}, čakané {expected}"
            except Exception as e:
                return UNVERIFIABLE, f"kontrola padla: {e!r}"
        return _c

    @staticmethod
    def jsonl_field_all(path, field):
        """KAŽDÝ riadok JSONL má neprázdne pole `field`. Vráti počty."""
        def _c():
            try:
                p = _abs(path)
                if not os.path.exists(p):
                    return UNVERIFIABLE, f"{path} neexistuje"
                total = has = 0
                for line in open(p, encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    o = json.loads(line)
                    if o.get(field) not in (None, ""):
                        has += 1
                if total == 0:
                    return UNVERIFIABLE, f"{path} prázdny — 0 riadkov (nie je to 'všetky OK')"
                if has == total:
                    return VERIFIED, f"{path}: {has}/{total} má {field!r}"
                return REFUTED, f"{path}: len {has}/{total} má {field!r}"
            except Exception as e:
                return UNVERIFIABLE, f"kontrola padla: {e!r}"
        return _c

    @staticmethod
    def temporal_superseded(old_id, by_id):
        """zol_graph temporal: old_id má valid_until + superseded_by == by_id."""
        def _c():
            try:
                import zol_graph
                st = zol_graph._temporal_state()
                s = st.get(old_id)
                if not s:
                    return REFUTED, f"#{old_id} nemá temporal záznam"
                if s.get("valid_until") and s.get("superseded_by") == by_id:
                    return VERIFIED, f"#{old_id} superseded -> #{by_id} @ {s['valid_until']}"
                return REFUTED, f"#{old_id} temporal = {s}"
            except Exception as e:
                return UNVERIFIABLE, f"kontrola padla: {e!r}"
        return _c

    @staticmethod
    def cmd_exit(cmd, expected_exit=0, must_contain=None):
        """Spusti príkaz (list argv, NIE shell), over exit a voliteľne substring."""
        def _c():
            try:
                r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                   text=True, timeout=600)
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode != expected_exit:
                    return REFUTED, f"exit {r.returncode} != {expected_exit}: {out[-160:]!r}"
                if must_contain and must_contain not in out:
                    return REFUTED, f"exit OK ale výstup nemá {must_contain!r}: {out[-160:]!r}"
                tail = must_contain or out.strip().split(chr(10))[-1][:80]
                return VERIFIED, f"exit {r.returncode}, {tail!r}"
            except Exception as e:
                return UNVERIFIABLE, f"kontrola padla: {e!r}"
        return _c

    @staticmethod
    def predicate(fn, label):
        """Ľubovoľný bool predikát -> (VERIFIED/REFUTED). Výnimka -> UNVERIFIABLE."""
        def _c():
            try:
                return (VERIFIED if fn() else REFUTED), label
            except Exception as e:
                return UNVERIFIABLE, f"predikát padol: {e!r}"
        return _c


class Ledger:
    def __init__(self):
        self.rows = []  # (statement, check_callable)

    def claim(self, statement, check):
        self.rows.append((statement, check))
        return self

    def _run(self):
        out = []
        for stmt, chk in self.rows:
            status, evidence = chk()
            out.append((stmt, status, evidence))
        return out

    def gate(self):
        """Spusti všetky kontroly, vráť (all_ok, výpis)."""
        res = self._run()
        ok = all(s == VERIFIED for _, s, _ in res)
        lines = ["=" * 60, "CLAIM LEDGER — zámok pred 'hotovo'", "=" * 60]
        icon = {VERIFIED: "[✓]", REFUTED: "[✗]", UNVERIFIABLE: "[?]"}
        for stmt, status, ev in res:
            lines.append(f"{icon[status]} {status:12} {stmt}")
            lines.append(f"      dôkaz: {ev}")
        n_ref = sum(1 for _, s, _ in res if s == REFUTED)
        n_unv = sum(1 for _, s, _ in res if s == UNVERIFIABLE)
        lines.append("-" * 60)
        if ok:
            lines.append(f"ZÁMOK OTVORENÝ: všetkých {len(res)} tvrdení VERIFIED.")
        else:
            lines.append(f"ZÁMOK ZAVRETÝ: {n_ref} vyvrátených, {n_unv} neoveriteľných "
                         f"— NESMIEM tvrdiť 'hotovo'.")
        return ok, "\n".join(lines)

    def all_verified(self):
        return all(s == VERIFIED for _, s, _ in self._run())


def _demo():
    """Sebatest väzenia: musí PUSTIŤ pravdu a ZAVRIEŤ na lži aj neoveriteľnom."""
    L = Ledger()
    L.claim("PRAVDA: mem_index má source vo všetkých riadkoch",
            checks.jsonl_field_all("state/mem_index.jsonl", "source"))
    L.claim("LOŽ: #120 superseded do #999 (nie je)",
            checks.temporal_superseded(120, 999))
    L.claim("NEOVERITEĽNÉ: neexistujúci súbor",
            checks.jsonl_field_all("state/neexistuje.jsonl", "x"))
    ok, txt = L.gate()
    print(txt)
    assert not ok, "väzenie MALO zavrieť (je tam lož + neoveriteľné)"
    print("\n[demo] väzenie správne ZAVRELO na lži+neoveriteľnom.")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        print(__doc__)
