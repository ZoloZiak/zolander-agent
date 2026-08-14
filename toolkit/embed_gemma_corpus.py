#!/usr/bin/env python3
"""embed_gemma_corpus.py — refresh eval cache Z DAEMONA (jeden zdroj pravdy, s prefixmi).

Predtym mal vlastnu embed cestu bez prefixov -> nekonzistentne s produkciou (daemon).
Teraz vola gemma_embed_server: korpus mode=document, gold queries mode=query.
Vystup: state/gemma_corpus.npz, state/gemma_gold.npz. Beztak stdlib+numpy (embed rob daemon).
"""
import os
import sys
import json
import urllib.request
import numpy as np

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
OUT_CORP = os.path.join(STATE, "gemma_corpus.npz")
OUT_GOLD = os.path.join(STATE, "gemma_gold.npz")
EMBED_URL = "http://127.0.0.1:8901/embed"


def embed(texts, mode):
    body = json.dumps({"texts": texts, "mode": mode}).encode()
    req = urllib.request.Request(EMBED_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return np.array(json.load(r)["vectors"], dtype=np.float32)


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
            rows.append((r["id"], r["text"]))
    return rows


def main():
    rows = load_corpus()
    ids = [r[0] for r in rows]
    cvecs = embed([r[1] for r in rows], "document")
    np.savez(OUT_CORP, ids=np.array(ids), vecs=cvecs)
    print(f"OK korpus -> {OUT_CORP} shape={cvecs.shape}")

    gold = json.load(open(GOLD))
    qvecs = embed([g["query"] for g in gold], "query")
    np.savez(OUT_GOLD, target_ids=np.array([g["id"] for g in gold]), qvecs=qvecs)
    print(f"OK gold -> {OUT_GOLD} shape={qvecs.shape}")


if __name__ == "__main__":
    main()
