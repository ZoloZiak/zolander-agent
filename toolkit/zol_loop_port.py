#!/usr/bin/env python3
"""zol_loop_port.py — port hermes F3 loop tick na Windows (one-shot).

Jeden TICK (zamerne bez LLM):
  1. integrity check (integrity.py, ak existuje) — ak zlyha, zaloguj a koniec
  2. heartbeat -> state/heartbeat.txt (ts + pid)
  3. sken repa ZOLANDER_ROOT: nezacomitovane zmeny -> zapis do state/loop_findings.jsonl
  4. logs/loop.log

Cisto stdlib. Spusta Windows Scheduled Task / runner. Root: ZOLANDER_ROOT.
"""
import datetime
import os
import subprocess
import sys

ROOT = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "loop.log"), "a", encoding="utf-8") as f:
        f.write(f"{now()} | {msg}\n")


def check_integrity():
    script = os.path.join(ROOT, "toolkit", "integrity.py")
    if not os.path.exists(script):
        return True, "integrity.py absent (steps krok vypusten)"
    try:
        p = subprocess.run([sys.executable, script], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT, timeout=120)
        if p.returncode == 0:
            return True, "integrity OK"
        return False, f"integrity zlyhal exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
    except Exception as e:  # noqa: BLE001
        return False, f"integrity vynimka: {e}"


def scan_repo():
    """Nezacomitovane zmeny v ZOLANDER_ROOT (len citaj). Vracia (status, count)."""
    if not os.path.exists(os.path.join(ROOT, ".git")):
        return "not-a-repo", 0
    try:
        p = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT, timeout=60)
        lines = [l for l in p.stdout.splitlines() if l.strip() and ".tmp_" not in l]
        return "ok", len(lines)
    except Exception as e:  # noqa: BLE001
        return f"chyba: {e}", 0


def main():
    ok, why = check_integrity()
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "heartbeat.txt"), "w", encoding="utf-8") as f:
        f.write(f"{now()} pid={os.getpid()} integrity={'OK' if ok else 'FAIL'}\n")
    log(f"tick: integrity={'OK' if ok else 'FAIL'} ({why})")
    if not ok:
        return 1
    st, n = scan_repo()
    if st == "ok" and n:
        os.makedirs(os.path.join(STATE), exist_ok=True)
        with open(os.path.join(STATE, "loop_findings.jsonl"), "a", encoding="utf-8") as f:
            f.write(json_now({"ts": now(), "dirty_files": n}) + "\n")
        log(f"repo dirty: {n} suborov")
    else:
        log(f"scan: {st} (dirty=0)")
    return 0


def json_now(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
