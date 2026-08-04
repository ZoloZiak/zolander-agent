#!/usr/bin/env python3
"""zol_mem.py — pamäť Zolandera (F2, v2 čistý Lorentz). PLAN §14 čistý rez.

ZMENA oproti v1: koniec dvojkolajnosti cosine768 + toy-lorentz129.
Teraz JEDNA natívna 129D Lorentz reprezentácia z YAR v5 (embed_yar.py).
Polomer/hĺbku určuje MODEL (naučená norma v LorentzMRLHead), NIE tabuľka LAYER_R.

Štyri kolekcie podľa druhu pamäte (kognitívna trojica semantic/episodic/
procedural + naša identity), všetky lorentz 129:
  zol_semantic   — fakty, poznatky, princípy (destiláty)
  zol_episodic   — zážitky, udalosti, čo sa v sesii stalo (zabúda cez decay)
  zol_procedural — naučené postupy: "ako sa rieši X", "keď zlyhá Y, sprav Z"
  zol_identity   — jadro identity, hodnoty, kto Zolander je (nezabúda)

Pozn.: procedurálna pamäť je aj v Hermes skilloch (načítané pravidlá); táto
kolekcia je pre postupy, ktoré má Zolander vedieť sémanticky VYHĽADAŤ, nie len
keď sa skill načíta.

Hippocampus NIE je kolekcia — je to PROCES konsolidácie v 'sen' (F4,
zolander_dream.py): episodic L0 -> destilát -> semantic/procedural L1 + návrh
čo zabudnúť. Kolekcie = kde spomienky ležia; hippocampus = čo ich presúva.

Vrstvy zostávajú ako METADATA (nie polomer):
  layer: L0 (working/epizoda) | L1 (destilát) | L2 (jadro) | L3 (meta-rámec)
  salience(0..1), confidence(0..1) — pre decay/konsolidáciu v 'sen' (F4)

Použitie:
  VPY=/Users/__USER__/zolander/.venv-yar/bin/python
  echo '{"text":"...", "kind":"semantic", "layer":"L1"}' | $VPY zol_mem.py remember
  echo '{"query":"...", "kind":"semantic", "topk":5}'    | $VPY zol_mem.py recall
  $VPY zol_mem.py decay
  $VPY zol_mem.py stats
  $VPY zol_mem.py init      # vytvorí 3 kolekcie (idempotentne)
"""
import os
import sys
import json
import time
import subprocess

HOME = os.path.expanduser("~")
NODE = "/Users/__USER__/Applications/homebrew/bin/node"
HS = "/Users/__USER__/zolo2.0/toolkit/hs.mjs"
STATE = os.path.join(HOME, "zolander/state")
IDFILE = os.path.join(STATE, "mem_next_id.txt")
NODE_ENV = dict(os.environ, NODE_PATH="/Users/__USER__/.npm/_npx/9e13365ae4a6529c/node_modules")

DIM = 129
METRIC = "lorentz"
KIND_COL = {
    "semantic": "zol_semantic",
    "episodic": "zol_episodic",
    "identity": "zol_identity",
    "procedural": "zol_procedural",
}
DEFAULT_KIND = "episodic"

# layer -> decay rýchlosť salience za deň (L2/L3 = jadro/princíp, nezabúdajú)
LAYER_DECAY = {"L3": 0.0, "L2": 0.0, "L1": 0.01, "L0": 0.08}

# YAR embedder (natívny 129D Lorentz) — import z rovnakého toolkitu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embed_yar import embed_one  # noqa: E402


def col_for(kind):
    return KIND_COL.get(kind, KIND_COL[DEFAULT_KIND])


def next_id():
    os.makedirs(STATE, exist_ok=True)
    cur = 1
    if os.path.exists(IDFILE):
        cur = int(open(IDFILE).read().strip() or "1")
    with open(IDFILE, "w") as f:
        f.write(str(cur + 1))
    return cur


def hs(cmd, *args, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd} zlyhal: " + p.stderr[-500:])
    out = p.stdout.strip()
    return json.loads(out) if out else None


