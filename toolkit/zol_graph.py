#!/usr/bin/env python3
"""zol_graph.py — memory-to-memory linky + bitemporalnost nad Lorentz pamatou.

JEDNA struktura nesie VZTAH aj CAS (dohoda s veduckom 2026-08-14): namiesto
paralelneho knowledge grafu (Zep) navesime hrany priamo na existujuce zol_mem zaznamy.

Hrany su append-only JSONL (state/mem_edges.jsonl), lebo:
  - mem_index.jsonl je per-zaznam (decay/BM25 korpus), nie na relacie,
  - DB nema nativne hranovy typ, ale Lorentz geometria UZ kóduje hierarchiu vzdialenostou.

Typy hran (edge):
  parent      A -> B : B je NADRADENY koncept (abstrakcia). Hierarchia pre nadhlad.
  supersedes  A -> B : A NAHRADZA B (novsi fakt). B dostane valid_until = ts(A).
                       Bitemporalnost: fakt sa NEMAZE decayom, ale oznaci "uz neplatil od X".
  related     A -> B : asociacia (net, oба smery volne).

Bitemporalne polia zaznamu (v state/mem_temporal.jsonl, sidecar k mem_index):
  {id, valid_from, valid_until (null=stale plati), superseded_by (id|null)}

CLI:
  zol_graph.py link <from_id> <edge> <to_id>       # pridaj hranu
  zol_graph.py supersede <new_id> <old_id>         # new nahradza old (link + valid_until)
  zol_graph.py neighbors <id> [edge]               # susedia (volitelne filter typu)
  zol_graph.py subtree <id> [depth]                # strom nadradenych (parent hrany)
  zol_graph.py active <id>                          # plati zaznam este? (bitemporal)
  zol_graph.py stats                                # pocty hran/typov
Bezi pod /usr/bin/python3 (stdlib, ziadny model). fcntl lock proti cross-process race.
"""
import os
import sys
import json
import time
import fcntl

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
TEMPORAL = os.path.join(STATE, "mem_temporal.jsonl")
EDGE_TYPES = ("parent", "supersedes", "related")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _append(path, obj):
    os.makedirs(STATE, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def _read(path):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def link(a, b, edge, meta=None):
    if edge not in EDGE_TYPES:
        raise SystemExit(f"neznamy typ hrany: {edge} (z {EDGE_TYPES})")
    e = {"from": a, "to": b, "edge": edge, "ts": _now()}
    if meta:
        e["meta"] = meta
    _append(EDGES, e)
    return e


def _set_temporal(mid, **fields):
    """Append temporalny zapis (posledny vyhrava pri citani)."""
    rec = {"id": mid, "ts": _now()}
    rec.update(fields)
    _append(TEMPORAL, rec)
    return rec


def _temporal_state():
    """Zluc temporalne zaznamy: pre kazde id posledny stav."""
    st = {}
    for r in _read(TEMPORAL):
        mid = r.get("id")
        if mid is None:
            continue
        cur = st.setdefault(mid, {"id": mid, "valid_from": None,
                                  "valid_until": None, "superseded_by": None})
        for k in ("valid_from", "valid_until", "superseded_by"):
            if k in r:
                cur[k] = r[k]
    return st


def supersede(new_id, old_id):
    """new_id nahradza old_id: pridaj supersedes hranu + old dostane valid_until=teraz."""
    link(new_id, old_id, "supersedes")
    now = _now()
    _set_temporal(old_id, valid_until=now, superseded_by=new_id)
    _set_temporal(new_id, valid_from=now, valid_until=None)
    return {"superseded": old_id, "by": new_id, "at": now}


def neighbors(mid, edge=None):
    out = []
    for e in _read(EDGES):
        if e.get("from") == mid and (edge is None or e.get("edge") == edge):
            out.append({"dir": "out", **e})
        elif e.get("to") == mid and (edge is None or e.get("edge") == edge):
            out.append({"dir": "in", **e})
    return out


def subtree(mid, depth=3):
    """Vystup nadradenych konceptov (parent hrany) do hlbky — strom pre nadhlad."""
    edges = _read(EDGES)
    parents = {}
    for e in edges:
        if e.get("edge") == "parent":
            parents.setdefault(e["from"], []).append(e["to"])
    out = []
    seen = set()

    def walk(x, d):
        if d > depth or x in seen:
            return
        seen.add(x)
        for p in parents.get(x, []):
            out.append({"child": x, "parent": p, "depth": d})
            walk(p, d + 1)
    walk(mid, 1)
    return out


def is_active(mid):
    """Plati zaznam este (bitemporal)? Vrat (active, temporal_info)."""
    st = _temporal_state().get(mid)
    if not st or st.get("valid_until") is None:
        return True, st
    return False, st


def stats():
    edges = _read(EDGES)
    by_type = {}
    for e in edges:
        by_type[e.get("edge", "?")] = by_type.get(e.get("edge", "?"), 0) + 1
    temporal = _temporal_state()
    superseded = sum(1 for v in temporal.values() if v.get("valid_until"))
    return {"edges_total": len(edges), "by_type": by_type,
            "temporal_records": len(temporal), "superseded": superseded}


def main():
    a = sys.argv[1:]
    if not a:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
        return 0
    cmd = a[0]
    if cmd == "link" and len(a) >= 4:
        print(json.dumps(link(int(a[1]), int(a[3]), a[2]), ensure_ascii=False))
    elif cmd == "supersede" and len(a) >= 3:
        print(json.dumps(supersede(int(a[1]), int(a[2])), ensure_ascii=False))
    elif cmd == "neighbors" and len(a) >= 2:
        print(json.dumps(neighbors(int(a[1]), a[2] if len(a) > 2 else None),
                         ensure_ascii=False, indent=2))
    elif cmd == "subtree" and len(a) >= 2:
        print(json.dumps(subtree(int(a[1]), int(a[3]) if len(a) > 3 else 3),
                         ensure_ascii=False, indent=2))
    elif cmd == "active" and len(a) >= 2:
        act, info = is_active(int(a[1]))
        print(json.dumps({"id": int(a[1]), "active": act, "temporal": info}, ensure_ascii=False))
    elif cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    else:
        raise SystemExit(f"neznamy prikaz/argumenty: {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
