#!/usr/bin/env python3
"""gemma_cross_llm.py — cross-mosty pamat<->kniha HYBRID: Gemma predfilter + OPUS reasoning.

Preco: embedder (YAR aj Gemma) najde len geometricku blizkost = "top mosty" boli semanticky
sum (0.74 par: "zdrzanlivost pred tvrdenim" <-> "zakaz akcii pred likvidaciou pobocky" = nic).
Skill §10: relacny sud NIE je podobnost tvaru textu ale REASONING -> robi OPUS, nie embedder.

Pipeline (resumovatelny):
  FAZA 1 embed: oba korpusy cez gemma_embed_server (mode=document), ulozi state/gemma_vecs.npz
                (skip ak npz uz existuje). Osetruje nulove/prazdne vektory.
  FAZA 2 kandidati: pre kazdu spomienku top-K kniznych atomov cez Gemma cosine.
  FAZA 3 OPUS: davka spomienok+kandidatov -> Opus vyberie ktory (ak vobec) REALNE obsahovo
               suvisi, vrati {mem_idx, best_gid|null, strength 0-1, reason}. Prisny (default null).
  Vystup: state/cross_bridges.json = LEN Opusom potvrdene mosty (s dovodom). Resume: cross_llm.progress

Beh: /usr/bin/python3 (numpy + palantir_client zo __PROJECT__). Daemon Gemma na :8901.
"""
import os
import sys
import json
import urllib.request
import numpy as np

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
ZOLO = os.path.join(HOME, "projects", "__PROJECT__")
sys.path.insert(0, os.path.join(ZOLO, "toolkit"))

MEM_IDX = os.path.join(ROOT, "state", "mem_index.jsonl")
META = os.path.join(ZOLO, "work", "ingest_meta.jsonl")
ASSIGN = os.path.join(ZOLO, "work", "assignments_opus.jsonl")
EMBED_URL = "http://127.0.0.1:8901/embed"
NPZ = os.path.join(ROOT, "state", "gemma_vecs.npz")
PROG = os.path.join(ROOT, "state", "cross_llm.progress")
OUT = os.path.join(ROOT, "state", "cross_bridges.json")

TOPK = 8          # kolko kniznych kandidatov na spomienku predlozit Opusovi
BATCH = 6         # kolko spomienok v jednom Opus volani
MIN_STRENGTH = 0.5  # Opusova sila pod ktoru most zahodime


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
        if len(txt) < 12:          # osetri prazdne/krratke -> nulovy vektor, sum
            continue
        a = asn.get(gid, {})
        rows.append({"gid": gid, "text": txt,
                     "theme": a.get("theme", "?"), "layer": a.get("layer", "L1")})
    return rows


def l2norm(V):
    n = np.linalg.norm(V, axis=1, keepdims=True)
    n[n == 0] = 1.0            # osetri nulovy vektor (bez divide-by-zero)
    return V / n


SYSTEM = (
    "Si prisny posudzovatel obsahovej suvislosti. Dostanes SPOMIENKU (fakt o AI asistentovi "
    "Zolander alebo o pouzivatelovi) a zoznam KANDIDATOV = atomov z knihy (osobny masterplan). "
    "Uloha: rozhodni ci NIEKTORY kandidat s spomienkou REALNE OBSAHOVO suvisi — teda hovoria o "
    "tej istej myslienke, principe, teme alebo situacii, nie len nahodou zdielaju slovo. "
    "Bud PRISNY: povrchova/nahodna zhoda slov = ZIADNY most (best_gid null). Most len ked by "
    "clovek povedal 'ano, toto sa naozaj tyka toho isteho'. Vrat CISTY JSON pole, jeden objekt "
    "na spomienku: {\"mem_idx\":int, \"best_gid\":int|null, \"strength\":0.0-1.0, \"reason\":\"kratko po slovensky\"}."
)


