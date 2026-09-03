#!/usr/bin/env python3
"""gemma_cross.py — cross-mosty pamat<->kniha cez EmbeddingGemma (semanticky, NIE YAR).

Dovod: YAR cross-mosty su sum (najblizsi par mal cosine-dist 0.80, ziadny obsahovy suvis).
Gemma (768D, silny semanticky) da most len tam kde sa spomienka a atom knihy REALNE dotykaju.

Krok 1 (TENTO skript, diagnostika): embedni oba korpusy cez gemma_embed_server (mode=document),
spocitaj cosine, vypis distribuciu podobnosti + top parov. Az z REALNYCH cisel rozhodneme prah.
Nemeni viz.html — najprv chcem vidiet ci vobec nieco zmysluplne prekroci prah.

Beh: /usr/bin/python3 (stdlib+numpy) — embed rob daemon. Daemon musi bezat na :8901.
"""
import os
import json
import urllib.request
import numpy as np

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
ZOLO = os.path.join(HOME, "projects", "__PROJECT__")
MEM_IDX = os.path.join(ROOT, "state", "mem_index.jsonl")
META = os.path.join(ZOLO, "work", "ingest_meta.jsonl")
ASSIGN = os.path.join(ZOLO, "work", "assignments_opus.jsonl")
EMBED_URL = "http://127.0.0.1:8901/embed"
OUT = os.path.join(ROOT, "state", "gemma_cross.json")


def embed(texts, mode, batch=64):
    out = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        body = json.dumps({"texts": chunk, "mode": mode}).encode()
        req = urllib.request.Request(EMBED_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out.extend(json.load(r)["vectors"])
        print(f"  embed {mode}: {min(i+batch,len(texts))}/{len(texts)}", flush=True)
    return np.array(out, dtype=np.float32)


def load_mem():
    rows, seen = [], set()
    for line in open(MEM_IDX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("text"):
            continue
        rid = r.get("id")
        if rid in seen:
            rows = [x for x in rows if x.get("id") != rid]
        seen.add(rid)
        rows.append(r)
    return rows


def load_book():
    meta = {}
    for line in open(META, encoding="utf-8"):
        if line.strip():
            o = json.loads(line)
            meta[o["gid"]] = o
    asn = {}
    for line in open(ASSIGN, encoding="utf-8"):
        if line.strip():
            o = json.loads(line)
            asn[o["gid"]] = o
    rows = []
    for gid, m in meta.items():
        txt = (m.get("clean") or m.get("orig") or "").strip().replace("\n", " ")
        if not txt:
            continue
        a = asn.get(gid, {})
        rows.append({"gid": gid, "text": txt,
                     "theme": a.get("theme", "?"), "layer": a.get("layer", "L1")})
    return rows


def main():
    mem = load_mem()
    book = load_book()
    print(f"[data] pamat={len(mem)} kniha={len(book)}", flush=True)

    print("[embed] pamat (document)...", flush=True)
    Vm = embed([r["text"] for r in mem], "document")
    print("[embed] kniha (document)...", flush=True)
    Vb = embed([r["text"] for r in book], "document")

    # daemon L2-normalizuje -> cosine = dot
    Vm /= (np.linalg.norm(Vm, axis=1, keepdims=True) + 1e-9)
    Vb /= (np.linalg.norm(Vb, axis=1, keepdims=True) + 1e-9)
    sim = Vm @ Vb.T                      # (nm, nb) cosine podobnost [-1,1]

    jbest = sim.argmax(axis=1)
    sbest = sim[np.arange(len(mem)), jbest]

    print("\n=== DISTRIBUCIA najlepsej podobnosti (pre kazdu spomienku najblizsi atom knihy) ===")
    for p in [50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: cosine {np.percentile(sbest, p):.3f}")
    for thr in [0.5, 0.6, 0.7, 0.8]:
        print(f"  spomienok s najblizsim atomom nad {thr}: {int((sbest>=thr).sum())}/{len(mem)}")

    order = np.argsort(-sbest)
    print("\n=== TOP 12 najsilnejsich semantickych mostov ===\n")
    for i in order[:12]:
        j = int(jbest[i])
        print(f"[cos {sbest[i]:.3f}]  KNIHA[{book[j]['theme']}/{book[j]['layer']}]")
        print(f"  P: {mem[i]['text'][:150]}")
        print(f"  K: {book[j]['text'][:150]}")
        print()

    # ulozime mosty nad 0.6 na pripadne zapojenie do viz
    THR = 0.6
    bridges = []
    for i in order:
        if sbest[i] < THR:
            break
        bridges.append({"mem_id": mem[i].get("id"), "gid": book[int(jbest[i])]["gid"],
                        "cos": round(float(sbest[i]), 3),
                        "mem_text": mem[i]["text"][:120], "book_text": book[int(jbest[i])]["text"][:120]})
    json.dump(bridges, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"OK mostov nad {THR}: {len(bridges)} -> {OUT}")


if __name__ == "__main__":
    main()
