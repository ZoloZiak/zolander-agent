#!/usr/bin/env python3
"""IBIA backfill: doplň `source` (+project) do mem_index.jsonl z DB meta.

DB `zol_mem` meta `source` DRŽÍ (migrated_4to1/writeback/loop/session/...), ale index
ho historicky nezapisoval. Tento skript pre každý index-riadok bez `source`:
  1) self-query cez search bridge (VRACIA meta; getPoints halucí) -> match podľa id -> vezmi meta.source
  2) fallback ak DB nevráti: audit stopa (events.jsonl initiative, seed skript markery)
  3) inak: 'unknown-legacy' (ŽIADNA halucinácia, ŽIADNY LLM)

Default DRY-RUN (nič nezapíše, vypíše plán + rozloženie zdrojov). Zápis až s `--commit`.
Idempotentné: riadky čo už `source` majú preskočí.

Spusti (dry):    .venv-yar/bin/python toolkit/backfill_provenance.py
Spusti (commit): .venv-yar/bin/python toolkit/backfill_provenance.py --commit
"""
import os
import sys
import json
import shutil
import time

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLKIT)


def _zm():
    """Lazy import zol_mem (ťahá torch cez embed_yar) — až keď reálne treba DB/embed.
    Vďaka tomu sa modul dá importovať v offline teste bez torch."""
    import zol_mem as zm
    return zm


def _paths():
    zm = _zm()
    idx = os.path.join(zm.STATE, "mem_index.jsonl")
    return zm, idx


def _db_source_for(mid, text):
    """Self-query cez search bridge; vráť meta.source pre presný id match, inak None."""
    if not (text or "").strip():
        return None
    zm = _zm()
    try:
        vec = zm.embed_one(text)
        res = zm.hs("search", zm.MEM_COL, 5, stdin=json.dumps({"vector": vec})) or []
    except Exception:
        return None
    for h in res:
        if h.get("id") == mid:
            src = (h.get("meta", {}) or {}).get("source")
            return src or None
    return None


def main():
    commit = "--commit" in sys.argv
    zm, IDX = _paths()
    with open(IDX, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]

    plan = {"total": len(rows), "already": 0, "from_db": 0,
            "unknown_legacy": 0, "empty_text": 0}
    src_dist = {}
    changed = []

    for r in rows:
        if r.get("source"):
            plan["already"] += 1
            changed.append(r)
            continue
        mid = r.get("id")
        text = r.get("text") or ""
        src = _db_source_for(mid, text)
        if src:
            r["source"] = src
            plan["from_db"] += 1
        else:
            r["source"] = "unknown-legacy"
            plan["unknown_legacy"] += 1
            if not text.strip():
                plan["empty_text"] += 1
        if "project" not in r:
            r["project"] = "zolander"
        src_dist[r["source"]] = src_dist.get(r["source"], 0) + 1
        changed.append(r)

    print(json.dumps({"mode": "commit" if commit else "dry-run", "plan": plan,
                      "source_distribution": src_dist}, ensure_ascii=False, indent=2))

    if not commit:
        print("\n[dry-run] nič nezapísané. Spusti s --commit na zápis.")
        return

    # záloha PRED zápisom (pravidlo veducka: záloha pred git/mutáciou)
    bak = IDX + ".bak-" + time.strftime("%Y%m%dT%H%M%S")
    shutil.copy2(IDX, bak)
    with open(IDX, "w", encoding="utf-8") as f:
        for r in changed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[commit] zapísané {len(changed)} riadkov; záloha: {bak}")


if __name__ == "__main__":
    main()
