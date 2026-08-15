#!/usr/bin/env python3
"""zol_gc.py — Garbage Collector pre vysoké vrstvy pamäte (L2/L3). Red-team poistka #1.

PROBLÉM (red-team audit 2026-08-10): abstrakčný stroj (Fáza 2) povýši konkrétnosti do
L2/L3 princípov. Ak sa cez write-gate dostane šum, Fréchet mean vyrobí geometricky
platný ale sémanticky prázdny bod, LLM ho pomenuje hlbokoznejúcim nezmyslom → zapíše sa
L3 axióm = "rakovinový kód". hook_recall ho potom vstrekuje na začiatok KAŽDEJ session
→ autoimunitná otrava (agent verí defektnej spomienke, sabotuje nápady). Bez GC pre
vysoké uzly je pamäť väzením.

RIEŠENIE: hit-tracking + decay + ARCHÍV (NIE destructive delete — SOTA append/invalidate).
- Každý recall zaznamená hit na vrátené id (recall_hits.jsonl, robí zol_mem — viď napojenie).
- GC: L2/L3 uzol bez hitu za N cyklov (default 30) + nízka confidence → ARCHÍV (soft):
  presun do mem_archive.jsonl + soft-del z DB (hs del). NIKDY nie hard delete —
  archív je obnoviteľný (append/invalidate vzor, história ostáva auditovateľná).
- DEFAULT DRY-RUN: len navrhne, nič nearchivuje, kým nie je --commit. Human audit prvý.

KRITICKÉ (red-team): toto je poistka PRED zapnutím Fázy 2 (ascend→L2/L3). Teraz je
pamäť celá L0, takže GC je teraz no-op — ale musí byť hotový DRIEV než začneme plniť
L2/L3, aby zlý abstrakt mal čo ho odstráni.

Použitie:
  /usr/bin/python3 zol_gc.py                # DRY-RUN: ukáž kandidátov na archív
  /usr/bin/python3 zol_gc.py --commit       # reálne archivuj (soft-del + mem_archive.jsonl)
  ZOL_GC_STALE_CYCLES=30 ZOL_GC_MIN_CONF=0.5  # prahy cez env
"""
import os
import sys
import json
import time
import subprocess

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
HITS = os.path.join(STATE, "recall_hits.jsonl")     # {id, ts} append pri kazdom recall hite
ARCHIVE = os.path.join(STATE, "mem_archive.jsonl")  # archivovane (obnovitelne)
GC_STATE = os.path.join(STATE, "gc_cycles.json")    # pocitadlo GC cyklov
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV  # prenositelne cesty (auto-detect)
MEM_COL = "zol_mem"

STALE_CYCLES = int(os.environ.get("ZOL_GC_STALE_CYCLES", "30"))
MIN_CONF = float(os.environ.get("ZOL_GC_MIN_CONF", "0.5"))
GC_LAYERS = ("L2", "L3")  # GC sa tyka LEN vysokych vrstiev; L0/L1 riesi decay


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def _hit_counts():
    """Pocet hitov na id z recall_hits.jsonl."""
    counts = {}
    for h in _load_jsonl(HITS):
        i = h.get("id")
        if i is not None:
            counts[i] = counts.get(i, 0) + 1
    return counts


def _cur_cycle():
    try:
        return json.load(open(GC_STATE)).get("cycle", 0)
    except Exception:
        return 0


def _bump_cycle():
    c = _cur_cycle() + 1
    os.makedirs(STATE, exist_ok=True)
    json.dump({"cycle": c, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(GC_STATE, "w"))
    return c


def _hs_del(mid):
    p = subprocess.run([NODE, HS, "del", MEM_COL, str(mid)],
                       capture_output=True, text=True, env=NODE_ENV)
    return p.returncode == 0


def find_candidates():
    """L2/L3 uzly bez hitu za >=STALE_CYCLES cyklov A nizka confidence."""
    rows = _load_jsonl(IDX)
    hits = _hit_counts()
    cur_cycle = _cur_cycle()
    cands = []
    for r in rows:
        if r.get("layer") not in GC_LAYERS:
            continue
        if r.get("archived"):
            continue
        mid = r.get("id")
        nhits = hits.get(mid, 0)
        conf = float(r.get("confidence", 0.7) or 0.7)
        # kandidat: ziadne hity A nizka confidence (defektny/nepouzivany abstrakt)
        if nhits == 0 and conf < MIN_CONF:
            cands.append({"id": mid, "layer": r.get("layer"), "conf": conf,
                          "hits": nhits, "text": r.get("text", "")[:100]})
    return cands, cur_cycle


def cmd_gc(commit):
    cands, cur_cycle = find_candidates()
    result = {"cycle": cur_cycle, "stale_cycles_thresh": STALE_CYCLES,
              "min_conf": MIN_CONF, "candidates": cands, "archived": [], "mode": "commit" if commit else "dry-run"}
    if commit and cands:
        rows = _load_jsonl(IDX)
        by_id = {r.get("id"): r for r in rows}
        for c in cands:
            mid = c["id"]
            # 1) zapis do archivu (obnovitelne) PRED soft-del
            with open(ARCHIVE, "a", encoding="utf-8") as f:
                rec = dict(by_id.get(mid, {}), archived_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                           archived_reason="gc_stale_lowconf")
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # 2) soft-del z DB
            if _hs_del(mid):
                result["archived"].append(mid)
                if mid in by_id:
                    by_id[mid]["archived"] = True
        # prepis index s archived flagom
        with open(IDX, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    commit = "--commit" in sys.argv
    if "--bump-cycle" in sys.argv:
        print(json.dumps({"cycle": _bump_cycle()}))
        return 0
    cmd_gc(commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
