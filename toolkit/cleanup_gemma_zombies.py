#!/usr/bin/env python3
"""cleanup_gemma_zombies.py — docistenie po rescue_orphans.py.

rescue mazal orphany len z Lorentz zol_mem, NIE z zol_mem_gemma -> zombie
(mrtve v Lorentz, zive v Gemma). Navyse novy fakt 683 natiahol related hrany
na 405/400/403 kym boli zive. Toto:
  1. soft-delete orphanov 397-405 z zol_mem_gemma,
  2. odstrani висячие hrany 683->{405,400,403} z mem_edges.jsonl (zaloha .bak).
DRY: --dry-run
"""
import os, sys, json, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT

STATE = os.path.join(ZROOT, "state")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
ORPHANS = {397, 398, 399, 400, 401, 402, 403, 404, 405}
DRY = "--dry-run" in sys.argv


def hs(cmd, *a, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(x) for x in a]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd}: {p.stderr[-200:]}")
    return json.loads(p.stdout.strip()) if p.stdout.strip() else None


# 1) del z Gemma
gdel, gmiss = [], []
for oid in sorted(ORPHANS):
    if DRY:
        print(f"[dry] del zol_mem_gemma {oid}")
        continue
    try:
        d = hs("del", "zol_mem_gemma", oid)
        (gdel if (d and d.get("deleted")) else gmiss).append(oid)
    except Exception as e:
        gmiss.append(oid)
        print(f"[warn] gemma del {oid}: {e!r}", file=sys.stderr)

# 2) odstran висячие hrany 683 -> mrtvy orphan
edges = [json.loads(l) for l in open(EDGES, encoding="utf-8") if l.strip()]
def is_dangling(e):
    return (e.get("from") == 683 and e.get("to") in ORPHANS)
drop = [e for e in edges if is_dangling(e)]
keep = [e for e in edges if not is_dangling(e)]
print(f"hrany na odstranenie (683->orphan): {len(drop)}")
for e in drop:
    print("  ", e)
if not DRY and drop:
    os.replace(EDGES, EDGES + ".bak")  # zaloha
    with open(EDGES, "w", encoding="utf-8") as f:
        for e in keep:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

print(json.dumps({
    "dry_run": DRY,
    "gemma_deleted": gdel,
    "gemma_miss": gmiss,
    "edges_dropped": len(drop),
    "edges_before": len(edges),
    "edges_after": len(edges) - (0 if DRY else len(drop)),
}, ensure_ascii=False, indent=2))
