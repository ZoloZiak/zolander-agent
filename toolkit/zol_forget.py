#!/usr/bin/env python3
"""zol_forget.py — forget politika (poctivé: DEFAULT DŮK jem rýchly návrhy).

DEFAULT = DRY: vypíše návrhy na vyhadzovanie, nič nemaže.
  kandidáti: L0 záznamy oboch pamätí so salience < threshold (default 0.25)
  (skále sa len L0 — L1/L2 koncepty smie vymazat len čluvoli ruka veduca).

--execute --confirm YES: skutočne maže
  - B: delete RPC na id (zajtra point metadany zahyne),
  - A: jsonl rewrite — padne riadky s ts kandidátov A alebo presnou
       plaintextom zhoda u textu kandidátov B,
  - zapíšeme potom A2A podpísaný auditný záznam (dual remember --file,
     source=forget-audit).
  Bez --confirm YES sa execut vzdá (ok:false, nič nespraví).

Pouzitie:
  python toolkit/zol_forget.py [--threshold 0.25]              # návrhy
  python toolkit/zol_forget.py --execute --confirm YES [--threshold ...]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLKIT)
sys.path.insert(0, TOOLKIT)

import zol_mem_text  # noqa: E402


def load_b_points():
    client = zol_mem_text.make_client()
    return zol_mem_text.rpc_call(client.scroll, limit=4000, collection="zol_mem")


def a_entries():
    path = os.path.join(ROOT, "state", "zol_memory.jsonl")
    rows = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows, path


def scan(threshold):
    pts, err = load_b_points()
    if err:
        return {"ok": False, "error": f"B nečitateľný: {err}"}
    rows, _ = a_entries()

    cand_b = []
    for p in (pts or []):
        md = p.get("metadata") or {}
        if md.get("layer") != "L0":
            continue
        try:
            sal = float(md.get("salience", 0.4))
        except (TypeError, ValueError):
            continue
        if sal < threshold:
            cand_b.append({"id": p.get("id"), "ts": md.get("ts"), "salience": sal,
                           "text": str(md.get("text", ""))})
    cand_a = []
    for rec in rows:
        if rec.get("layer") != "L0":
            continue
        try:
            sal = float(rec.get("salience", 0.4))
        except (TypeError, ValueError):
            continue
        if sal < threshold:
            cand_a.append({"ts": rec.get("ts"), "salience": sal,
                           "text": str(rec.get("text", ""))})
    return {"ok": True, "a": cand_a, "b": cand_b}


def do_execute(cands, threshold):
    client = zol_mem_text.make_client()
    rc = zol_mem_text.rpc_call

    # A texty zhodné s B kandidátmi (previazanie památí cez presný plaintext)
    b_texts = {c["text"] for c in cands["b"] if c["text"]}
    a_ts_set = {str(c["ts"]) for c in cands["a"]}
    rows, path = a_entries()
    removed_a, kept = [], []
    for row in rows:
        if str(row.get("ts")) in a_ts_set or (b_texts and row.get("text") in b_texts):
            removed_a.append({"ts": row.get("ts")})
            continue
        kept.append(row)
    with open(path, "w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    removed_b, errors = [], []
    for c in cands["b"]:
        ok, err = rc(client.delete, id=c["id"], collection="zol_mem")
        if err or not ok:
            errors.append({"engine": "B", "id": c["id"], "err": (err or "ok=false")[:150]})
        else:
            removed_b.append({"id": c["id"]})

    audit = {
        "text": (f"Forget audit (threshold {threshold}): vyhodené "
                 f"A={len(removed_a)}, B={len(removed_b)} — L0 záznamy pod "
                 f"salience. Nič iné."),
        "kind": "procedural", "layer": "L0", "confidence": 0.9,
        "source": "forget-audit",
    }
    audit_ok = False
    fd, pth = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(audit, ensure_ascii=False))
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(TOOLKIT, "zol_remember_dual.py"), "--file", pth],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
            cwd=ROOT, timeout=300,
        )
        try:
            audit_out = json.loads(p.stdout or "{}")
            audit_ok = bool(audit_out.get("ok"))
        except json.JSONDecodeError:
            audit_ok = False
    finally:
        os.unlink(pth)

    return {"removed_a": removed_a, "removed_b": removed_b, "errors": errors,
            "audit_dual_ok": audit_ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--confirm", default=None)
    args = ap.parse_args()

    cands = scan(args.threshold)

    if not args.execute:
        print(json.dumps({"ok": True, "mode": "forget-dry", "threshold": args.threshold,
                          "kandidati": {"a": len(cands["a"]), "b": len(cands["b"])},
                          "detail": cands}, ensure_ascii=False, indent=1))
        return 0

    if args.confirm != "YES":
        print(json.dumps({"ok": False, "error": "execute vyžaduje --confirm YES (nič nesmazané)"},
                         ensure_ascii=False))
        return 1
    if not cands.get("ok"):
        print(json.dumps(cands, ensure_ascii=False))
        return 1

    res = do_execute(cands, args.threshold)
    print(json.dumps({"ok": not res["errors"], "mode": "forget-execute",
                      "threshold": args.threshold, **res}, ensure_ascii=False, indent=1))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
