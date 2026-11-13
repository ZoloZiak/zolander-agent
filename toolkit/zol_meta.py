#!/usr/bin/env python3
"""zol_meta.py — Meta-Agent nad checker reportmi (bod 1). Recuris "fixed Meta-Agent".

Recuris (arXiv 2608.24876): fixny Meta-Agent cita STRUKTUROVANE zlyhanie z behu,
lokalizuje ho na KOMPONENT, a navrhne LOKALIZOVANY, VALIDACIOU-PODMIENENY update.
Tu je jeho verzia pre nas stack, s tvrdymi poistkami tohto prostredia:

  1) DETERMINISTICKE JADRO (testovatelne bez LLM): z checker reportu spravi pre kazdy
     FAIL "repair directive" = {anchor, component, fail_class, reason, action, target}.
     action je RULE-BASED mapa (component x fail_class -> co spravit). Ziadna mágia.
  2) PROPOSE-MODE (nie auto-apply): directives sa ZAPISU do state/meta_pending.jsonl.
     Meta-Agent SAM NEMENI main vetvu ani skilly — to je tok "zrob N"/vedúcko schvali.
     (Rovnaka disciplina ako initiative.py: navrhni, nekonaj na main.)
  3) VALIDACNA BRANA (EvolveMem/Recuris gate): `verify` znova spusti manifest a proposal
     je VALIDNY iba ak cielove anchory teraz PRECHADZAJU a NEVZNIKLA regresia (exit 2).
     Nevalidovany navrh sa NEoznaci za hotovy — presne "action != completion".
  4) VOLITELNA LLM VRSTVA (--llm): obohati deterministicku diagnozu o prirodzeny
     repair-plan cez llm_client.chat (opus). FAIL-OPEN: bez LLM ostane rule-based.

Toto NIE je plna RSI slucka co sama prepisuje kod — to by na monitorovanom
Macu bola pistol namierena na nohu. Je to DIAGNOSTIK + NAVRHAR + validator; ruku na
spusti ma vedúcko. Presne ako to chcel: mechanizmus, nie autopilot na main.

CLI:
  zol_meta.py diagnose <report.json>          # report zo zol_checker.py run --> directives
  zol_meta.py diagnose <report.json> --llm     # + LLM repair-plan (opus, fail-open)
  zol_meta.py propose <report.json>            # diagnose + zapis do meta_pending.jsonl
  zol_meta.py verify <manifest.json>           # validacna brana: re-run, PASS+bez regresie?
  zol_meta.py pending                          # vypis otvorene navrhy
  echo '<report JSON>' | zol_meta.py diagnose - 
"""
import os
import sys
import json
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
try:
    from zol_paths import STATE
except Exception:
    STATE = os.path.expanduser("~/projects/zolander/state")
try:
    from zol_events import emit, new_run
except Exception:
    def emit(*a, **k):
        pass

    def new_run(s):
        return None

SYS_PY = "/usr/bin/python3"
ZOL_CHECKER = os.path.join(HERE, "zol_checker.py")
PENDING = os.path.join(STATE, "meta_pending.jsonl")

# --- RULE-BASED repair mapa: (component, fail_class) -> co spravit. ---
# Recuris: patch smeruj na komponent co zlyhal, nie prepisuj celok. OpenSkill:
# knowledge-gap (chod zisti) vs implementation-bug (oprav krok) su INE opravy.
_REPAIR = {
    ("skill", "implementation_bug"):
        "Sekcia/marker v skille chyba alebo je zle — priamo dopln/oprav SKILL.md sekciu (patch, nie rewrite).",
    ("skill", "knowledge_gap"):
        "Skillu chyba informacia — najprv zisti fakt (rešerš/čítanie), potom dopln do skillu.",
    ("retrieval", "knowledge_gap"):
        "Artefakt necituje zdroj co ma — retrieval nevytiahol spravne atomy. Over query = aktualny subgoal (nie pociatocna instrukcia), potom doplň citacie.",
    ("artifact", "implementation_bug"):
        "Krok bol vykonany zle — oprav samotny artefakt/kod na deklarovanom mieste.",
    ("artifact", "missing"):
        "Artefakt/subor neexistuje — vytvor ho (krok sa nevykonal, hoci mohol tvrdit opak).",
    ("artifact", "leak"):
        "LEAK realneho mena/cesty — sanitizuj PRED akymkolvek pushom (__USER__->__USER__, odstran /Users/...). BLOKUJUCE pre verejny repo.",
    ("artifact", "regression"):
        "REGRESIA — anchor co predtym presiel teraz padol. Revert-on-regression: vrat poslednu zmenu co to pokazila (EvolveMem).",
    ("state", "implementation_bug"):
        "Task-state je nekonzistentny — oprav tracking (zol_tasks/state), nie artefakt.",
}


def _repair_action(component, fail_class):
    if (component, fail_class) in _REPAIR:
        return _REPAIR[(component, fail_class)]
    # rozumny default podla klasy, ked komponent nemame v mape
    generic = {
        "leak": "LEAK — sanitizuj pred pushom (BLOKUJUCE).",
        "missing": "Chyba artefakt — vytvor/dokonci krok.",
        "knowledge_gap": "Chyba informacia — najprv zisti, potom oprav.",
        "regression": "Regresia — revert poslednej zmeny.",
        "implementation_bug": "Krok vykonany zle — oprav ho na mieste.",
    }
    return generic.get(fail_class, "Preskumaj zlyhanie a oprav zodpovedny komponent.")


