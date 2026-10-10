#!/usr/bin/env python3
"""reality_audit.py — strážca DRIFTU docs/SOUL.md/skillov voči REALITE.

PROBLEM ktory riesi (veducko, 2026-10-01): stack ma skvelu self-heal + notify vrstvu
na KOD (watchdog: loop/db/integrity; recall_health: self-heal daemonov), ale
DOKUMENTACIA a PERSONA-ZDROJE (SOUL.md, lookup jadra skillov) nemaju ziadneho straznika.
Kod sa opravi sam, text klame dalej. Dokazane pripady driftu:
  - SOUL.md odkazoval na ~/zolander po presune na ~/projects/zolander
  - skill ziak-local-ai-stack tvrdil palantir_gate_v2.py, plist spusta v3 (2026-10-01)
  - Gemma port / OrbStack->nativny launchd zmeny ostali v texte zamrznute

POCTIVA HRANICA (neslubujem strazcu prazdnych dveri):
  - NEvie overit ci je PROZA pravdiva ("W_GEM je 0.8" ked je 1.5) — semanticky drift
    v cislach sa strojovo nezisti bez single-source-of-truth. Na to je liek NEDUPLIKOVAT,
    nie detektor.
  - VIE overit STROJOVE KOTVY: existuju cesty? bezia launchd labely? pocuvaju porty?
    sedi binarka v pliste s tym co skill vyhlasuje za AKTIVNU? su mrtve vetvy (groq/agy)
    naozaj prec z configu?

DVE TRIEDY kontrol:
  1. DEKLAROVANE INVARIANTY (register nizsie) = FAIL-CLOSED. Rucne kotvy na to co sme
     videli horiet. Nesediaca kotva = CHYBA (exit 1, notify).
  2. GENERICKA EXTRAKCIA ciest zo SOUL.md = WARN. Vytiahne ~/... a /Users/... cesty,
     overi existenciu. Warn (nie fail) lebo text ma aj priklady/placeholdery.

Fail-open na VLASTNE chyby (nikdy nezhodi — chyba v audite nesmie nic rozbit).
Stdlib only, /usr/bin/python3 (ziadny torch/venv netreba).

Pouzitie:
  /usr/bin/python3 reality_audit.py              # text report + exit 0/1
  /usr/bin/python3 reality_audit.py --json       # strojovy JSON
  /usr/bin/python3 reality_audit.py --notify     # pri FAIL posli notify (brief/launchd)
  /usr/bin/python3 reality_audit.py --brief-line # jeden riadok pre ranny brief
"""
import os
import re
import sys
import json
import socket
import plistlib
import subprocess

HOME = os.path.expanduser("~")
ZROOT = os.environ.get("ZOLANDER_ROOT") or (
    os.path.join(HOME, "projects", "zolander")
    if os.path.isdir(os.path.join(HOME, "projects", "zolander"))
    else os.path.join(HOME, "zolander")
)
LA = os.path.join(HOME, "Library", "LaunchAgents")
SKILLS = os.path.join(HOME, ".hermes", "skills")
SOUL = os.path.join(HOME, ".hermes", "SOUL.md")
CONFIG = os.path.join(HOME, ".hermes", "config.yaml")
NOTIFY = os.path.join(ZROOT, "toolkit", "zolander_notify.py")
SYS_PY = "/usr/bin/python3"

STACK_SKILL = os.path.join(SKILLS, "mlops", "ziak-local-ai-stack", "SKILL.md")

# ── DEKLAROVANE INVARIANTY (FAIL-CLOSED) ──────────────────────────────────

# launchd labely co MAJU byt loaded (jadro Zolander behu)
REQUIRED_LAUNCHD = [
    "pl.zolander.hyperspace",
    "pl.zolander.gemmaembed",
    "pl.zolander.palantir-gate",
    "pl.zolander.loop",
    "pl.zolander.dream",
    "pl.zolander.brief",
    "pl.zolander.initiative",
    "pl.zolander.writeback",
    "pl.zolander.watchdog",
]

