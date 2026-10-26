#!/usr/bin/env python3
"""zol_watchdog_port.py — watchdog servera + dual pamati (one-shot na tick).

Tick:
  1. zol_mem_text.py health -> gRPC 50051 zivy?
  2. ak server padnuty -> pokus o restart (wsl server, pozadi); log
  3. kontrola state/zol_memory.jsonl existuje
  4. zapis state/watchdog.log

Cisto stdlib + subprocess. Deaktivne akcje len restartupovacie (nie mazanie).
"""
import datetime
import os
import subprocess
import sys

ROOT = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "logs")
WSL_START = "wsl -d Ubuntu --cd /home/zolo/hyperspace-db-401 -- /home/zolo/hyperspace-db-401/target/release/hyperspace-server"


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "watchdog.log"), "a", encoding="utf-8") as f:
        f.write(f"{now()} | {msg}\n")


def server_alive():
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "toolkit", "zol_mem_text.py"), "health"],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=60,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return '"ok": true' in out, out[-200:].replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def main():
    os.makedirs(os.path.join(ROOT, "state"), exist_ok=True)
    mempath = os.path.join(ROOT, "state", "zol_memory.jsonl")
    mem_ok = os.path.exists(mempath)
    alive, detail = server_alive()

    if not mem_ok:
        log("VYSTRANA: state/zol_memory.jsonl neexistuje (A pamat prazdna; nezalamuj — dual degraduje)")

    if alive:
        log(f"OK: server zivy ({'A mem ' + ('ok' if mem_ok else 'TESNE')})")
        return 0

    log(f"PAD: server nedostupny ({detail}) — pokusam restart")
    try:
        subprocess.Popen(["wsl", "-d", "Ubuntu", "--cd",
                          "/home/zolo/hyperspace-db-401", "--",
                          "/home/zolo/hyperspace-db-401/target/release/hyperspace-server"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        log("restart odposlany (dokonci sa sam; health pri dalsom ticku)")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"restart zlyhal: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