def ask_opus(batch_items):
    from palantir_client import chat
    payload = []
    for it in batch_items:
        payload.append({
            "mem_idx": it["mem_idx"],
            "spomienka": it["mem_text"][:280],
            "kandidati": [{"gid": c["gid"], "text": c["text"][:180]} for c in it["cands"]],
        })
    prompt = ("Posud tieto spomienky a ich kandidatov. Vrat IBA JSON pole.\n\n"
              + json.dumps(payload, ensure_ascii=False))
    resp = chat(prompt, model="opus", max_tokens=1500, system=SYSTEM)
    # robustny JSON parse (salvage pole)
    s = resp.strip()
    a, b = s.find("["), s.rfind("]")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    try:
        return json.loads(s)
    except Exception:
        return []


def main():
    mem = load_mem()
    book = load_book()
    print(f"[data] pamat={len(mem)} kniha={len(book)}", flush=True)

    # FAZA 1: embed (cache)
    if os.path.exists(NPZ):
        d = np.load(NPZ, allow_pickle=True)
        Vm, Vb = d["Vm"], d["Vb"]
        print(f"[embed] cache {NPZ}", flush=True)
    else:
        print("[embed] pamat...", flush=True)
        Vm = embed([r["text"] for r in mem], "document")
        print("[embed] kniha...", flush=True)
        Vb = embed([r["text"] for r in book], "document")
        np.savez(NPZ, Vm=Vm, Vb=Vb)
    Vm, Vb = l2norm(Vm), l2norm(Vb)

    # FAZA 2: kandidati (top-K na spomienku)
    sim = Vm @ Vb.T
    topk_idx = np.argsort(-sim, axis=1)[:, :TOPK]

    # resume
    done = set()
    if os.path.exists(PROG):
        for line in open(PROG):
            line = line.strip()
            if line:
                done.add(int(line))
    bridges = []
    if os.path.exists(OUT):
        try:
            bridges = json.load(open(OUT))
        except Exception:
            bridges = []

    # FAZA 3: Opus davky
    items = []
    for i in range(len(mem)):
        if i in done:
            continue
        cands = [{"gid": book[j]["gid"], "text": book[j]["text"], "j": int(j)}
                 for j in topk_idx[i]]
        items.append({"mem_idx": i, "mem_text": mem[i]["text"], "cands": cands})

    print(f"[opus] {len(items)} spomienok na posudenie, davka {BATCH}", flush=True)
    gid2book = {b["gid"]: b for b in book}
    prog_f = open(PROG, "a")
    for bi in range(0, len(items), BATCH):
        batch = items[bi:bi + BATCH]
        verdicts = ask_opus(batch)
        vmap = {v.get("mem_idx"): v for v in verdicts if isinstance(v, dict)}
        for it in batch:
            v = vmap.get(it["mem_idx"], {})
            bg = v.get("best_gid")
            strg = float(v.get("strength", 0) or 0)
            if bg is not None and bg in gid2book and strg >= MIN_STRENGTH:
                bk = gid2book[bg]
                bridges.append({
                    "mem_id": mem[it["mem_idx"]].get("id"),
                    "gid": bg, "strength": round(strg, 2),
                    "reason": (v.get("reason") or "")[:200],
                    "mem_text": mem[it["mem_idx"]]["text"][:160],
                    "book_text": bk["text"][:160],
                    "theme": bk["theme"], "layer": bk["layer"],
                })
            prog_f.write(f"{it['mem_idx']}\n")
        prog_f.flush()
        json.dump(bridges, open(OUT, "w"), ensure_ascii=False, indent=1)
        print(f"  davka {bi//BATCH+1}: mostov spolu {len(bridges)}", flush=True)

    prog_f.close()
    print(f"\nOK potvrdenych mostov: {len(bridges)} -> {OUT}")
    # ukazka
    for br in sorted(bridges, key=lambda x: -x["strength"])[:10]:
        print(f"[{br['strength']}] {br['reason']}")
        print(f"   P: {br['mem_text'][:110]}")
        print(f"   K: {br['book_text'][:110]}")


if __name__ == "__main__":
    main()
