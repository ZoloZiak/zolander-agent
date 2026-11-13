#!/usr/bin/env python3
"""build_geom_data.py — zber dat pre geometricky falzifikacny test (KROK B).

Pre CELY korpus (mem_index.jsonl): Gemma768 uhol (daemon :8901) + opus polomer
(abstraktnost 0-1, kalibrovany model z gate A). Uklada RESUMOVATELNE do
state/geom_data.json (507 opus volani -> nech prezije prerusenie).

Tieto opus skore su DVOJUCELOVE: (1) polomer pre hyperbola/product-space test,
(2) treningove data pre Option 2 radialnu hlavu Gemma768->r. Nic sa neplytva."""
import json, os, sys, urllib.request, time

sys.path.insert(0, os.path.expanduser("~/projects/zolo2.0/toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from llm_client import chat

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "geom_data.json")
GPORT = os.environ.get("GEMMA_EMBED_PORT", "8901")

SYSTEM = (
    "Si merací aparát na ABSTRAKTNOSŤ textu. Abstraktnosť = ako všeobecný/nadradený je "
    "výrok. 0.0 = úplne konkrétny fakt/udalosť/riadok kódu. 1.0 = najvšeobecnejší princíp/"
    "svetonázor. Medzi tým plynulá škála. Skóruj IBA abstraktnosť, NIE dôležitosť. Vráť čistý JSON."
)

def gemma_embed(texts):
    body = json.dumps({"texts": texts, "mode": "document"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{GPORT}/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=120)
    return json.loads(r.read())["vectors"]

def opus_score(items):
    lines = "\n".join(f'{it["id"]}: {(it["text"] or "")[:220]}' for it in items)
    prompt = ('Oskóruj abstraktnosť (0.0-1.0) KAŽDÉHO výroku. Vráť JSON objekt '
              '{"<id>": <float>, ...} pre VŠETKY id nižšie, nič iné:\n\n' + lines)
    txt = chat(prompt, model="opus", max_tokens=1500, system=SYSTEM).strip()
    a, b = txt.find("{"), txt.rfind("}")
    return {int(k): float(v) for k, v in json.loads(txt[a:b+1]).items()}

def main():
    rows = []
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if l:
            r = json.loads(l)
            if (r.get("text") or "").strip():
                rows.append(r)
    print(f"[build] korpus={len(rows)}", file=sys.stderr)

    # resume
    data = {}
    if os.path.exists(OUT):
        data = {int(k): v for k, v in json.load(open(OUT, encoding="utf-8")).items()}
        print(f"[build] resume: uz mam {len(data)}", file=sys.stderr)

    # 1) Gemma uhol pre chybajuce
    need_g = [r for r in rows if r["id"] not in data or "gemma" not in data.get(r["id"], {})]
    for i in range(0, len(need_g), 32):
        chunk = need_g[i:i+32]
        vecs = gemma_embed([r["text"][:400] for r in chunk])
        for r, v in zip(chunk, vecs):
            data.setdefault(r["id"], {})
            data[r["id"]].update({"id": r["id"], "layer": r.get("layer"),
                                  "text": r["text"][:220], "gemma": v})
        print(f"[gemma] {min(i+32,len(need_g))}/{len(need_g)}", file=sys.stderr)
    json.dump({str(k): v for k, v in data.items()}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False)

    # 2) opus polomer pre chybajuce (resumovatelne po batchoch)
    need_r = [r for r in rows if "r_opus" not in data.get(r["id"], {})]
    print(f"[opus] treba oskorovat: {len(need_r)}", file=sys.stderr)
    for i in range(0, len(need_r), 15):
        chunk = need_r[i:i+15]
        for attempt in range(2):
            try:
                sc = opus_score([{"id": r["id"], "text": r["text"]} for r in chunk])
                for r in chunk:
                    if r["id"] in sc:
                        data[r["id"]]["r_opus"] = sc[r["id"]]
                break
            except Exception as e:
                if attempt == 1:
                    print(f"  ! opus batch fail: {e}", file=sys.stderr)
        json.dump({str(k): v for k, v in data.items()}, open(OUT, "w", encoding="utf-8"),
                  ensure_ascii=False)
        print(f"[opus] {min(i+15,len(need_r))}/{len(need_r)}", file=sys.stderr)

    done = sum(1 for v in data.values() if "gemma" in v and "r_opus" in v)
    print(json.dumps({"total": len(rows), "complete": done, "out": OUT}, ensure_ascii=False))

if __name__ == "__main__":
    main()
