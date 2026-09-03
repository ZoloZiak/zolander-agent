#!/usr/bin/env python3
"""cleanup_reverse_zombies.py — docisti 664/666 (test artefakty HMAC_..._zmazat).

Reverzne zombie: zmazane z Lorentz zol_mem (rescue/skorsie testy), ale ZIVE v
indexe + Gemma -> BM25 aj Gemma ich stale serviruju. Text = jasny test junk
(HMAC_E2E_TEST_..._zmazat). Docistenie:
  1. odstran z mem_index.jsonl (prepis bez nich, .bak zaloha),
  2. soft-delete z zol_mem_gemma,
  3. trash stopa (recoverable).
Z Lorentz uz preto NEmazem (uz nie su). DRY: --dry-run
"""
import os, sys, json, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT

STATE = os.path.join(ZROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
TARGETS = {664, 666}
DRY = "--dry-run" in sys.argv


def hs(cmd, *a, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(x) for x in a]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd}: {p.stderr[-200:]}")
    return json.loads(p.stdout.strip()) if p.stdout.strip() else None


rows = [json.loads(l) for l in open(IDX, encoding="utf-8") if l.strip()]
hit = [r for r in rows if r["id"] in TARGETS]
keep = [r for r in rows if r["id"] not in TARGETS]
print(f"v indexe najdene: {[r['id'] for r in hit]}")
for r in hit:
    print(f"  [{r['id']}] {r.get('kind')} :: {r.get('text','')[:70]}")

if DRY:
    print(f"[dry] by odstranil {len(hit)} z indexu, del z Gemma {sorted(TARGETS)}")
    sys.exit(0)

# 1) index prepis (.bak)
if hit:
    os.replace(IDX, IDX + ".bak")
    with open(IDX, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

# 2) Gemma del + 3) trash
gdel = []
for tid in sorted(TARGETS):
    try:
        d = hs("del", "zol_mem_gemma", tid)
        if d and d.get("deleted"):
            gdel.append(tid)
    except Exception as e:
        print(f"[warn] gemma del {tid}: {e!r}", file=sys.stderr)
    src = next((r for r in hit if r["id"] == tid), {"id": tid})
    with open(TRASH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "removed": {"id": tid, "meta": src},
                            "reason": "reverse-zombie test artefakt (HMAC _zmazat)",
                            "merged_into": None, "source": "cleanup_reverse_zombies.py"},
                           ensure_ascii=False) + "\n")

print(json.dumps({"index_removed": [r["id"] for r in hit],
                  "gemma_deleted": gdel,
                  "index_before": len(rows), "index_after": len(keep)},
                 ensure_ascii=False, indent=2))
