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
ROOT = os.path.join(HOME, "projects", "zolander")
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


def last_tick_age_min():
    """Vek posledneho 'tick OK' riadku v loop.log v minutach, alebo None.
    Krizova kontrola k heartbeatu: po prebudeni Macu sa launchd brief job moze
    spustit skor nez loop stihne tiknut -> heartbeat je stale, ale loop realne
    zije. Preto pred poplachom overime aj cerstvost posledneho ticku."""
    last_ts = None
    try:
        with open(LOOPLOG, encoding="utf-8") as f:
            for line in f:
                if "tick OK" not in line:
                    continue
                try:
                    last_ts = datetime.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
    except FileNotFoundError:
        return None
    if last_ts is None:
        return None
    return (now() - last_ts).total_seconds() / 60.0


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


def _section_bullets(all_lines, header_substr):
    """Vytiahne '- ...' odrazky pod nadpisom '## ...' co obsahuje header_substr.
    Konci pri dalsom '## ' nadpise alebo '---'."""
    out = []
    grabbing = False
    for line in all_lines:
        s = line.rstrip("\n")
        st = s.strip()
        if st.startswith("## "):
            grabbing = header_substr.lower() in st.lower()
            continue
        if not grabbing:
            continue
        if st.startswith("---"):
            break
        if st.startswith("- "):
            out.append(st[2:].strip())
    return out


def dream_summary():
    """Obsah dnesneho dream cyklu: nove abstrakty (rebrik) + dedup-merge + pocet
    forget-navrhov. Vracia zoznam riadkov (uz s '- ' prefixom pre WhatsApp), alebo
    None ak denny brief neexistuje. Cita REALNY obsah z denniky/brief_<dnes>.md."""
    fname = os.path.join(DENNIKY, f"brief_{now():%Y-%m-%d}.md")
    if not os.path.exists(fname):
        return None
    try:
        with open(fname, encoding="utf-8") as f:
            all_lines = f.readlines()
    except Exception:
        return None

    out = []

    # nove abstrakty (rebrik / F8)
    absts = _section_bullets(all_lines, "rebr")
    absts = [a for a in absts if "nič" not in a.lower() and "nic" not in a.lower()]
    for a in absts:
        out.append(f"- sen/abstrakt: {a}")

    # dedup-merge (obsah, nie len pocet)
    merges = _section_bullets(all_lines, "Dedup")
    if merges:
        out.append(f"- sen/dedup: zlucenych {len(merges)} duplikatov:")
        for m in merges:
            short = m if len(m) <= 100 else m[:97] + "..."
            out.append(f"   • {short}")

    # forget-navrhy: len pocet (nezaplav mobil zoznamom idciek)
    forgets = _section_bullets(all_lines, "zabudnut")
    if forgets:
        out.append(f"- sen/forget: {len(forgets)} navrhov na zabudnutie caka na tvoj audit "
                   f"(detail v denniky/brief_{now():%Y-%m-%d}.md)")

    return out if out else None


def build_message():
    parts = ["Zolander ranny brief"]

    # loop / heartbeat
    age = read_heartbeat_age_min()
    if age is None:
        parts.append("- loop: NEZNAMY (heartbeat sa neda precitat)")
    elif age > 45:
        # Krizova kontrola: po prebudeni Macu je heartbeat stale, ale loop moze
        # realne zit. Ak posledny 'tick OK' je cerstvy (<45 min), nie je to vypadok
        # ale len wake-up race medzi launchd jobmi -> nehlas falosny poplach.
        tick_age = last_tick_age_min()
        if tick_age is not None and tick_age <= 45:
            parts.append(f"- loop: OK (tick pred {tick_age:.0f} min; heartbeat stale "
                         f"{age:.0f} min — Mac spal, launchd dobehol po prebudeni)")
        else:
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
    if d:
        parts.extend(d)
    else:
        parts.append("- sen: bez novej konsolidacie")

    return "\n".join(parts)


def main():
    msg = build_message()
    report = os.path.join(DENNIKY, f"brief_{now():%Y-%m-%d}.md")
    cmd = [PYBIN, NOTIFY, "--subject", "ranny brief"]
    if os.path.exists(report):
        cmd += ["--report", report]
    # ranny brief: bez zvuku (nema budit) — desktop banner ticho
    cmd += [msg]
    try:
        subprocess.run(cmd, timeout=90, cwd=ROOT)
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
