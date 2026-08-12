#!/usr/bin/env python3
"""zol_watchdog.py — infra-poistka Zolandera (bod 1, zuzeny).

Spusta launchd 1x za hodinu. Skontroluje IBA infra-zdravie, ktore ziva gateway
NEPOKRYJE: (1) loop stoji, (2) DB dole, (3) integrity mismatch. Ked je vsetko OK,
je TICHO (nic neposle). Ked nieco spadne, posle 1 spravu cez zolander_notify.py.

ANTI-SPAM: dedup cez state/watchdog_ledger.txt — ten isty problem posle len RAZ,
kym sa stav nevrati do OK (potom sa ledger vymaze a pri dalsom vypadku znova upozorni).
Ziadne initiative/dream hlasenie — to riesi gateway + ranny brief (bez duplicity).
Fail-open: nikdy nezhodi daemon.
"""
import os
import sys
import json
import socket
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
HEARTBEAT = os.path.join(STATE, "heartbeat.txt")
LEDGER = os.path.join(STATE, "watchdog_ledger.txt")
NOTIFY = os.path.join(ROOT, "toolkit", "zolander_notify.py")
INTEGRITY = os.path.join(ROOT, "toolkit", "integrity.py")
PYBIN = "/usr/bin/python3"

HEARTBEAT_MAX_MIN = 45  # loop tika kazdych 20 min -> 45 min ticha = problem


def now():
    return datetime.datetime.now()


def heartbeat_age_min():
    try:
        with open(HEARTBEAT, encoding="utf-8") as f:
            hb = json.load(f)
        epoch = float(hb.get("epoch", 0))
        if epoch <= 0:
            return None
        return (now().timestamp() - epoch) / 60.0
    except Exception:
        return None


def db_up(host="127.0.0.1", port=50051, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def integrity_ok():
    try:
        p = subprocess.run([PYBIN, INTEGRITY, "check"],
                           capture_output=True, text=True, timeout=30, cwd=ROOT)
        return p.returncode == 0
    except Exception:
        return None


def load_ledger():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return set(x.strip() for x in f if x.strip())
    except FileNotFoundError:
        return set()


def save_ledger(active):
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(LEDGER, "w", encoding="utf-8") as f:
            for k in sorted(active):
                f.write(k + "\n")
    except Exception:
        pass


def notify(msg):
    try:
        # watchdog = nieco hori -> vyrazny zvuk (desktop banner cez zolander_notify)
        subprocess.run([PYBIN, NOTIFY, "--subject", "watchdog ALERT",
                        "--sound", "Sosumi", msg],
                       timeout=90, cwd=ROOT)
    except Exception:
        print(msg)


def main():
    problems = {}  # kluc -> text

    age = heartbeat_age_min()
    if age is None:
        problems["loop"] = "loop: heartbeat sa neda precitat (mozno stoji)"
    elif age > HEARTBEAT_MAX_MIN:
        problems["loop"] = f"loop STOJI: posledny tep pred {age:.0f} min"

    if not db_up():
        problems["db"] = "pamat (HyperspaceDB :50051) je DOLE — recall nefunguje"

    ig = integrity_ok()
    if ig is False:
        problems["integrity"] = "integrity MISMATCH — identita nesedi, loop je fail-closed. Treba re-baseline."

    prev = load_ledger()
    active = set(problems.keys())

    # posli len NOVE problemy (co v ledgeri este neboli)
    new = active - prev
    if new:
        lines = ["Zolander infra-poistka nasla problem:"]
        lines += [f"- {problems[k]}" for k in sorted(new)]
        notify("\n".join(lines))

    # ak sa nieco vratilo do OK, uvolni to z ledgera (aby dalsi vypadok znova upozornil)
    save_ledger(active)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"WATCHDOG EXCEPTION: {exc!r}", file=sys.stderr)
        sys.exit(0)