def cmd_init():
    """Vytvorí 3 Lorentz kolekcie (idempotentne — ak existujú, hs vráti chybu, ignorujeme)."""
    made = {}
    for kind, col in KIND_COL.items():
        try:
            hs("create", col, DIM, METRIC)
            made[col] = "created"
        except RuntimeError as e:
            made[col] = "exists?" if ("exist" in str(e).lower() or "already" in str(e).lower()) else f"ERR {e}"
    print(json.dumps({"init": made, "dim": DIM, "metric": METRIC}, ensure_ascii=False, indent=2))


def cmd_remember():
    obj = json.loads(sys.stdin.read())
    text = obj["text"]
    kind = obj.get("kind", DEFAULT_KIND)
    layer = obj.get("layer", "L0")
    salience = float(obj.get("salience", 0.5))
    confidence = float(obj.get("confidence", 0.7))
    source = obj.get("source", "session")
    project = obj.get("project", "zolander")
    links = obj.get("links", "")
    ts = obj.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S")

    mid = obj.get("id") or next_id()
    vec = embed_one(text)  # natívny 129D Lorentz
    col = col_for(kind)

    meta = {
        "kind": kind, "layer": layer, "salience": round(salience, 3),
        "confidence": round(confidence, 3), "source": source,
        "project": project, "ts": ts, "links": links,
        "text": text[:300],
    }
    rec = json.dumps({"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n"
    hs("insert", col, stdin=rec)

    # lokálny index pre decay/konsolidáciu (DB nemá hromadný listing)
    with open(os.path.join(STATE, "mem_index.jsonl"), "a") as f:
        f.write(json.dumps({"id": mid, "col": col, "kind": kind, "layer": layer,
                            "salience": salience, "confidence": confidence,
                            "ts": ts, "text": text[:120]}, ensure_ascii=False) + "\n")
    print(json.dumps({"remembered": mid, "kind": kind, "col": col, "layer": layer},
                     ensure_ascii=False))


def cmd_recall():
    obj = json.loads(sys.stdin.read())
    query = obj["query"]
    topk = int(obj.get("topk", 5))
    kind = obj.get("kind")  # None => hľadaj vo všetkých troch
    vec = embed_one(query)
    cols = [col_for(kind)] if kind else list(KIND_COL.values())
    results = []
    for col in cols:
        res = hs("search", col, topk, stdin=json.dumps({"vector": vec}))
        for r in (res or []):
            r["col"] = col
            results.append(r)
    # menšia Lorentzova vzdialenosť = bližšie; zoraď a vezmi topk
    results.sort(key=lambda r: r.get("distance", 9e9))
    print(json.dumps(results[:topk], ensure_ascii=False, indent=2))


def cmd_stats():
    out = {}
    for col in KIND_COL.values():
        try:
            out[col] = hs("stats", col)
        except RuntimeError as e:
            out[col] = {"error": str(e)[-200:]}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_decay():
    """Salience decay podľa veku a vrstvy. Read-only voči DB — navrhne
    konsolidáciu (L0->L1) a zabudnutie (pod prah) pre 'sen' (F4), ktorý rozhodne."""
    now = time.time()
    suggestions = {"forget": [], "promote": [], "kept": 0}
    idx_path = os.path.join(STATE, "mem_index.jsonl")
    if not os.path.exists(idx_path):
        print(json.dumps({"note": "žiadny mem_index.jsonl — decay no-op", "suggestions": suggestions}, ensure_ascii=False, indent=2))
        return
    rows = [json.loads(l) for l in open(idx_path) if l.strip()]
    out = []
    for r in rows:
        layer = r.get("layer", "L0")
        sal = float(r.get("salience", 0.5))
        ts = r.get("ts", "")
        try:
            age_days = (now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 86400.0
        except Exception:
            age_days = 0.0
        new_sal = max(0.0, sal - LAYER_DECAY.get(layer, 0.08) * age_days)
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
    {
        "init": cmd_init,
        "remember": cmd_remember,
        "recall": cmd_recall,
        "decay": cmd_decay,
        "stats": cmd_stats,
    }.get(cmd, lambda: (_ for _ in ()).throw(SystemExit(f"neznámy príkaz: {cmd}")))()


if __name__ == "__main__":
    main()