# porty co MAJU pocuvat (daemon -> port)
REQUIRED_PORTS = [
    (50051, "HyperspaceDB (vektorova DB)"),
    (8901, "EmbeddingGemma daemon (3. recall lens)"),
    (8787, "palantir-gate shim (LLM pacing)"),
]

# kriticke cesty co MUSIA existovat (kotvy co skilly/SOUL spominaju ako fakt)
REQUIRED_PATHS = [
    (os.path.join(ZROOT, "identity", "zolander_ed25519.key"), "Ed25519 identita"),
    (os.path.join(ZROOT, ".venv-yar", "bin", "python"), "YAR torch venv"),
    (os.path.join(HOME, "models", "yar_v5_embedding"), "YAR v5 embed model"),
    (os.path.join(ZROOT, "toolkit", "zol_mem.py"), "pamat zol_mem"),
    (STACK_SKILL, "skill ziak-local-ai-stack"),
]

# mrtve vetvy co NESMU byt v config.yaml (dokazany cleanup)
CONFIG_ABSENT = ["groq", "agy-bridge", "opencode-bridge"]
# providery co TAM MAJU byt
CONFIG_PRESENT = ["palantir-claude", "palantir-gpt", "palantir-gemini"]


def _ok(checks, cid, msg):
    checks.append({"id": cid, "status": "OK", "msg": msg})


def _fail(checks, cid, msg):
    checks.append({"id": cid, "status": "FAIL", "msg": msg})


def _warn(checks, cid, msg):
    checks.append({"id": cid, "status": "WARN", "msg": msg})


def check_launchd(checks):
    for label in REQUIRED_LAUNCHD:
        try:
            p = subprocess.run(["/bin/launchctl", "list", label],
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                _ok(checks, f"launchd:{label}", f"{label} loaded")
            else:
                _fail(checks, f"launchd:{label}", f"{label} NIE je loaded (daemon chyba)")
        except Exception as e:
            _warn(checks, f"launchd:{label}", f"launchctl zlyhal: {str(e)[-80:]}")


def check_ports(checks):
    for port, desc in REQUIRED_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=3):
                _ok(checks, f"port:{port}", f":{port} pocuva ({desc})")
        except Exception:
            _fail(checks, f"port:{port}", f":{port} NEPOCUVA — {desc} dole")


def check_paths(checks):
    for path, desc in REQUIRED_PATHS:
        if os.path.exists(path):
            _ok(checks, f"path:{desc}", f"{desc} existuje")
        else:
            _fail(checks, f"path:{desc}", f"CHYBA cesta: {path} ({desc})")


def check_gate_version(checks):
    """JADROVY DRIFT DETEKTOR: binarka ktoru plist REALNE spusta vs. ktoru skill
    vyhlasuje za AKTIVNU. Presne to co chytilo v2->v3 (2026-10-01)."""
    plist = os.path.join(LA, "pl.zolander.palantir-gate.plist")
    real_bin = None
    try:
        with open(plist, "rb") as f:
            data = plistlib.load(f)
        args = data.get("ProgramArguments", [])
        # najdi prvy .py v argumentoch (ProgramArguments[0] je python)
        for a in args:
            if a.endswith(".py"):
                real_bin = os.path.basename(a)
                break
        if real_bin and not os.path.exists([a for a in args if a.endswith(".py")][0]):
            _fail(checks, "gate:binary_exists",
                  f"plist spusta {real_bin} ale subor NEEXISTUJE")
    except Exception as e:
        _warn(checks, "gate:plist", f"plist sa neda precitat: {str(e)[-80:]}")
        return

    # co skill vyhlasuje za AKTIVNU VERZIU
    skill_bin = None
    try:
        with open(STACK_SKILL, encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"AKTIVNA VERZIA:\s*`[^`]*?(palantir_gate[\w.]*\.py)`", txt)
        if m:
            skill_bin = m.group(1)
    except Exception as e:
        _warn(checks, "gate:skill", f"skill sa neda precitat: {str(e)[-80:]}")
        return

    if real_bin and skill_bin:
        if real_bin == skill_bin:
            _ok(checks, "gate:version",
                f"gate binarka sedi (plist aj skill = {real_bin})")
        else:
            _fail(checks, "gate:version",
                  f"DRIFT: plist spusta {real_bin}, skill vyhlasuje {skill_bin} "
                  f"— aktualizuj skill ziak-local-ai-stack")
    elif real_bin and not skill_bin:
        _warn(checks, "gate:version",
              f"plist spusta {real_bin}, v skille som nenasiel 'AKTIVNA VERZIA'")


