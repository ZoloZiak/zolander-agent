#!/usr/bin/env python3
"""zolander_loop.py — F3 background tick (one-shot, spusta ho launchd StartInterval).

Jeden TICK:
  1. integrity check (ak zlyha -> zaloguj a skonci, NErob nic dalsie)
  2. heartbeat -> state/heartbeat.txt (timestamp + pid)
  3. sken dovolenych git projektov: nezacomitovane zmeny -> zapis do denníka
  4. zaloguj tick do logs/loop.log

ZAMERNE bez LLM volani (lacne + overitelne). LLM obohacovanie = F4 "sen".
Iba stdlib -> bezi na /usr/bin/python3, ziaden venv.
"""
import os
import sys
import json
import time
import subprocess
import datetime

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
DENNIKY = os.path.join(ROOT, "denniky")
LOGS = os.path.join(ROOT, "logs")
HEARTBEAT = os.path.join(STATE, "heartbeat.txt")
LOOPLOG = os.path.join(LOGS, "loop.log")
INTEGRITY = os.path.join(ROOT, "toolkit", "integrity.py")

# dovolene projekty na sken (P1 z PLAN §5) — len citanie stavu, ziadne zmeny
ALLOWED_PROJECTS = [
    os.path.join(HOME, "zolo2.0"),
    os.path.join(HOME, "turiec-pod-lupou"),
]


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(LOOPLOG, "a") as f:
        f.write(f"{now()} | {msg}\n")


def check_integrity():
    """Variant B — rozlisuje SKUTOCNY utok od Hermes-vlastneho prepisu skillu.

    Fail-closed IBA ked nesedia kryptograficke kluce (pub/fingerprint) alebo
    chyba samotny integrity skript. Ked sedia kluce a nesedi LEN skill (Hermes
    si SKILL.md sam prepisuje: normalizacia frontmatteru, curator, `hermes
    update`), NEjde o utok -> loop sa SAM re-baselinuje, posle info a tika dalej.

    Vrati (ok: bool, note: str|None). note != None -> stala sa auto-oprava.
    """
    if not os.path.exists(INTEGRITY):
        log("INTEGRITY SKRIPT CHYBA (%s) — fail-closed, tick prerušený." % INTEGRITY)
        return False, None

    # 1. plny check — ak prejde, hotovo
    full = subprocess.run([sys.executable, INTEGRITY, "check"],
                          capture_output=True, text=True)
    if full.returncode == 0:
        return True, None

    # 2. plny check zlyhal -> preveriť SKUTOCNU identitu (len kluce)
    keys = subprocess.run([sys.executable, INTEGRITY, "check-keys"],
                          capture_output=True, text=True)
    if keys.returncode != 0:
        # kluce/fingerprint nesedia = realny utok na identitu -> FAIL-CLOSED
        log("INTEGRITY FAIL — KLUCE/FINGERPRINT nesedia (mozny utok)! tick prerušený.")
        return False, None

    # 3. kluce OK, nesedi len skill -> Hermes-vlastny prepis, NIE utok.
    #    sam re-baselinuj a pokracuj.
    wr = subprocess.run([sys.executable, INTEGRITY, "write"],
                        capture_output=True, text=True)
    if wr.returncode != 0:
        log("INTEGRITY: re-baseline skillu ZLYHAL (%s) — tick prerušený." % wr.stderr.strip())
        return False, None
    note = "SKILL.md sa zmenil (Hermes-vlastny prepis, kluce OK) — auto re-baseline, loop pokracuje."
    log("INTEGRITY: " + note)
    return True, note


def notify(msg):
    """Best-effort info cez zolander_notify.py (fail-open)."""
    notify_py = os.path.join(ROOT, "toolkit", "zolander_notify.py")
    if not os.path.exists(notify_py):
        return
    try:
        subprocess.run(["/usr/bin/python3", notify_py, msg],
                       capture_output=True, text=True, timeout=70)
    except Exception as e:
        log(f"notify zlyhal: {e!r}")


def write_heartbeat():
    os.makedirs(STATE, exist_ok=True)
    with open(HEARTBEAT, "w") as f:
        f.write(json.dumps({"ts": now(), "pid": os.getpid(),
                            "epoch": int(time.time())}) + "\n")


def git_dirty(project):
    """Vrati zoznam zmenenych suborov (porcelain), alebo None ak nie je git/neexistuje."""
    if not os.path.isdir(os.path.join(project, ".git")):
        return None
    p = subprocess.run(["git", "-C", project, "status", "--porcelain"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return [l for l in p.stdout.splitlines() if l.strip()]


def scan_projects():
    findings = []
    for proj in ALLOWED_PROJECTS:
        dirty = git_dirty(proj)
        if dirty is None:
            continue
        if dirty:
            findings.append((os.path.basename(proj), dirty))
    return findings


def write_diary(findings):
    if not findings:
        return
    os.makedirs(DENNIKY, exist_ok=True)
    day = datetime.date.today().isoformat()
    path = os.path.join(DENNIKY, f"{day}.md")
    with open(path, "a") as f:
        f.write(f"\n## tick {now()}\n")
        for name, dirty in findings:
            f.write(f"- **{name}**: {len(dirty)} nezacomitovanych zmien\n")
            for line in dirty[:20]:
                f.write(f"  - `{line}`\n")


def tick():
    ok, note = check_integrity()
    if not ok:
        log("INTEGRITY FAIL — identita zmenena! tick prerušený.")
        return 1
    write_heartbeat()
    findings = scan_projects()
    write_diary(findings)
    total = sum(len(d) for _, d in findings)
    log(f"tick OK | projekty so zmenami={len(findings)} | zmien spolu={total}")
    if note:
        notify("🔧 Zolander loop: " + note)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(tick())
    except Exception as e:
        log(f"TICK EXCEPTION: {e!r}")
        sys.exit(1)
