#!/usr/bin/env python3
"""zol_ascend.py — vzostup vrstiev L0 -> L1 -> L2 (fáza vrstiev).

Mechanizmus (žiaden LLM — rule-based koncept):
  1. Server-side clustering: FindSemanticClusters (HNSW graf nad vektormi
     zol_mem; na lorentz kolekcii sú hrany typ HIERARCHY). Honesty: interne
     beží zhlukovací engine servera nad vektormi — NIE čisto lorentz.
  2. PASS L0->L1: pre každý cluster (>= min_size L0 členov) postavi
     KONCEPT client-side (zdielané kľúčové slová + hlava člena 1).
  3. PASS L1->L2: rovnaké server clustery obmedzené na L1 členy ->
     L2 koncept nad L1.
  4. Zápis do OBOCH pamätí (dual remember + A2A podpis) s layer dst,
     kind=semantic, metadata members/members_hash.
  5. Dedup: members_hash (sha1 zo sort ids) — rovnaký len raz.

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


def concept_text(member_ids, by_id, dst):
    texts = [str((by_id[i].get("metadata") or {}).get("text", "")) for i in member_ids if i in by_id]
    kws = keywords([t for t in texts if t])
    head = texts[0][:160] if texts else ""
    return (
        f"{dst} koncept (ascend, {len(member_ids)} členov) — témata: "
        f"{', '.join(kws) if kws else '(bez kľúčových slov)'} | členovia: {list(member_ids)}"
        f" | hlava čl.1: {head}"
    )


def members_hash(ids):
    return hashlib.sha1(",".join(str(i) for i in sorted(ids)).encode()).hexdigest()


def existing_hashes(points, layer):
    out = set()
    for p in points:
        md = p.get("metadata") or {}
        if md.get("layer") == layer and md.get("members_hash"):
            out.add(md["members_hash"])
    return out


def ascend_pass(pts, clusters, src, dst, dry_run, min_size=2):
    """Jeden ascend pass: clustery obmedzene na body vrstvy src -> koncept
    do vrstvy dst (dual zapis, A2A podpis, dedup members_hash)."""
    src_map = {}
    dst_hashes = set()
    for p in pts:
        md = p.get("metadata") or {}
        i = p.get("id")
        if md.get("layer") == src:
            src_map[i] = p
        if md.get("layer") == dst and md.get("members_hash"):
            dst_hashes.add(md["members_hash"])
    by_id = {p.get("id"): p for p in pts}

    report = {"from": src, "to": dst, "src_nodes": len(src_map),
              "clusters_used": 0, "created": [], "skipped_dedup": []}
    for ids in clusters:
        cids = [i for i in ids if i in src_map]
        if len(cids) < min_size:
            continue
        report["clusters_used"] += 1
        cid = members_hash(cids)
        if cid in dst_hashes:
            report["skipped_dedup"].append({"members": list(cids), "members_hash": cid})
            continue
        text = concept_text(cids, by_id, dst)
        if dry_run:
            report["created"].append({"dry_run": True, "members": list(cids), "text_head": text[:140]})
            continue
        out = dual_remember_layer(text, cids, cid, dst)
        report["created"].append({"members": list(cids), "members_hash": cid,
                                  "dual_ok": bool(out.get("ok")), "dual_ok_detail": {
                                      "A": bool((out.get("A") or {}).get("ok")),
                                      "B": bool((out.get("B") or {}).get("ok"))}})
        dst_hashes.add(cid)
    return report


def dual_remember_layer(text, members, mhash, layer):
    payload = json.dumps(
        {"text": text, "kind": "semantic", "layer": layer, "confidence": 0.75,
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
    by_layer: dict[str, dict] = {}
    for p in pts:
        md = p.get("metadata") or {}
        if md.get("layer") in ("L0", "L1", "L2"):
            by_layer.setdefault(md.get("layer"), {})[p.get("id")] = p

    if not by_layer.get("L0"):
        print(json.dumps({"ok": False, "note": "žiadne L0 body v B pamäti — bez ascendu"}, ensure_ascii=False))
        return 0

    min_size = max(2, int(args.min_size))
    try:
        server_clusters = clusters_of(rpc_call, client, min_size, args.max_clusters * 2)
    except RuntimeError as e:
        print(json.dumps({"ok": False, "error": str(e)[:300]}, ensure_ascii=False))
        return 1

    # Pass 1: L0->L1 (clustery obmedzené na L0 členov).
    plain = [c for c in server_clusters if sum(1 for i in c if i in by_layer.get("L0", {})) >= min_size]
    rep1 = ascend_pass(pts, plain, "L0", "L1", args.dry_run, min_size)
    # Pass 2: L1->L2 (rovnaké server clustery obmedzené na L1 členov).
    rep2 = ascend_pass(pts, server_clusters, "L1", "L2", args.dry_run, min_size)

    report = {"ok": True, "pass_L0_L1": rep1, "pass_L1_L2": rep2}
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