def check_config(checks):
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = f.read()
    except Exception as e:
        _warn(checks, "config", f"config.yaml sa neda precitat: {str(e)[-80:]}")
        return
    for dead in CONFIG_ABSENT:
        # hladaj ako provider kluc / alias (pod providers: alebo aliases:), nie v komentari
        if re.search(rf"^\s*{re.escape(dead)}\s*:", cfg, re.MULTILINE):
            _fail(checks, f"config:dead:{dead}",
                  f"mrtva vetva '{dead}' je STALE v config.yaml (mala byt odstranena)")
        else:
            _ok(checks, f"config:dead:{dead}", f"'{dead}' nie je v configu (OK)")
    for need in CONFIG_PRESENT:
        if need in cfg:
            _ok(checks, f"config:need:{need}", f"provider '{need}' je v configu")
        else:
            _fail(checks, f"config:need:{need}",
                  f"provider '{need}' CHYBA v config.yaml")


def check_soul_paths(checks):
    """GENERICKA extrakcia (WARN): vytiahni cesty zo SOUL.md a over existenciu.
    Warn nie fail — SOUL ma aj priklady/placeholdery/__USER__."""
    if not os.path.exists(SOUL):
        _warn(checks, "soul:exists", f"SOUL.md neexistuje na {SOUL}")
        return
    try:
        with open(SOUL, encoding="utf-8") as f:
            txt = f.read()
    except Exception as e:
        _warn(checks, "soul:read", f"SOUL.md sa neda precitat: {str(e)[-80:]}")
        return
    # cesty: ~/... alebo /Users/... po whitespace/backtick/zatvorku
    cands = set(re.findall(r"(?:~|/Users/[\w.\-]+)/[\w./\-]+", txt))
    missing = []
    for c in cands:
        c = c.rstrip(".,;:)")  # oristni vetnu interpunkciu (inak false-positive)
        if "__USER__" in c or "<" in c or c.endswith("/"):
            continue  # placeholder / adresarovy vzor
        expanded = os.path.expanduser(c.replace("/Users/__USER__", HOME))
        # ignoruj zjavne priklady (hviezdicka, premenne)
        if "*" in expanded or "$" in expanded:
            continue
        if not os.path.exists(expanded):
            missing.append(c)
    if missing:
        _warn(checks, "soul:paths",
              f"SOUL.md spomina {len(missing)} neexistujucich ciest: " +
              ", ".join(sorted(missing)[:6]) + (" ..." if len(missing) > 6 else ""))
    else:
        _ok(checks, "soul:paths", f"vsetky konkretne cesty v SOUL.md existuju "
                                  f"({len(cands)} kandidatov)")


# MRTVE FRAZY co NESMU byt v SOUL.md. SOUL sa injektuje KAZDY turn a ma opisovat
# IBA AKTUALNY stav — na rozdiel od references/, ktore legitimne dokumentuju historiu.
# Preto tento check je SCOPED LEN na SOUL.md (v referencoch by 'Groq odstraneny' bol OK).
# Kazda fraza = fakt co BOL pravdivy a UZ NIE JE. Regex (IGNORECASE), + preco je mrtva.
SOUL_STALE_PHRASES = [
    (r"\bserializes\b", "gate v3 (min-conc>=3) serializacii ZABRANUJE — 'serializes sessions' bola v1 chyba (regex matnevhodnee LEN afirmativne sloveso, nie pravdive 'prevents serialization')"),
    (r"orbstack", "DB je nativny launchd pl.zolander.hyperspace, NIE OrbStack (odstr. 2026-08-30)"),
    (r"\bdocker\b", "DB nebezi v Dockeri — nativna binarka na :50051"),
    (r"\bgroq\b", "Groq cely odstraneny 2026-08-29 (fallback=none)"),
    (r"palantir_gate_v2|palantir_gate\.py\b", "aktivna gate binarka je v3"),
    (r"cosine\s*768", "pamat je 129D Lorentz (YAR v5), cosine-768 vetva zrusena"),
    (r"agy-bridge|\bagy\b", "agy bridge odstraneny 2026-09-05"),
    (r"(?<!projects/)\~/zolander/|(?<!projects/)/Users/\w+/zolander/",
     "root sa presunul na ~/projects/zolander (bare ~/zolander je stara cesta)"),
]