def diagnose(report, use_llm=False):
    """Z checker reportu sprav zoznam repair directives (deterministicky).
    Kazda directive lokalizuje zlyhanie na komponent a navrhne CIELENU opravu."""
    fails = [r for r in report.get("results", []) if not r.get("pass")]
    directives = []
    for r in fails:
        comp = r.get("component", "artifact")
        cls = r.get("fail_class", "implementation_bug")
        d = {
            "anchor": r.get("id"),
            "type": r.get("type"),
            "component": comp,
            "fail_class": cls,
            "reason": r.get("reason", ""),
            "action": _repair_action(comp, cls),
            "target": r.get("path") or r.get("repo") or "?",
            "blocking": cls in ("leak", "regression"),
        }
        directives.append(d)
    diag = {
        "task": report.get("task"),
        "n_fail": len(fails),
        "regression": report.get("regression", False),
        "directives": directives,
        # zoradenie priorit: blokujuce (leak/regresia) prve
        "priority": [d["anchor"] for d in sorted(
            directives, key=lambda x: (not x["blocking"], x["fail_class"]))],
    }
    if use_llm and directives:
        diag["llm_plan"] = _llm_plan(diag)
    return diag


def _llm_plan(diag):
    """Volitelne: obohat deterministicku diagnozu o prirodzeny repair-plan.
    FAIL-OPEN — ak LLM nedostupny, vrat None (rule-based directives staci)."""
    try:
        from llm_client import chat
    except Exception as e:
        return None
    sysmsg = ("Si diagnostik agent-harnessu. Dostanes strukturovane zlyhania checker "
              "anchorov (uz lokalizovane na komponent + klasifikovane). Navrhni STRUCNY "
              "poradovnik krokov opravy. Respektuj: knowledge-gap=zisti; implementation-bug="
              "oprav krok; leak=sanitizuj a blokuj push; regression=revert. Ziadna vata.")
    try:
        raw = chat(json.dumps(diag, ensure_ascii=False), model="opus",
                   system=sysmsg, max_tokens=500)
        return raw.strip()
    except Exception:
        return None


def propose(report, use_llm=False):
    """Diagnose + zapis directives do meta_pending.jsonl (PROPOSE-MODE, nie apply)."""
    diag = diagnose(report, use_llm=use_llm)
    os.makedirs(STATE, exist_ok=True)
    rid = new_run("meta")
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "run_id": rid,
        "task": diag["task"],
        "n_fail": diag["n_fail"],
        "directives": diag["directives"],
        "status": "pending",
    }
    with open(PENDING, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    emit("meta", "proposed", {"task": diag["task"], "n_fail": diag["n_fail"]}, rid)
    return {**diag, "written_to": PENDING}


def verify_proposal(manifest_path):
    """VALIDACNA BRANA (Recuris/EvolveMem): znova spusti manifest cez zol_checker
    --regress. Proposal je VALIDNY iba ak: fail==0 A ziadna regresia. Vrati verdikt.
    Toto je mechanicka brana — 'action != completion' vynutene kodom."""
    p = subprocess.run([SYS_PY, ZOL_CHECKER, "run", manifest_path, "--regress"],
                       capture_output=True, text=True)
    try:
        report = json.loads(p.stdout)
    except Exception:
        return {"validated": False, "reason": f"checker nevratil JSON: {p.stderr[-200:]}",
                "exit": p.returncode}
    validated = (report.get("fail", 1) == 0) and not report.get("regression", False)
    verdict = {
        "validated": validated,
        "exit": p.returncode,
        "fail": report.get("fail"),
        "regression": report.get("regression", False),
        "regressed": report.get("regressed", []),
        "reason": "vsetky anchory PASS, ziadna regresia" if validated else
                  ("REGRESIA — nevalidne" if report.get("regression")
                   else f"{report.get('fail')} anchorov stale FAIL"),
    }
    emit("meta", "verify", {"manifest": os.path.basename(manifest_path),
                            "validated": validated})
    return verdict


def show_pending():
    if not os.path.exists(PENDING):
        return []
    out = []
    for ln in open(PENDING, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out


def _load_report(arg):
    if arg == "-":
        return json.loads(sys.stdin.read())
    return json.loads(open(os.path.expanduser(arg), encoding="utf-8").read())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "diagnose":
        if len(sys.argv) < 3:
            print("diagnose <report.json|-> [--llm]", file=sys.stderr)
            return 2
        rep = _load_report(sys.argv[2])
        print(json.dumps(diagnose(rep, use_llm="--llm" in sys.argv[3:]),
                         ensure_ascii=False, indent=2))
        return 0
    if cmd == "propose":
        if len(sys.argv) < 3:
            print("propose <report.json|-> [--llm]", file=sys.stderr)
            return 2
        rep = _load_report(sys.argv[2])
        print(json.dumps(propose(rep, use_llm="--llm" in sys.argv[3:]),
                         ensure_ascii=False, indent=2))
        return 0
    if cmd == "verify":
        if len(sys.argv) < 3:
            print("verify <manifest.json>", file=sys.stderr)
            return 2
        v = verify_proposal(os.path.expanduser(sys.argv[2]))
        print(json.dumps(v, ensure_ascii=False, indent=2))
        return 0 if v["validated"] else 1
    if cmd == "pending":
        print(json.dumps(show_pending(), ensure_ascii=False, indent=2))
        return 0
    print(f"neznamy prikaz: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
