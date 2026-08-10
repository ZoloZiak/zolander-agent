#!/usr/bin/env python3
"""zol_tasks.py — durable task registry + cross-session awareness (R2+X1).

JEDEN zdroj pravdy na disku: ~/zolander/state/tasks.json. Rieši dve veci naraz:
- CROSS-SESSION (X1): okná (WhatsApp, CLI) = zberné nádoby. Každé zapíše svoj stav sem;
  Zolander-konsolidátor vie o oboch → na "ako progres na noťase?" odpovie z registry.
- DURABLE (R2): stav úlohy žije MIMO procesu. Keď proces padne (OOM/SIGTERM — dnešný
  loadavg 37), úloha prežije a pokračuje z checkpointu (steps_done), nie od nuly.

Princíp (SOTA durable execution + Vadim idempotencia): stav = riadok v store, nie stack
frame v procese. Krok idempotentný — pri resume "je krok v steps_done? preskoč".

Príkazy (stdlib only, /usr/bin/python3, fail-open, atomický zápis):
  zol_tasks.py list                     # JSON všetkých úloh
  zol_tasks.py show <task_id>
  zol_tasks.py upsert < JSON            # {task_id,title,window,status,progress,next,refs}
  zol_tasks.py step <task_id> "<krok>"  # pridaj hotový krok (checkpoint, idempotentne)
  zol_tasks.py done <task_id> [status]  # označ done|failed|paused
  zol_tasks.py progress                 # ľudský prehľad aktívnych (pre WhatsApp odpoveď)
  zol_tasks.py has-step <task_id> "<krok>"  # exit 0 ak krok už hotový (pre idempot. resume)
"""
import os
import sys
import re
import json
import tempfile
import datetime
import fcntl
import contextlib

ROOT = os.path.expanduser("~/zolander")
STATE = os.path.join(ROOT, "state")
TASKS = os.path.join(STATE, "tasks.json")
LOCK = os.path.join(STATE, ".tasks.lock")
VALID_STATUS = ("running", "paused", "done", "failed")


