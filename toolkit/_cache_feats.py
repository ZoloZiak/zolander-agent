#!/usr/bin/env python3
"""_cache_feats.py — zacacheuj Gemma-EN + HiT-EN vektory na disk RAZ.
Maly batch + retry (daemon spadol raz). Vystup: state/feat_gemma_en.json, state/feat_hit_en.json.
Tym je nasledny trening odolny voci padu daemona (cita hotove JSON).
"""
import os, sys, json, time
os.environ.pop("HF_HUB_OFFLINE", None); os.environ.pop("TRANSFORMERS_OFFLINE", None)
import numpy as np, urllib.request

STATE = os.path.expanduser("~/projects/zolander/state")
EN = {int(k): v for k, v in json.load(open(os.path.join(STATE, "mem_en.json"))).items()}
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items()}
ids = sorted(i for i in EN if i in data)
print(f"ids={len(ids)}", flush=True)

def gemma_embed(texts, tries=5):
    for a in range(tries):
        try:
            req = urllib.request.Request("http://127.0.0.1:8901/embed",
                data=json.dumps({"texts": texts, "mode": "document"}).encode(),
                headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=180))["vectors"]
        except Exception as e:
            print(f"  retry {a+1}: {repr(e)[:60]}", flush=True); time.sleep(4)
    raise RuntimeError("gemma daemon nedostupny")

gpath = os.path.join(STATE, "feat_gemma_en.json")
if not os.path.exists(gpath):
    GEM = {}
    B = 64
    for s in range(0, len(ids), B):
        ch = ids[s:s+B]
        vs = gemma_embed([EN[i] for i in ch])
        for k, i in enumerate(ch): GEM[i] = vs[k]
        print(f"  gemma {min(s+B,len(ids))}/{len(ids)}", flush=True)
    json.dump({str(i): GEM[i] for i in GEM}, open(gpath, "w"))
    print("SAVED", gpath, flush=True)
else:
    print("EXISTS", gpath, flush=True)

hpath = os.path.join(STATE, "feat_hit_en.json")
if not os.path.exists(hpath):
    from hierarchy_transformers import HierarchyTransformer
    hit = HierarchyTransformer.from_pretrained("Hierarchy-Transformers/HiT-MiniLM-L12-WordNetNoun")
    hemb = hit.encode([EN[i] for i in ids], convert_to_numpy=True, show_progress_bar=False)
    json.dump({str(ids[k]): hemb[k].tolist() for k in range(len(ids))}, open(hpath, "w"))
    print("SAVED", hpath, hemb.shape, flush=True)
else:
    print("EXISTS", hpath, flush=True)
print("DONE", flush=True)
