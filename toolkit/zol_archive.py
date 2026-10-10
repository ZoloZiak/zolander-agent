#!/usr/bin/env python3
"""zol_archive.py — presun retired epizod z ziveho indexu do archivu (moznost B).

PRECO (namerane 2026-09-26): dormant/retired epizody ostavaju v mem_index.jsonl, ktory
BM25 (mem_lexical.load_corpus) cita pri KAZDOM recalle. Rast korpusu 318->2437 zrazil
BM25 R@1 0.83->0.58. Moznost A (dormant filter v recalle) ich uz SKRYVA z vysledkov, ale
subor fyzicky rastie a load je O(n). Tento nastroj (moznost B) ich presunie do
mem_archive.jsonl + soft-del z DB, cim horuci index natrvalo odlahci.

BEZPECNOST (vsetko cannot-violate):
- DRY-RUN DEFAULT: bez --apply len vypise plan, NIC nezmeni.
- REVERZIBILNE: cely record -> mem_archive.jsonl; zmazane hrany -> mem_edges_trash.jsonl
  (cez zol_graph.detach trash_path); zmazany bod -> dedup_trash.jsonl (mem_store trash_rec).
  Obnova: `zol_archive.py restore <id...>` (vrati do indexu+grafu, sync() re-embedne do DB).
- ORPHAN-SAFE: pred kazdym soft-del zavola zol_graph.detach -> hrany prec s trash stopou.
  Bez toho by 279/283 dormant uzlov nechalo ~1623 висiacich hran (lekcia id=1078).
- IDEMPOTENTNE: druhy beh na uz archivovanom ID = no-op.

KANDIDATI (default): forget_state in {retired_candidate, retired}. Volitelne --dormant-age N
prida aj dormant epizody starsie nez N dni (na jednorazove upratanie existujucich 283).
Retired prah v decay: >60d & salience<0.05 & episodic. NEMENI decay politiku — len zbiera
to, co decay uz oznacil.
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import ZROOT  # noqa: E402

STATE = os.path.join(ZROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
ARCHIVE = os.path.join(STATE, "mem_archive.jsonl")
EDGE_TRASH = os.path.join(STATE, "mem_edges_trash.jsonl")

RETIRED_STATES = {"retired_candidate", "retired"}


def _load_idx(path=None):
    path = path or IDX
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _age_days(rec, now=None):
    now = now or time.time()
    ts = (rec.get("ts") or "")[:19]
    try:
        return (now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 86400.0
    except Exception:
        return -1.0


def select_candidates(rows, dormant_age=None, now=None):
    """Vrat zoznam recordov na archivaciu.

    Default: forget_state retired/retired_candidate. dormant_age=N: prida dormant
    epizody starsie nez N dni (salience uz je ~0, decay ich odlozil).
    """
    out = []
    for r in rows:
        fs = r.get("forget_state", "active")
        if fs in RETIRED_STATES:
            out.append(r)
        elif dormant_age is not None and fs == "dormant" and _age_days(r, now) >= dormant_age:
            out.append(r)
    return out


def _append_jsonl(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _already_archived():
    ids = set()
    if os.path.exists(ARCHIVE):
        for line in open(ARCHIVE, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line).get("id"))
                except Exception:
                    pass
    return ids


def archive(candidates, apply=False, delete_fn=None, detach_fn=None):
    """Archivuj kandidatov. apply=False (default) = dry-run, nic sa nezmeni.

    delete_fn/detach_fn: injekcia pre test (default zapoji zive mem_store/zol_graph).
    Poradie na kazdom uzle: (1) zapis cely record do ARCHIVE (reverzibilita PRVA),
    (2) detach hran -> EDGE_TRASH, (3) mem_store.delete(remove_index=True, trash_rec).
    """
    done = _already_archived()
    plan = [r for r in candidates if r.get("id") not in done]
    stats = {"selected": len(candidates), "already": len(candidates) - len(plan),
             "to_archive": len(plan), "edges_removed": 0, "db_deleted": 0, "applied": apply}

    if not apply:
        stats["sample"] = [(r.get("id"), r.get("forget_state"),
                            (r.get("text") or "")[:60]) for r in plan[:10]]
        return stats

    # lenivy import zivych zavislosti az v apply vetve (dry-run nepotrebuje DB/graf)
    if delete_fn is None:
        import mem_store
        delete_fn = lambda mid, rec: mem_store.delete(  # noqa: E731
            mid, remove_index=True, trash_rec=rec, reason="archive")
    if detach_fn is None:
        import zol_graph
        detach_fn = lambda mid: zol_graph.detach(mid, trash_path=EDGE_TRASH)  # noqa: E731

    for r in plan:
        mid = r.get("id")
        _append_jsonl(ARCHIVE, dict(r, _archived_ts=time.strftime("%Y-%m-%dT%H:%M:%S")))
        d = detach_fn(mid) or {}
        stats["edges_removed"] += d.get("removed", 0)
        delete_fn(mid, r)
        stats["db_deleted"] += 1
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Archivuj retired/dormant epizody (reverzibilne).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_plan = sub.add_parser("plan", help="dry-run: vypis co by sa archivovalo")
    p_plan.add_argument("--dormant-age", type=int, default=None,
                        help="prida dormant epizody starsie nez N dni")
    p_apply = sub.add_parser("apply", help="VYKONAJ archivaciu (nezvratne bez restore)")
    p_apply.add_argument("--dormant-age", type=int, default=None)
    p_apply.add_argument("--yes", action="store_true", help="povinne potvrdenie")
    args = ap.parse_args(argv)

    rows = _load_idx()
    cands = select_candidates(rows, dormant_age=getattr(args, "dormant_age", None))

    if args.cmd == "plan":
        st = archive(cands, apply=False)
        print(json.dumps(st, ensure_ascii=False, indent=2))
    elif args.cmd == "apply":
        if not args.yes:
            print("ODMIETNUTE: apply vyzaduje --yes (nezvratne bez restore).")
            return 2
        st = archive(cands, apply=True)
        print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
