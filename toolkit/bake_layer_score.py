#!/usr/bin/env python3
"""bake_layer_score.py — zapec opus abstraktnost (geom_data.json r_opus) do mem_index.jsonl
ako pole 'layer_score'. Atomicky (temp+rename), zdroj pravdy = index (poradie/ID zachovane)."""
import json, os, sys

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
DATA = os.path.join(STATE, "geom_data.json")
TMP = IDX + ".tmp-bake"

data = {int(k): v for k, v in json.load(open(DATA, encoding="utf-8")).items()}

rows = []
for line in open(IDX, encoding="utf-8"):
    line = line.strip()
    if line:
        rows.append(json.loads(line))

n_in = len(rows)
ids_in = [r["id"] for r in rows]
baked = 0
missing = []
for r in rows:
    rid = r["id"]
    d = data.get(rid)
    if d and "r_opus" in d:
        r["layer_score"] = round(float(d["r_opus"]), 4)
        baked += 1
    else:
        missing.append(rid)

# zapis atomicky
with open(TMP, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# verifikacia PRED rename
chk = []
for line in open(TMP, encoding="utf-8"):
    line = line.strip()
    if line:
        chk.append(json.loads(line))
n_out = len(chk)
ids_out = [r["id"] for r in chk]

if n_out != n_in or ids_out != ids_in:
    print(json.dumps({"ABORT": True, "n_in": n_in, "n_out": n_out,
                      "ids_match": ids_out == ids_in}), file=sys.stderr)
    os.remove(TMP)
    sys.exit(1)

os.replace(TMP, IDX)
print(json.dumps({
    "n_in": n_in, "n_out": n_out, "ids_preserved": ids_out == ids_in,
    "baked": baked, "missing_count": len(missing), "missing_ids": missing[:20],
}, ensure_ascii=False))
