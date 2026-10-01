#!/usr/bin/env python3
"""verify_zombies.py — over ci 79/261/664/666 su REALNE zombie alebo len
hlbsie v ranku (Lorentz union je neuplny 513/611 -> riziko false-positive).

Metoda: vezmi text z indexu (ak tam je) alebo z Gemma meta, embedni cez YAR,
cielene hladaj v zol_mem. Ak sa ID vrati v top-5 na SVOJ VLASTNY text -> ZIVY
v Lorentz (false-positive guardu). Ak sa nevrati ani na vlastny text -> realne
prec z Lorentz (zombie).
"""
import os, sys, json, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT
from embed_yar import embed_one

STATE = os.path.join(ZROOT, "state")
CAND = [79, 261, 664, 666]


def hs(cmd, *a, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(x) for x in a]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-200:])
    return json.loads(p.stdout.strip()) if p.stdout.strip() else None


def gemma_embed(q):
    body = json.dumps({"texts": [q], "mode": "query"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8901/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["vectors"][0]


# texty z indexu
idx = {}
for line in open(os.path.join(STATE, "mem_index.jsonl"), encoding="utf-8"):
    line = line.strip()
    if line:
        r = json.loads(line)
        idx[r["id"]] = r.get("text", "")

# texty z Gemma (pre tie co nie su v indexe)
gem_txt = {}
for q in ["identita HMAC podpis test zmazat", "pamat recall veducko",
          "gabber hardcore", "zdravie lekar", "sandbox mac gateway"]:
    try:
        for r in (hs("search", "zol_mem_gemma", 300, stdin=json.dumps({"vector": gemma_embed(q)})) or []):
            m = r.get("meta", {}) or {}
            if r.get("id") in CAND:
                gem_txt[r["id"]] = m.get("text", "")
    except Exception as e:
        print(f"  ! gemma dotaz: {e}", file=sys.stderr)

for cid in CAND:
    text = idx.get(cid) or gem_txt.get(cid) or ""
    in_index = cid in idx
    if not text:
        print(f"[{cid}] BEZ textu (ani index ani gemma) -> neda sa overit cielene")
        continue
    # cielena Lorentz search na vlastny text
    res = hs("search", "zol_mem", 5, stdin=json.dumps({"vector": embed_one(text)})) or []
    ids = [r.get("id") for r in res]
    alive = cid in ids
    print(f"[{cid}] v_indexe={in_index} | vlastny-text Lorentz top5={ids} | "
          f"{'ZIVY (false-positive guardu)' if alive else 'REALNE PREC z Lorentz (zombie)'}")
    print(f"      text: {text[:90]}")
