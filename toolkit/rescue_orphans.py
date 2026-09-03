#!/usr/bin/env python3
"""rescue_orphans.py — Bug 1 zachrana: DB-only orphany 397-405.

Tieto ID boli vpchane priamym `hs insert` (obchadzajuc cmd_remember) -> su v DB
Lorentz, ale NIE v indexe, NIE v Gemma, bez HMAC podpisu = slepe pre BM25 aj decay
aj Gemma lens. Obsah = realny fakt o veduckovi (hudba) + test junk + 1
redundantny fakt.

Postup (kopiruje dream-loop recovery vzor):
  1. re-fetch full meta orphanov cez search (pre trash recovery),
  2. soft-delete kazdy z DB + zapis do dedup_trash.jsonl (merged_into=novy cisty fakt),
  3. zapis JEDEN cisty konsolidovany hudobny fakt cez OFICIALNY cmd_remember
     (Lorentz + Gemma + index + HMAC + graf hrany naraz).

DRY-RUN: `python rescue_orphans.py --dry-run` (nic nemaze, nic nezapisuje).
"""
import os, sys, io, json, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT
from embed_yar import embed_one

STATE = os.path.join(ZROOT, "state")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
MEM_COL = "zol_mem"
ORPHANS = {397, 398, 399, 400, 401, 402, 403, 404, 405}
DRY = "--dry-run" in sys.argv

# cisty konsolidovany fakt (nahrada za 399-405; 397 redundantny, 398 junk)
CLEAN_FACT = (
    "Vedúcko vyrába elektronickú hudbu, "
    ""
    "chce 100% analógový reťazec, nula digitálu vo výrobe."
)


def hs(cmd, *args, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd}: {p.stderr[-300:]}")
    out = p.stdout.strip()
    return json.loads(out) if out else None


# --- 1) re-fetch full meta orphanov (batéria dotazov, zozbieraj payloady) ---
QUERIES = [
    "elektronicka hudba zaner beat efekt analog vyroba",
    "OrbStack kontajner hyperspace port 50051 pamat",
    "fail-open test gemma daemon xyzzy",
]
found = {}
for q in QUERIES:
    vec = embed_one(q)
    for r in (hs("search", MEM_COL, 300, stdin=json.dumps({"vector": vec})) or []):
        if r.get("id") in ORPHANS:
            found[r["id"]] = r

print(f"[audit] orphanov najdenych v DB search: {sorted(found)}", file=sys.stderr)
missing = ORPHANS - set(found)
if missing:
    print(f"[audit] nenajdene cez search (skusim del po ID aj tak): {sorted(missing)}",
          file=sys.stderr)

# --- 2) soft-delete + trash ---
trashed, del_fail = [], []
for oid in sorted(ORPHANS):
    rec = found.get(oid)
    meta = (rec or {}).get("meta", {}) or {}
    reason = ("test junk (xyzzy)" if oid == 398 else
              "redundantny s indexom (OrbStack 5x)" if oid == 397 else
              "DB-only orphan zluceny do cisteho hudobneho faktu")
    if DRY:
        print(f"[dry] del {oid} + trash :: {reason} :: {(meta.get('text') or '')[:70]}")
        trashed.append(oid)
        continue
    # del PRV, trash az po uspesnom zmazani (ako dream loop)
    try:
        d = hs("del", MEM_COL, oid)
        ok = bool(d and d.get("deleted"))
    except Exception as e:
        ok = False
        print(f"[warn] del {oid} vynimka: {e!r}", file=sys.stderr)
    if ok:
        with open(TRASH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "removed": {"id": oid, "meta": meta},
                "reason": reason,
                "merged_into": "PENDING",  # doplni sa po zapise cisteho faktu
                "source": "rescue_orphans.py",
            }, ensure_ascii=False) + "\n")
        trashed.append(oid)
    else:
        del_fail.append(oid)

# --- 3) zapis JEDEN cisty fakt cez OFICIALNY cmd_remember ---
new_id = None
if not DRY:
    import zol_mem
    payload = {
        "text": CLEAN_FACT, "kind": "semantic", "layer": "L1",
        "salience": 0.75, "confidence": 0.85, "source": "rescue_orphan_backfill",
        "no_dedup": True,  # orphany uz zmazane; poistka proti kolizii s ich duchmi
    }
    _real_stdin, _real_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(payload))
    _buf = io.StringIO()
    sys.stdout = _buf
    try:
        zol_mem.cmd_remember()
    finally:
        sys.stdin, sys.stdout = _real_stdin, _real_stdout
    out = _buf.getvalue().strip()
    print(f"[insert] cmd_remember -> {out}", file=sys.stderr)
    try:
        new_id = json.loads(out.splitlines()[-1]).get("remembered")
    except Exception:
        new_id = None
    # doplnenie merged_into=new_id v trash zaznamoch tejto davky
    if new_id is not None:
        lines = open(TRASH, encoding="utf-8").read().splitlines()
        for i in range(len(lines) - 1, -1, -1):
            try:
                r = json.loads(lines[i])
            except Exception:
                continue
            if r.get("source") == "rescue_orphans.py" and r.get("merged_into") == "PENDING":
                r["merged_into"] = new_id
                lines[i] = json.dumps(r, ensure_ascii=False)
            elif r.get("merged_into") != "PENDING" and r.get("source") == "rescue_orphans.py":
                break
        with open(TRASH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
else:
    print(f"[dry] by zapisal cisty fakt cez cmd_remember: {CLEAN_FACT[:80]}...")

print(json.dumps({
    "dry_run": DRY,
    "trashed": trashed,
    "del_fail": del_fail,
    "new_clean_fact_id": new_id,
}, ensure_ascii=False, indent=2))
