#!/usr/bin/env python3
"""zol_mem.py — pamat Zolandera (F2). Dualna reprezentacia + vrstvy cez metadata.

Kazda spomienka zije v DVOCH kolekciach pod ROVNAKYM id:
  zol_sem  (cosine 768)  — presny semanticky recall
  zol_hier (lorentz 129) — hierarchia / abstrakcia / zoom-out

Vrstvy NIE su kolekcie — su to metadata:
  kind:  episodic | semantic | procedural | identity
  layer: L0 (working/epizoda, zabuda) | L1 (destilat) | L2 (jadro, nezabuda)
Hyperbolicky polomer r sa odvodi od layer: L2 blizko korena (abstraktne, r male),
L0 na okraji (konkretne, r velke) — presne ako to_lorentz.py mapuje hlbku.

Metadata na kazdom zazname:
  kind, layer, salience(0..1), confidence(0..1), source, project, ts, text, links

Pouzitie:
  VPY=/Users/ziak.z/.local/share/uv/tools/vmlx/bin/python
  export NODE_PATH=/Users/ziak.z/.npm/_npx/9e13365ae4a6529c/node_modules
  echo '{"text":"...", "kind":"episodic", "layer":"L0", ...}' | $VPY zol_mem.py remember
  echo '{"query":"...", "topk":5}' | $VPY zol_mem.py recall
  $VPY zol_mem.py decay            # salience decay + navrhy na konsolidaciu/zabudnutie
  $VPY zol_mem.py stats

Design pozn.: embed cez embed.py logiku (mlx GPU). Zapis/citanie cez hs.mjs most.
"""
import os
import sys
import json
import math
import time
import subprocess

HOME = os.path.expanduser("~")
NODE = "/Users/ziak.z/Applications/homebrew/bin/node"
HS = "/Users/ziak.z/zolo2.0/toolkit/hs.mjs"
VPY = "/Users/ziak.z/.local/share/uv/tools/vmlx/bin/python"
EMBED = "/Users/ziak.z/zolo2.0/toolkit/embed.py"
STATE = os.path.join(HOME, "zolander/state")
IDFILE = os.path.join(STATE, "mem_next_id.txt")
NODE_ENV = dict(os.environ, NODE_PATH="/Users/ziak.z/.npm/_npx/9e13365ae4a6529c/node_modules")

COL_SEM = "zol_sem"
COL_HIER = "zol_hier"
TRUNC = 128

# layer -> zakladny hyperbolicky polomer (male = blizko korena = abstraktne/jadro)
LAYER_R = {"L2": 0.4, "L1": 1.2, "L0": 2.2}
# layer -> decay rychlost salience za den (L2 nezabuda)
LAYER_DECAY = {"L2": 0.0, "L1": 0.01, "L0": 0.08}


def next_id():
    os.makedirs(STATE, exist_ok=True)
    cur = 1
    if os.path.exists(IDFILE):
        cur = int(open(IDFILE).read().strip() or "1")
    with open(IDFILE, "w") as f:
        f.write(str(cur + 1))
    return cur


def embed_text(text):
    """Vrati 768d vektor cez GPU embed.py."""
    p = subprocess.run(
        [VPY, EMBED],
        input=json.dumps({"id": 1, "text": text}) + "\n",
        capture_output=True, text=True,
        env=dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"),
    )
    if p.returncode != 0:
        raise RuntimeError("embed zlyhal: " + p.stderr[-500:])
    for line in p.stdout.splitlines():
        line = line.strip()
        if line:
            return json.loads(line)["vector"]
    raise RuntimeError("embed nevratil vektor")


def to_lorentz(vec768, r):
    """Matryoshka 128 + L2 norm + exp-map na hyperboloid pri polomere r -> 129d."""
    u = vec768[:TRUNC]
    nrm = math.sqrt(sum(x * x for x in u)) or 1.0
    u = [x / nrm for x in u]
    ch, sh = math.cosh(r), math.sinh(r)
    return [ch] + [sh * x for x in u]


