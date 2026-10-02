#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
masterplan_check.py — auto-check životného masterplanu (Zolander).

Recuris princíp (toolkit-runbook): cieľ je "hotový" LEN keď to potvrdí OBSERVÁCIA,
nie keď to niekto tvrdí. Tento skript overí 'evidence' spec každého auto-checku v
life.json proti REALITE na disku (dir/file/mtime/git), nastaví 'done', prepočíta
vážené %, prekreslí dashboard a vráti report pre ranný brief.

- stdlib only, /usr/bin/python3 (žiaden venv netreba).
- shell-safe: subprocess VŽDY argv list, shell=False.
- FAIL-CLOSED na dôkaze: keď sa evidence nedá overiť (chýba cesta, git zlyhá,
  neznámy typ) -> check NEzozelenie (radšej false-nezelený než falošne hotový).
- Len auto:True checky sa dotýka. Manuálne (ty) checky NIKDY nemení.
- Idempotentné: beh 2× dá ten istý výsledok.

CLI:
  masterplan_check.py run      # over + zapíš life.json + prekresli dashboard
  masterplan_check.py dry      # over + vypíš, NIČ nezapíš
  masterplan_check.py report   # text report (pre ranný brief / notify)
"""
import os, sys, json, time, glob, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
_ZROOT = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(ROOT)
MP_DIR = os.path.join(os.path.expanduser(_ZROOT), "state", "masterplan")
LIFE = os.path.join(MP_DIR, "life.json")
DASH = os.path.join(MP_DIR, "dashboard.html")
STATE = os.path.join(MP_DIR, "autocheck_state.json")  # audit stopa zmien
NOW = time.time()

_SKIP_DIRS = {".git", "node_modules", ".venv", ".next", "__pycache__", "venv",
              ".venv-yar", ".pytest_cache", "dist", "build"}
_REL_EXT = (".py", ".js", ".ts", ".tsx", ".json", ".md", ".csv", ".txt", ".yaml", ".yml")


def _run(cmd, timeout=20):
    """argv list, shell=False (sandbox). Vrati (rc, out) alebo (None, err)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return None, str(e)


def _newest_age_days(path):
    """Vek (dni) najnovšieho relevantného súboru v strome. None ak nič/neexistuje."""
    if not os.path.isdir(path):
        # samostatny subor?
        if os.path.isfile(path):
            return (NOW - os.path.getmtime(path)) / 86400.0
        return None
    newest = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if f.endswith(_REL_EXT):
                try:
                    m = os.path.getmtime(os.path.join(root, f))
                    if m > newest:
                        newest = m
                except OSError:
                    continue
    return (NOW - newest) / 86400.0 if newest else None


# ---- evidence overovace: vracia (bool_pass, detail_str) -------------------
def ev_dir_exists(ev):
    p = os.path.expanduser(ev["path"])
    return os.path.isdir(p), ("existuje" if os.path.isdir(p) else "chýba: " + p)


def ev_file_exists(ev):
    p = os.path.expanduser(ev["path"])
    return os.path.isfile(p), ("existuje" if os.path.isfile(p) else "chýba: " + p)


def ev_recent_activity(ev):
    p = os.path.expanduser(ev["path"])
    days = float(ev.get("days", 30))
    age = _newest_age_days(p)
    if age is None:
        return False, "žiadna aktivita / cesta chýba"
    return (age <= days), f"najnovší pred {age:.1f}d (prah {days:.0f}d)"


def ev_git_recent(ev):
    repo = os.path.expanduser(ev["repo"])
    days = float(ev.get("days", 30))
    if not os.path.isdir(os.path.join(repo, ".git")):
        return False, "nie je git repo"
    rc, out = _run(["git", "-C", repo, "log", "-1", "--format=%ct"])
    if rc != 0 or not out.strip().isdigit():
        return False, "git log zlyhal"  # fail-closed
    age = (NOW - int(out.strip())) / 86400.0
    return (age <= days), f"posledný commit pred {age:.1f}d (prah {days:.0f}d)"


def ev_file_glob(ev):
    base = os.path.expanduser(ev["path"])
    pat = ev["pattern"].lower()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            name = f.lower()
            # jednoduchy *substr* glob
            core = pat.strip("*")
            if core in name:
                return True, "našiel: " + os.path.join(root, f).replace(base + "/", "")
    return False, f"nenašiel vzor '{ev['pattern']}' v {base}"


