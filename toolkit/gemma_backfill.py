#!/usr/bin/env python3
"""gemma_backfill.py — naplni cosine kolekciu zol_mem_gemma existujucim korpusom.

Cita mem_index.jsonl (id, text), embedne cez gemma_embed_server (HTTP :8901),
vlozi {id, vector[768], meta} do zol_mem_gemma cez hs.mjs. Bezi pod /usr/bin/python3
(stdlib only — netreba torch ani mlx, embed rob daemon). Idempotentne: prepise po id.
"""
import os
import sys
import json
import subprocess
import urllib.request

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
NODE = "/Users/__USER__/Applications/homebrew/bin/node"
HS = "/Users/__USER__/zolo2.0/toolkit/hs.mjs"
NODE_ENV = dict(os.environ, NODE_PATH="/Users/__USER__/.npm/_npx/9e13365ae4a6529c/node_modules")
COL = "zol_mem_gemma"
EMBED_URL = "http://127.0.0.1:8901/embed"


def embed(texts):
    body = json.dumps({"texts": texts, "mode": "document"}).encode()
    req = urllib.request.Request(EMBED_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["vectors"]


def load_corpus():
    rows = []
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("text") and r.get("id") is not None:
            rows.append((r["id"], r["text"], r.get("kind", ""), r.get("layer", "")))
    return rows


def main():
    rows = load_corpus()
    print(f"# korpus: {len(rows)} textov", file=sys.stderr)
    ids = [r[0] for r in rows]
    vecs = embed([r[1] for r in rows])
    assert len(vecs) == len(rows), f"embed count mismatch {len(vecs)} != {len(rows)}"
    lines = []
    for (mid, text, kind, layer), v in zip(rows, vecs):
        lines.append(json.dumps({"id": mid, "vector": v,
                                 "meta": {"kind": kind, "layer": layer, "text": text[:300]}},
                                ensure_ascii=False))
    stdin = "\n".join(lines) + "\n"
    p = subprocess.run([NODE, HS, "insert", COL], input=stdin,
                       capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        print("INSERT ZLYHAL:", p.stderr[-500:], file=sys.stderr)
        return 1
    print(f"OK backfill: {len(lines)} vektorov -> {COL}")
    print(p.stdout.strip()[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
