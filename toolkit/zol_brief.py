#!/usr/bin/env python3
"""zol_brief.py — ranny "zijem" brief Zolandera (bod 2).

Spusta launchd raz denne (8:00). Zozbiera REALNY stav z logov/suborov a posle
jednu strucnu spravu cez zolander_notify.py. Ziadne vymyslanie aktivity —
len fakty z disku. Fail-open (nikdy nezhodi daemon).

Zdroje faktov:
  - state/heartbeat.txt        -> zije loop? kedy naposledy tikol
  - logs/loop.log              -> pocet tickov za poslednych 24h + integrity faily
  - denniky/brief_<dnes>.md    -> vysledok nocneho dream cyklu (ak bol)
  - DB :50051 (TCP)            -> je pamat dostupna?
  - integrity.py check         -> sedi identita?
"""
import os
import sys
import socket
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
DENNIKY = os.path.join(ROOT, "denniky")
HEARTBEAT = os.path.join(STATE, "heartbeat.txt")
LOOPLOG = os.path.join(LOGS, "loop.log")
NOTIFY = os.path.join(ROOT, "toolkit", "zolander_notify.py")
INTEGRITY = os.path.join(ROOT, "toolkit", "integrity.py")
PYBIN = "/usr/bin/python3"


def now():
    return datetime.datetime.now()


def read_heartbeat_age_min():
    """Vek posledneho heartbeatu v minutach, alebo None ak sa neda precitat."""
    try:
        import json
        with open(HEARTBEAT, encoding="utf-8") as f:
            hb = json.load(f)
        epoch = float(hb.get("epoch", 0))
        if epoch <= 0:
            return None
        return (now().timestamp() - epoch) / 60.0
    except Exception:
        return None


def count_ticks_24h():
    """Pocet 'tick OK' riadkov v loop.log za poslednych 24h + posledny integrity fail."""
    ok = 0
    fails = 0
    cutoff = now() - datetime.timedelta(hours=24)
    try:
        with open(LOOPLOG, encoding="utf-8") as f:
            for line in f:
                ts_str = line[:19]
                try:
                    ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                if "tick OK" in line:
                    ok += 1
                elif "INTEGRITY FAIL" in line:
                    fails += 1
    except FileNotFoundError:
        pass
    return ok, fails


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
        return None  # neznamy stav


def dream_summary():
    """Prva sekcia dnesneho ranneho briefu (dream vysledok), ak existuje."""
    fname = os.path.join(DENNIKY, f"brief_{now():%Y-%m-%d}.md")
    if not os.path.exists(fname):
        return None
    try:
        lines = []
        with open(fname, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("*") or s.startswith("---"):
                    continue
                lines.append(s)
                if len(lines) >= 3:
                    break
        return " ".join(lines) if lines else None
    except Exception:
        return None


def build_message():
    parts = ["Zolander ranny brief"]

    # loop / heartbeat
    age = read_heartbeat_age_min()
    if age is None:
        parts.append("- loop: NEZNAMY (heartbeat sa neda precitat)")
    elif age > 45:
        parts.append(f"- loop: STOJI? posledny tep pred {age:.0f} min")
    else:
        parts.append(f"- loop: OK (tep pred {age:.0f} min)")

    ok, fails = count_ticks_24h()
    tick_line = f"- za 24h: {ok} tickov"
    if fails:
        tick_line += f", {fails} integrity failov"
    parts.append(tick_line)

    # DB
    parts.append("- pamat (DB): OK" if db_up() else "- pamat (DB): DOLE (:50051 neodpovedá)")

    # integrity
    ig = integrity_ok()
    if ig is True:
        parts.append("- identita: OK")
    elif ig is False:
        parts.append("- identita: MISMATCH (treba re-baseline)")
    else:
        parts.append("- identita: NEZNAMA")

    # dream
    d = dream_summary()
    parts.append(f"- sen: {d}" if d else "- sen: bez novej konsolidacie")

    return "\n".join(parts)


def main():
    msg = build_message()
    try:
        subprocess.run([PYBIN, NOTIFY, "--subject", "ranny brief", msg],
                       timeout=90, cwd=ROOT)
    except Exception:
        # fail-open: aspon vypis, launchd to da do log suboru
        print(msg)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"BRIEF EXCEPTION: {exc!r}", file=sys.stderr)
        sys.exit(0)
