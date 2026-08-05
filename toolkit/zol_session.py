#!/usr/bin/env python3
"""zol_session.py — životný cyklus sesie Zolandera: recall-first štart + konsolidačný koniec.

Zapája existujúce diely (zol_mem, zol_guard) do dvoch bodov sesie. NIE je to
event-hook (Hermes ich nemá) — je to skript volaný skillmi /start a /koniec.

  start           -> recall-first: načíta relevantné spomienky + chvost PLAN.md,
                     aby Zolander začal S KONTEXTOM, nie naslepo. Query z argv[2]
                     alebo default (stav + otvorené úlohy).
  koniec <file>   -> konsolidácia: zol_guard scan-text nad súborom s výstupmi
                     sesie (anti-halucinacia/sycophancy audit PRED uložením),
                     potom uloží zhrnutie ako episodic spomienku a spustí decay.

Spúšťať cez .venv-yar python (kvôli embed_yar v recall).
"""
import os
import sys
import json
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
VPY = "/Users/__USER__/zolander/.venv-yar/bin/python"
ZOL_MEM = os.path.join(HERE, "zol_mem.py")
ZOL_GUARD = os.path.join(HERE, "zol_guard.py")
LENS = os.path.join(HERE, "lens.py")
PATTERNS = os.path.join(HERE, "patterns.py")
PLAN = "/Users/__USER__/zolander/PLAN.md"
SYS_PY = "/usr/bin/python3"

DEFAULT_START_QUERY = "aktualny stav Zolander a otvorene ulohy co treba dokoncit"


def _run(argv, stdin=None):
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def plan_tail(n=40):
    """Posledných n riadkov PLAN.md (aktuálny stav býva na konci)."""
    if not os.path.exists(PLAN):
        return "(PLAN.md chýba)"
    lines = open(PLAN, encoding="utf-8", errors="replace").read().splitlines()
    return "\n".join(lines[-n:])


def cmd_start():
    query = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_START_QUERY
    print("=== ZOLANDER /start — recall-first ===\n")

    # 1) recall cez vsetky kolekcie (zol_mem sam prehlada vsetky ked kind=None)
    rc, out, err = _run([VPY, ZOL_MEM, "recall"],
                        stdin=json.dumps({"query": query, "topk": 6}))
    if rc == 0:
        try:
            hits = json.loads(out)
            print("PAMÄŤ (top spomienky k stavu):")
            for h in hits:
                d = h.get("distance", 0)
                txt = h.get("meta", {}).get("text", "")[:90]
                col = h.get("col", "?").replace("zol_", "")
                print(f"  [{col:10s} d={d:.3f}] {txt}")
        except Exception:
            print("recall raw:", out[:400])
    else:
        print("recall zlyhal:", err[-300:])

    # 2) chvost PLAN (aktualny stav)
    print("\nPLAN.md (chvost — aktuálny stav):")
    print(plan_tail(35))
    print("\n=== /start hotovo — pokračuj s kontextom, nie naslepo ===")


def cmd_koniec():
    if len(sys.argv) < 3:
        print("pouzitie: zol_session.py koniec <file_s_vystupmi>", file=sys.stderr)
        sys.exit(2)
    src = sys.argv[2]
    print("=== ZOLANDER /koniec — konsolidácia ===\n")

    # 1) MECHANICKA anti-halucinacia/sycophancy brana nad vystupmi PRED ulozenim
    rc, out, err = _run([SYS_PY, ZOL_GUARD, "scan-text", src])
    guard = json.loads(out) if out.strip() else {"ok": True, "findings": []}
    if guard["ok"]:
        print("GUARD: čisté — žiadne halucinačné/sycophancy nálezy vo výstupoch.")
    else:
        print(f"GUARD: {guard['count']} NÁLEZOV — pozor pred uložením:")
        for f in guard["findings"]:
            print(f"  ! {f['kind']} @L{f.get('line','?')}: {f.get('match','')[:60]}")
        print("  (uloz az po revizii — nekonsoliduj halucinaciu do pamate)")

    # 2) decay (navrhne co zabudnut / povysit — 'sen' F4 rozhodne)
    rc2, out2, err2 = _run([VPY, ZOL_MEM, "decay"])
    if rc2 == 0:
        try:
            s = json.loads(out2)
            print(f"\nDECAY: forget={len(s.get('forget',[]))} "
                  f"promote={len(s.get('promote',[]))} kept={s.get('kept',0)}")
        except Exception:
            print("\ndecay raw:", out2[:200])
    else:
        print("\ndecay zlyhal:", err2[-200:])

    print("\n=== /koniec hotovo — zhrnutie sesie ulož cez zol_mem remember "
          "(kind=episodic) IBA ak guard čistý ===")


def cmd_gate():
    """Double-take BRANA (Roadmap #2): deterministicky rozhodni ci otazka je vazna,
    a ak ano, spusti lift. Toto je konvencny vstupny bod ktory ma Zolander volat
    PRED vaznou odpovedou (Hermes nema event-hook, takze je to skill-disciplina).
    Vstup: argv[2] = otazka/situacia (alebo stdin)."""
    problem = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not problem:
        print("pouzitie: zol_session.py gate \"<otazka>\"", file=sys.stderr)
        sys.exit(2)
    rc, out, err = _run([SYS_PY, LENS, "gate"],
                        stdin=json.dumps({"problem": problem}))
    if rc == 0:
        print(out.strip())
    else:
        print("lens gate zlyhal:", err[-300:], file=sys.stderr)
        sys.exit(1)


def cmd_lens():
    """Double-take pred vážnou odpoveďou: deleguje na lens.py lift.
    Vstup: argv[2] = problém/situácia (alebo stdin)."""
    problem = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not problem:
        print("pouzitie: zol_session.py lens \"<problem>\"", file=sys.stderr)
        sys.exit(2)
    # lens lift potrebuje palantir_client (LLM) — beží pod sys python (stdlib urllib)
    rc, out, err = _run([SYS_PY, LENS, "lift"],
                        stdin=json.dumps({"problem": problem}))
    if rc == 0:
        print(out.strip())
    else:
        print("lens lift zlyhal:", err[-300:], file=sys.stderr)
        sys.exit(1)


def cmd_pattern():
    """Detektor vzorcov: 'akého vzorca je toto inštancia?'. Deleguje na patterns.py detect.
    Vstup: argv[2] = situácia. Embedding beží cez .venv-yar (YAR v5)."""
    situation = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read().strip()
    if not situation:
        print("pouzitie: zol_session.py pattern \"<situacia>\"", file=sys.stderr)
        sys.exit(2)
    rc, out, err = _run([VPY, PATTERNS, "detect"],
                        stdin=json.dumps({"situation": situation}))
    if rc == 0:
        print(out.strip())
    else:
        print("patterns detect zlyhal:", err[-300:], file=sys.stderr)
        sys.exit(1)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        cmd_start()
    elif cmd == "koniec":
        cmd_koniec()
    elif cmd == "gate":
        cmd_gate()
    elif cmd == "lens":
        cmd_lens()
    elif cmd == "pattern":
        cmd_pattern()
    else:
        print(f"neznámy režim: {cmd} (start|koniec|gate|lens|pattern)", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
