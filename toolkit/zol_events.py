#!/usr/bin/env python3
"""zol_events.py — tenký append-only event log + deterministický replay (PRIMA §, orezané).

NIE 28-typový event-sourcing framework (to je pre teba over-engineering). Toto je 90%
hodnoty za 10% práce: jeden JSONL, append-only, jedna emit() funkcia, replay/filter CLI.

Načo: daemony (dream, initiative) robia LLM rozhodnutia na pozadí. Keď zošalejú alebo
navrhnú blbosť, teraz vidíš len výsledok v logu, nie PREČO. Event log = vieš znovu
prehrať postupnosť rozhodnutí jedného behu (run_id) a pochopiť čo sa dialo.

Formát riadku: {"ts","run_id","source","event","data"}
  ts     = ISO čas
  run_id = zoskupí JEDEN beh daemona (napr. jedna nočná konsolidácia) — kľúč replayu
  source = ktorý daemon/skript (dream, initiative, ...)
  event  = typ udalosti (voľný string: "start","llm_call","decision","skip","error","done"...)
  data   = dict s detailmi (prompt snippet, skóre, rozhodnutie, dôvod...)

Použitie ako knižnica:
  from zol_events import emit, new_run
  rid = new_run("dream")                       # vygeneruje run_id
  emit("dream", "start", {"n_atoms": 42}, rid)
  emit("dream", "decision", {"merge": [1,2], "reason": "..."}, rid)

CLI:
  zol_events.py tail [N]                    # posledných N eventov (default 30)
  zol_events.py runs [source]               # zoznam run_id (+počet eventov, čas)
  zol_events.py replay <run_id>             # všetky eventy jedného behu, chronologicky
  zol_events.py grep <substr>               # eventy obsahujúce substring
"""
import os
import sys
import json
import time
import datetime

ROOT = os.path.expanduser("~/zolander")
STATE = os.path.join(ROOT, "state")
LOG = os.path.join(STATE, "events.jsonl")
MAX_DATA_CHARS = 2000  # ochrana: neuloz obri prompt cely, orez (kontext-hygiena)


def new_run(source):
    """Vygeneruj run_id pre jeden beh daemona: <source>-<epoch>-<pid>."""
    return f"{source}-{int(time.time())}-{os.getpid()}"


def emit(source, event, data=None, run_id=None):
    """Append jeden event. Fail-open — logging NIKDY nezhodí volajúci daemon."""
    try:
        os.makedirs(STATE, exist_ok=True)
        rec = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id or "adhoc",
            "source": source,
            "event": event,
            "data": _trim(data if data is not None else {}),
        }
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # event log je diagnostika, nesmie zhodiť beh


def _trim(data):
    """Orež veľké string hodnoty (napr. celý prompt) na MAX_DATA_CHARS."""
    if not isinstance(data, dict):
        return {"value": str(data)[:MAX_DATA_CHARS]}
    out = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > MAX_DATA_CHARS:
            out[k] = v[:MAX_DATA_CHARS] + f"...[orez {len(v)}z]"
        else:
            out[k] = v
    return out


def _load():
    if not os.path.exists(LOG):
        return []
    rows = []
    for ln in open(LOG, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue  # poškodený riadok nezhodí celý replay
    return rows


def cmd_tail(n):
    for r in _load()[-n:]:
        print(f"{r['ts']} [{r['source']}/{r['event']}] run={r['run_id']} {json.dumps(r['data'], ensure_ascii=False)}")


def cmd_runs(source):
    runs = {}
    for r in _load():
        if source and r["source"] != source:
            continue
        rid = r["run_id"]
        if rid not in runs:
            runs[rid] = {"n": 0, "first": r["ts"], "last": r["ts"], "source": r["source"]}
        runs[rid]["n"] += 1
        runs[rid]["last"] = r["ts"]
    for rid, info in sorted(runs.items(), key=lambda x: x[1]["last"], reverse=True):
        print(f"{info['last']} [{info['source']}] run={rid} ({info['n']} eventov, od {info['first']})")


def cmd_replay(run_id):
    evs = [r for r in _load() if r["run_id"] == run_id]
    if not evs:
        print(f"ziadne eventy pre run_id={run_id}")
        return
    print(f"=== REPLAY run={run_id} ({len(evs)} eventov) ===")
    for r in evs:
        print(f"\n{r['ts']} [{r['event']}]")
        for k, v in r["data"].items():
            print(f"    {k}: {json.dumps(v, ensure_ascii=False)}")


def cmd_grep(substr):
    s = substr.lower()
    for r in _load():
        blob = json.dumps(r, ensure_ascii=False).lower()
        if s in blob:
            print(f"{r['ts']} [{r['source']}/{r['event']}] run={r['run_id']} {json.dumps(r['data'], ensure_ascii=False)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "tail":
        cmd_tail(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif cmd == "runs":
        cmd_runs(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "replay":
        cmd_replay(sys.argv[2])
    elif cmd == "grep":
        cmd_grep(sys.argv[2])
    else:
        print(f"neznamy prikaz: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