def hs_insert(col, records):
    """records: list of {id, vector, meta}."""
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    p = subprocess.run([NODE, HS, "insert", col], input=payload,
                       capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError("hs insert zlyhal: " + p.stderr[-500:])
    return json.loads(p.stdout.strip())


def hs_search(col, vector, topk):
    p = subprocess.run([NODE, HS, "search", col, str(topk)],
                       input=json.dumps({"vector": vector}),
                       capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError("hs search zlyhal: " + p.stderr[-500:])
    return json.loads(p.stdout.strip())


def hs_stats(col):
    p = subprocess.run([NODE, HS, "stats", col],
                       capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        return {"error": p.stderr[-200:]}
    return json.loads(p.stdout.strip())


def cmd_remember():
    obj = json.loads(sys.stdin.read())
    text = obj["text"]
    kind = obj.get("kind", "episodic")
    layer = obj.get("layer", "L0")
    salience = float(obj.get("salience", 0.5))
    confidence = float(obj.get("confidence", 0.7))
    source = obj.get("source", "session")
    project = obj.get("project", "zolander")
    links = obj.get("links", "")
    ts = obj.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S")

    mid = obj.get("id") or next_id()
    vec = embed_text(text)
    r = LAYER_R.get(layer, 2.2)
    lor = to_lorentz(vec, r)

    meta = {
        "kind": kind, "layer": layer, "salience": round(salience, 3),
        "confidence": round(confidence, 3), "source": source,
        "project": project, "ts": ts, "links": links,
        "text": text[:300],
    }
    hs_insert(COL_SEM, [{"id": mid, "vector": vec, "meta": meta}])
    hs_insert(COL_HIER, [{"id": mid, "vector": lor, "meta": dict(meta, r=round(r, 3))}])
    # lokalny index pre decay/konsolidaciu (DB nema hromadny listing)
    with open(os.path.join(STATE, "mem_index.jsonl"), "a") as f:
        f.write(json.dumps({"id": mid, "kind": kind, "layer": layer,
                            "salience": salience, "confidence": confidence,
                            "ts": ts, "text": text[:120]}, ensure_ascii=False) + "\n")
    print(json.dumps({"remembered": mid, "kind": kind, "layer": layer, "r": round(r, 3)},
                     ensure_ascii=False))


def cmd_recall():
    obj = json.loads(sys.stdin.read())
    query = obj["query"]
    topk = int(obj.get("topk", 5))
    mode = obj.get("mode", "sem")  # sem = presny recall, hier = abstraktny/zoom-out
    vec = embed_text(query)
    if mode == "hier":
        r = LAYER_R.get(obj.get("layer", "L0"), 2.2)
        res = hs_search(COL_HIER, to_lorentz(vec, r), topk)
    else:
        res = hs_search(COL_SEM, vec, topk)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_stats():
    out = {c: hs_stats(c) for c in (COL_SEM, COL_HIER)}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_decay():
    """Salience decay podla veku a vrstvy. Navrhne konsolidaciu (L0->L1) a
    zabudnutie (salience pod prah). NEMENI DB sam — vypise navrhy pre 'sen' (F4),
    ktory rozhodne. Zamerne read-only: destruktivne akcie az po rozhodnuti."""
    now = time.time()
    suggestions = {"forget": [], "promote": [], "kept": 0}
    # nacitaj vsetky body zo sem kolekcie cez stats/get nie je hromadne dostupne,
    # preto pracujeme s lokalnym indexom ak existuje; inak len report.
    idx_path = os.path.join(STATE, "mem_index.jsonl")
    if not os.path.exists(idx_path):
        print(json.dumps({"note": "ziadny lokalny mem_index.jsonl — decay je no-op kym loop (F3) nezacne indexovat zapisy", "suggestions": suggestions}, ensure_ascii=False, indent=2))
        return
    rows = []
    for line in open(idx_path):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    out = []
    for r in rows:
        layer = r.get("layer", "L0")
        sal = float(r.get("salience", 0.5))
        ts = r.get("ts", "")
        try:
            age_days = (now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 86400.0
        except Exception:
            age_days = 0.0
        decay = LAYER_DECAY.get(layer, 0.08) * age_days
        new_sal = max(0.0, sal - decay)
        r["salience"] = round(new_sal, 3)
        if layer == "L0" and new_sal < 0.15:
            suggestions["forget"].append(r["id"])
        elif layer == "L0" and new_sal > 0.7 and age_days > 3:
            suggestions["promote"].append(r["id"])
        else:
            suggestions["kept"] += 1
        out.append(r)
    with open(idx_path, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(suggestions, ensure_ascii=False, indent=2))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "remember":
        cmd_remember()
    elif cmd == "recall":
        cmd_recall()
    elif cmd == "decay":
        cmd_decay()
    elif cmd == "stats":
        cmd_stats()
    else:
        print("neznamy prikaz: " + cmd, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
