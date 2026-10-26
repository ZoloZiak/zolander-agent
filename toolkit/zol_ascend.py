#!/usr/bin/env python3
"""zol_ascend.py — L0 -> L1 ascend (fáza 1 vrstiev).

Mechanizmus (žiaden LLM — rule-based koncept):
  1. Server-side clustering: FindSemanticClusters (HNSW graf nad vektormi
     zol_mem; na lorentz kolekcii sú hrany typ HIERARCHY). Honesty: interne
     beží zhlukovací engine servera nad vektormi — NIE čisto lorentz.
  2. Pre každý cluster (>= min_size členov) postavi KONCEPT client-side:
     zdielané kľúčové slová členov + hlava prvého člena.
  3. Zápis ako NOVÝ bod do OBOCH pamätí (dual remember + A2A podpis) s
     layer=L1, kind=semantic, metadata members/members_hash.
  4. Dedup: members_hash (sha1 zo sort ids) — rovnaký cluster nezapíše
     ináč druhý raz.
  5. Report: clusters + vytvorené L1 ids.

Použitie:
  python toolkit/zol_ascend.py [--dry-run] [--min-size 3] [--max-clusters 6]
  python toolkit/zol_ascend.py tree --root <id>   # GetSubsumptionTree od bodu

Vystup JSON na stdout, exit 0 == ok.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLKIT)
sys.path.insert(0, TOOLKIT)

COLLECTION = "zol_mem"
STOP = set("a aj ako ale asi azaž buď by byť či dnes do ešte je jeho ich ked keď kým že lebo ma má mám máš mi môj máme musím my na nad nami nás ne nemá nemôže nie nič niečo nieje no o od on oni po pod pred pre presne pri raz som s so tak tato táto te ten tento teraz toto tu vaše vo vy v z za že".split())


def make_client():
    import zol_mem_text
    return zol_mem_text.make_client(), zol_mem_text.rpc_call


def all_points():
    client, rpc_call = make_client()
    pts, _ = rpc_call(client.scroll, limit=4000, collection=COLLECTION)
    return client, rpc_call, [p for p in (pts or [])]


def clusters_of(rpc_call, client, min_size, max_clusters):
    res, err = rpc_call(
        client.find_semantic_clusters,
        layer=0,
        min_cluster_size=min_size,
        max_clusters=max_clusters,
        max_nodes=10000,
        collection=COLLECTION,
    )
    if err:
        raise RuntimeError(f"RPC chyba pri FindSemanticClusters: {err}")
    out = []
    for c in (res or []):
        if isinstance(c, dict):
            out.append(c.get("node_ids") or c.get("ids") or [])
        elif isinstance(c, (list, tuple)):
            out.append(list(c))
    return out


def keywords(texts, k=6):
    words: list[str] = []
    for t in texts:
        for w in re.findall(r"[a-zA-Zà-ýa-zá-ý0-9]{3,}", t.lower()):
            if w not in STOP:
                words.append(w)
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in top[:k]]


def concept_text(member_ids, by_id):
    texts = [str((by_id[i].get("metadata") or {}).get("text", "")) for i in member_ids if i in by_id]
    kws = keywords([t for t in texts if t])
    head = texts[0][:160] if texts else ""
    return (
        f"L1 koncept (ascend, {len(member_ids)} členov) — témata: "
        f"{', '.join(kws) if kws else '(bez kľúčových slov)'} | členovia: {list(member_ids)}"
        f" | hlava čl.1: {head}"
    )


def members_hash(ids):
    return hashlib.sha1(",".join(str(i) for i in sorted(ids)).encode()).hexdigest()


def existing_hashes(points):
    out = set()
    for p in points:
        md = p.get("metadata") or {}
        if md.get("layer") == "L1" and md.get("members_hash"):
            out.add(md["members_hash"])
    return out


def dual_remember_l1(text, members, mhash):
    payload = json.dumps(
        {"text": text, "kind": "semantic", "layer": "L1", "confidence": 0.75,
         "source": "ascend", "members": ",".join(map(str, members)),
         "members_hash": mhash},
        ensure_ascii=False,
    )
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        # --file (čistý UTF-8), nie stdin pipe (PS 5.1 posiela ASCII).
        p = subprocess.run(
            [sys.executable, os.path.join(TOOLKIT, "zol_remember_dual.py"), "--file", path],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
            cwd=ROOT, timeout=300,
        )
        try:
            return json.loads(p.stdout or "{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": (p.stderr or p.stdout)[-300:]}
    finally:
        os.unlink(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-size", type=int, default=2)
    ap.add_argument("--max-clusters", type=int, default=6)
    args = ap.parse_args()

    if len(sys.argv) >= 3 and sys.argv[1] == "tree":
        client, rpc_call, _ = make_client()
        root_id = int(sys.argv[sys.argv.index("--root") + 1])
        nodes, err = rpc_call(client.get_subsumption_tree, root_id=root_id, max_depth=3, collection=COLLECTION)
        if err:
            print(json.dumps({"ok": False, "error": str(err)[:300]}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "tree": nodes}, ensure_ascii=False, indent=1, default=str))
        return 0

    client, rpc_call, pts = all_points()
    by_id = {}
    by_layer: dict[str, dict] = {}
    for p in pts:
        i = p.get("id")
        md = p.get("metadata") or {}
        if md.get("layer") in ("L0", "L1"):
            by_id[i] = p
            by_layer.setdefault(md.get("layer"), {})[i] = p

    l0_map = by_layer.get("L0", {})
    if not l0_map:
        print(json.dumps({"ok": False, "note": "žiadne L0 body v B pamäti — bez ascendu"}, ensure_ascii=False))
        return 0

    min_size = max(2, int(args.min_size))
    clusters = []
    for ids in clusters_of(rpc_call, client, min_size, args.max_clusters):
        cids = [i for i in ids if i in l0_map]
        if len(cids) >= min_size:
            clusters.append(cids)

    existing = existing_hashes(pts)
    report: dict = {"ok": True, "clusters_found": len(clusters), "nodes_l0": len(l0_map),
                    "created": [], "skipped_dedup": []}
    for cids in clusters:
        cid = members_hash(cids)
        text = concept_text(cids, by_id)
        if cid in existing:
            report["skipped_dedup"].append({"members": list(cids), "members_hash": cid})
            continue
        if args.dry_run:
            report["created"].append({"dry_run": True, "members": list(cids), "text_head": text[:140]})
            continue
        out = dual_remember_l1(text, cids, cid)
        report["created"].append({"members": list(cids), "members_hash": cid,
                                  "dual_ok": bool(out.get("ok")), "dual": out})
        existing.add(cid)

    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