def check_soul_stale(checks):
    """FAIL-CLOSED: SOUL.md (every-turn prompt) NESMIE obsahovat mrtve frazy.
    Toto je strojovo-overitelny kus 'prozoveho driftu' — nie cela pravdivost
    (to sa neda), ale ZNAME mrtve tvrdenia ano. Scoped LEN na SOUL.md."""
    if not os.path.exists(SOUL):
        return
    try:
        with open(SOUL, encoding="utf-8") as f:
            txt = f.read()
    except Exception as e:
        _warn(checks, "soul:stale_read", f"SOUL.md sa neda precitat: {str(e)[-80:]}")
        return
    hit_any = False
    for pat, why in SOUL_STALE_PHRASES:
        m = re.search(pat, txt, re.IGNORECASE)
        if m:
            hit_any = True
            _fail(checks, f"soul:stale:{pat[:20]}",
                  f"SOUL.md obsahuje mrtvu frazu '{m.group(0)}' — {why}")
    if not hit_any:
        _ok(checks, "soul:stale", "SOUL.md neobsahuje ziadnu znamu mrtvu frazu")


def run_all():
    checks = []
    for fn in (check_launchd, check_ports, check_paths,
               check_gate_version, check_config, check_soul_paths,
               check_soul_stale):
        try:
            fn(checks)
        except Exception as e:
            _warn(checks, fn.__name__, f"kontrola zlyhala (fail-open): {str(e)[-100:]}")
    fails = [c for c in checks if c["status"] == "FAIL"]
    warns = [c for c in checks if c["status"] == "WARN"]
    return checks, fails, warns


def notify(fails, warns):
    try:
        lines = ["REALITA-AUDIT nasiel drift medzi dokumentaciou/stackom a realitou:"]
        for c in fails:
            lines.append(f"- [FAIL] {c['msg']}")
        for c in warns[:5]:
            lines.append(f"- [warn] {c['msg']}")
        subprocess.run([SYS_PY, NOTIFY, "--subject", "realita-audit DRIFT",
                        "--sound", "Sosumi", "\n".join(lines)],
                       timeout=90, cwd=ZROOT)
    except Exception:
        pass


def main(argv):
    checks, fails, warns = run_all()

    if "--json" in argv:
        print(json.dumps({"checks": checks, "fails": len(fails),
                          "warns": len(warns)}, ensure_ascii=False, indent=2))
    elif "--brief-line" in argv:
        if fails:
            print(f"- realita-audit: {len(fails)} DRIFT, {len(warns)} warn "
                  f"(spusti reality_audit.py)")
        elif warns:
            print(f"- realita-audit: OK, {len(warns)} warn")
        else:
            print("- realita-audit: OK (docs/stack sedia s realitou)")
    else:
        for c in checks:
            tag = {"OK": "  ok", "WARN": "warn", "FAIL": "FAIL"}[c["status"]]
            print(f"[{tag}] {c['msg']}")
        print(f"\n{len(fails)} FAIL, {len(warns)} warn, "
              f"{len(checks)-len(fails)-len(warns)} ok")

    if fails and "--notify" in argv:
        notify(fails, warns)

    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        # fail-open: audit nikdy nezhodi volajuceho (brief/launchd)
        print(f"REALITY_AUDIT EXCEPTION (fail-open): {exc!r}", file=sys.stderr)
        sys.exit(0)