_EV = {
    "dir_exists": ev_dir_exists, "file_exists": ev_file_exists,
    "recent_activity": ev_recent_activity, "git_recent": ev_git_recent,
    "file_glob": ev_file_glob,
}


def verify_evidence(ev):
    fn = _EV.get(ev.get("kind"))
    if fn is None:
        return False, f"neznámy typ dôkazu: {ev.get('kind')}"  # fail-closed
    try:
        return fn(ev)
    except Exception as e:
        return False, f"chyba overenia: {e}"  # fail-closed


def phase_pct(p):
    d = t = 0
    for o in p.get("objectives", []):
        ow = o.get("weight", 1)
        for c in o.get("checks", []):
            w = c.get("weight", 1) * ow
            t += w
            if c.get("done"):
                d += w
    return (round(d / t * 100) if t else 0)


def run(write=True):
    life = json.load(open(LIFE, encoding="utf-8"))
    changes = []  # (phase, obj, label, old, new, detail)
    results = []
    for p in life["phases"]:
        for o in p.get("objectives", []):
            for c in o.get("checks", []):
                if not c.get("auto"):
                    continue
                ev = c.get("evidence")
                if not ev:
                    results.append((p["id"], o["id"], c["label"], None, "BEZ dôkazu"))
                    continue
                passed, detail = verify_evidence(ev)
                old = bool(c.get("done"))
                if old != passed:
                    changes.append((p["id"], o["id"], c["label"], old, passed, detail))
                c["done"] = passed
                c["evidence_last"] = {"pass": passed, "detail": detail,
                                      "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
                results.append((p["id"], o["id"], c["label"], passed, detail))

    pcts = {p["id"]: phase_pct(p) for p in life["phases"]}
    life["updated"] = time.strftime("%Y-%m-%d")
    life.setdefault("meta", {})["last_autocheck"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    if write:
        _atomic_json(LIFE, life)
        _redraw_dashboard(life)
        _atomic_json(STATE, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "changes": [list(x) for x in changes], "pcts": pcts})
    return life, results, changes, pcts


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _redraw_dashboard(life):
    """Nahradí inline 'const D = {...};' v dashboard.html novým life.json."""
    if not os.path.isfile(DASH):
        return False
    html = open(DASH, encoding="utf-8").read()
    marker = "const D = "
    end_marker = ";\nfunction opDone"
    if marker not in html or end_marker not in html:
        return False
    s = html.index(marker) + len(marker)
    e = html.index(end_marker)
    new = html[:s] + json.dumps(life, ensure_ascii=False) + html[e:]
    tmp = DASH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DASH)
    return True


def report(life=None, changes=None, pcts=None):
    if life is None or pcts is None:
        life, _, changes, pcts = run(write=False)
    changes = changes or []
    lines = ["🎯 Masterplan auto-check:"]
    for p in life["phases"]:
        auto = [c for o in p.get("objectives", []) for c in o.get("checks", []) if c.get("auto")]
        done = [c for c in auto if c.get("done")]
        if auto:
            lines.append(f"  {p['evo']} {p['id']}: {pcts.get(p['id'],0)}%  ({len(done)}/{len(auto)} auto-checkov zelených)")
    if changes:
        lines.append("  Δ zmeny:")
        for ph, ob, lab, old, new, det in changes:
            arrow = "✅ zelený" if new else "⬜ zhasol"
            lines.append(f"    {arrow}: {lab[:48]} — {det}")
    else:
        lines.append("  (žiadna zmena oproti minulému behu)")
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dry"
    if cmd == "run":
        life, results, changes, pcts = run(write=True)
        print(report(life, changes, pcts))
    elif cmd == "report":
        print(report())
    else:  # dry
        life, results, changes, pcts = run(write=False)
        for ph, oid, lab, passed, det in results:
            mark = "✅" if passed else ("⬜" if passed is False else "⚠️")
            print(f"{mark} [{ph}] {lab[:50]:50} {det}")
        print("\n--- % per fáza (dry, nezapísané) ---")
        for pid, v in pcts.items():
            print(f"  {pid}: {v}%")
        print("\n" + report(life, changes, pcts))
