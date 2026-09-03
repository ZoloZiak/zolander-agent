#!/usr/bin/env python3
"""purge_vata.py — cielený purge aforizmovej "vaty" z vysokých vrstiev (Bug 2).

PROBLÉM (2026-08-30, veducko): ascend/consolidate_graph vygeneroval ~86 abstraktných
"PRINCIP:"/"META-RÁMEC:" destilátov do L2/L3. Recall ich servíruje PRVÉ (vysoký layer +
salience) => pamäť sa plní múdroslovím namiesto faktov. Generátor je už VYPNUTÝ
(zolander_dream.py, ZOL_ASCEND_ENABLED default 0). Tento skript odstráni EXISTUJÚCU vatu.

PREČO NIE zol_gc.py: jeho filter je hits==0 AND confidence<0.5. Vata má confidence 0.75 =>
zol_gc ju nechytí. Navyše zol_gc len nastaví archived flag + hs del z Lorentz, ale:
  - mem_lexical.load_corpus() NEfiltruje 'archived' => BM25 lens by uzol ďalej vracal
  - nemaže z zol_mem_gemma (cosine lens) => zombie v Gemma vrstve
  - nemaže hrany v mem_edges.jsonl => orphan hrany
Preto tento skript čistí VŠETKY 4 sklady: Lorentz DB + Gemma DB + index (fyzicky) + hrany.

SCOPE: L2/L3 uzly MIMO whitelistu PROTECT. PROTECT = persona + anti-halucinačné/anti-
sycophancy protokoly + doménové fakty (NIE vata). Konzervatívne: pri pochybnosti CHRÁŇ.

BEZPEČNOSŤ:
  - DEFAULT DRY-RUN: len vypíše zoznam, nič nemaže. --commit spustí reálne.
  - Archív PRED mazaním do mem_archive.jsonl (append/invalidate, plne obnoviteľné).
  - Soft-del z DB (hs del), fyzické vytiahnutie z indexu, odstránenie hrán.

Použitie:
  .venv-yar/bin/python purge_vata.py                # DRY-RUN: audit
  .venv-yar/bin/python purge_vata.py --commit       # reálny purge
"""
import os
import sys
import json
import time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV  # prenositelne cesty

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
ARCHIVE = os.path.join(STATE, "mem_archive.jsonl")

MEM_COL = "zol_mem"
GEMMA_COL = "zol_mem_gemma"
PURGE_LAYERS = ("L2", "L3")

# WHITELIST — nikdy nemazať. Persona + protokoly + doménové fakty (overené 2026-08-30):
#   37  = persona ("veducko" + jedovatý humor)
#   39  = anti-halucinačný protokol (over pred tvrdením)
#   40  = abstain/ternárne skórovanie (arXiv 2511.11500)
#   41  = anti-sycophancy liek (arXiv 2602.23971, 2505.23840)
#   347 = zdržanlivosť pred tvrdením (jadro persony)
#   563 = farmako doménový fakt (enzýmový inhibítor — statíny)
#   631 = identity-fakt: pravdivosť systému = verifikovateľný záznam (konkrétny)
#   635 = identity-fakt: identita agenta = perzist. vrstva + Ed25519 + záväzok k pravde
PROTECT = {37, 39, 40, 41, 347, 563, 631, 635}


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def _hs_del(col, mid):
    p = subprocess.run([NODE, HS, "del", col, str(mid)],
                       capture_output=True, text=True, env=NODE_ENV)
    return p.returncode == 0, (p.stderr or p.stdout or "").strip()[:200]


def find_targets():
    rows = _load_jsonl(IDX)
    targets = [r for r in rows
               if r.get("layer") in PURGE_LAYERS and r.get("id") not in PROTECT]
    return rows, targets


def main():
    commit = "--commit" in sys.argv
    rows, targets = find_targets()
    tids = {r.get("id") for r in targets}

    # hrany dotknuté purge (from alebo to v tids)
    edges = _load_jsonl(EDGES)
    dead_edges = [e for e in edges if e.get("from") in tids or e.get("to") in tids]

    result = {
        "mode": "commit" if commit else "dry-run",
        "protect": sorted(PROTECT),
        "purge_count": len(targets),
        "edges_removed": len(dead_edges),
        "purge_ids": sorted(tids),
        "deleted": {"lorentz": [], "gemma": [], "fail": []},
    }

    if not commit:
        result["preview"] = [
            {"id": r.get("id"), "layer": r.get("layer"), "kind": r.get("kind"),
             "layer_score": r.get("layer_score"), "text": (r.get("text") or "")[:90]}
            for r in sorted(targets, key=lambda r: (r.get("layer"), r.get("id")))
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # --- COMMIT ---
    os.makedirs(STATE, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 1) ARCHÍV pred mazaním (obnoviteľné) — uzly aj hrany
    with open(ARCHIVE, "a", encoding="utf-8") as f:
        for r in targets:
            rec = dict(r, archived_at=ts, archived_reason="purge_vata_bug2")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for e in dead_edges:
            rec = dict(e, _kind="edge", archived_at=ts, archived_reason="purge_vata_bug2")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 2) soft-del z oboch DB kolekcií
    for mid in sorted(tids):
        ok_l, err_l = _hs_del(MEM_COL, mid)
        if ok_l:
            result["deleted"]["lorentz"].append(mid)
        else:
            result["deleted"]["fail"].append({"col": MEM_COL, "id": mid, "err": err_l})
        ok_g, err_g = _hs_del(GEMMA_COL, mid)
        if ok_g:
            result["deleted"]["gemma"].append(mid)
        # Gemma zlyhanie nie je fatálne (fail-open dual-write) — nezapisuj ako fail

    # 3) fyzicky vytiahni z indexu (BM25 lens číta index bez archived filtra)
    kept = [r for r in rows if r.get("id") not in tids]
    with open(IDX, "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    result["index_before"] = len(rows)
    result["index_after"] = len(kept)

    # 4) odstráň dotknuté hrany
    live_edges = [e for e in edges if e.get("from") not in tids and e.get("to") not in tids]
    with open(EDGES, "w", encoding="utf-8") as f:
        for e in live_edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    result["edges_before"] = len(edges)
    result["edges_after"] = len(live_edges)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