@contextlib.contextmanager
def _locked():
    """Cross-process exclusive lock okolo read-modify-write. Bez neho 2 procesy
    (CLI + gateway) stratia updaty: A cita, B cita starsi stav, obaja zapisu,
    posledny prepise prveho (lost update — namerane 7/12 pri 12 subehoch).
    fcntl.flock serializuje cely cyklus. Fail-open: ak lock zlyha, bezime bez neho."""
    os.makedirs(STATE, exist_ok=True)
    f = None
    try:
        f = open(LOCK, "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        if f is not None:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _load():
    """Fail-open: chýbajúci/rozbitý súbor -> prázdny register."""
    try:
        with open(TASKS, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("tasks"), dict):
            return d
    except Exception:
        pass
    return {"tasks": {}}


def _save(d):
    """Atomický zápis (.tmp + os.replace) — dve okná môžu písať naraz."""
    os.makedirs(STATE, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE, prefix=".tasks_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, TASKS)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def upsert(obj):
    tid = str(obj.get("task_id") or "").strip()
    if not tid:
        raise ValueError("task_id required")
    with _locked():
        d = _load()
        t = d["tasks"].get(tid, {"steps_done": [], "created": _now()})
        for k in ("title", "window", "status", "progress", "next"):
            if k in obj and obj[k] is not None:
                t[k] = obj[k]
        if "refs" in obj and isinstance(obj["refs"], list):
            t["refs"] = obj["refs"]
        if t.get("status") not in VALID_STATUS:
            t["status"] = "running"
        t.setdefault("steps_done", [])
        t["updated"] = _now()
        d["tasks"][tid] = t
        _save(d)
    return t


# PRIMA §XII poisoned-output guard: pri resume/checkpointe NEoznač otrávený výstup za
# hotový. Otrávený = prázdny, error-shape (traceback/rate-limit/timeout), alebo podozrivo
# krátky na deklarovaný typ. Bez toho by 429-skrátený alebo spadnutý krok prešiel ako
# "converged" a resume by ho preskočil (PRIMA _load_completed_steps).
_ERROR_SHAPES = re.compile(
    r"\b(traceback|rate.?limit|429|timeout|timed out|connection (reset|refused)|"
    r"exception|OOM|killed|SIGTERM|INTEGRITY FAIL|NOT_FOUND|null|undefined)\b",
    re.IGNORECASE)


def _looks_poisoned(result, min_len=20):
    """True = výstup je otrávený/neúplný, NEsmie sa checkpointovať ako hotový."""
    r = (result or "").strip()
    if not r:
        return True
    if len(r) < min_len:            # podozrivo krátke na reálny výstup
        return True
    if _ERROR_SHAPES.search(r):     # nesie stopu zlyhania
        return True
    return False


def step(tid, text, result=None, min_len=20):
    """Pridaj hotový krok — IDEMPOTENTNE (ak už je, nič). Checkpoint pre resume.
    Ak je daný `result`, VALIDUJ ho (poisoned-output guard): otrávený/neúplný výstup
    krok NEoznačí za hotový — vráti {rejected: dôvod}, aby resume vedel pokračovať."""
    text = (text or "").strip()
    if result is not None and _looks_poisoned(result, min_len):
        return {"rejected": "poisoned_output", "task_id": tid, "step": text}
    with _locked():
        d = _load()
        t = d["tasks"].get(tid)
        if t is None:
            raise KeyError(f"neznama uloha: {tid}")
        t.setdefault("steps_done", [])
        if text and text not in t["steps_done"]:
            t["steps_done"].append(text)
            t["updated"] = _now()
            _save(d)
    return t


def has_step(tid, text):
    t = _load()["tasks"].get(tid, {})
    return (text or "").strip() in t.get("steps_done", [])


def set_status(tid, status):
    status = status if status in VALID_STATUS else "done"
    return upsert({"task_id": tid, "status": status})


def progress():
    """Ľudský prehľad AKTÍVNych úloh (pre 'ako progres / čo beží')."""
    d = _load()
    active = [(tid, t) for tid, t in d["tasks"].items()
              if t.get("status") in ("running", "paused")]
    if not active:
        return "Ziadne aktivne ulohy."
    lines = []
    for tid, t in sorted(active, key=lambda x: x[1].get("updated", ""), reverse=True):
        w = t.get("window", "?")
        st = t.get("status", "?")
        pr = t.get("progress", "")
        nx = t.get("next", "")
        nsteps = len(t.get("steps_done", []))
        line = f"[{w}/{st}] {t.get('title', tid)} — {pr} ({nsteps} krokov hotovych)"
        if nx:
            line += f" | dalej: {nx}"
        lines.append(line)
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    try:
        if cmd == "list":
            print(json.dumps(_load(), ensure_ascii=False, indent=1))
        elif cmd == "show":
            t = _load()["tasks"].get(sys.argv[2])
            print(json.dumps(t, ensure_ascii=False, indent=1) if t else "null")
        elif cmd == "upsert":
            obj = json.loads(sys.stdin.read() or "{}")
            print(json.dumps(upsert(obj), ensure_ascii=False, indent=1))
        elif cmd == "step":
            # step <id> <text> [result]  — ak je result daný, poisoned-output guard ho overí
            result = sys.argv[4] if len(sys.argv) > 4 else None
            print(json.dumps(step(sys.argv[2], sys.argv[3], result), ensure_ascii=False, indent=1))
        elif cmd == "has-step":
            return 0 if has_step(sys.argv[2], sys.argv[3]) else 1
        elif cmd == "done":
            status = sys.argv[3] if len(sys.argv) > 3 else "done"
            print(json.dumps(set_status(sys.argv[2], status), ensure_ascii=False, indent=1))
        elif cmd == "progress":
            print(progress())
        else:
            print(f"neznamy prikaz: {cmd}", file=sys.stderr)
            return 2
    except Exception as e:
        print(f"CHYBA: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
