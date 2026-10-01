#!/usr/bin/env python3
"""edge_cluster_consensus.py — dobehni gemini pre #685 (utlo sa) + spocitaj opus∩gemini konsenzus.
Cita state/edge_cluster_verdict.json, doplni gemini/#685, prepise verdikt, vypise konsenzus tabulku."""
import os, sys, json
HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "projects", "zolander", "state")
OUT = os.path.join(STATE, "edge_cluster_verdict.json")
IDX = os.path.join(STATE, "mem_index.jsonl")
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from palantir_client import chat

rows = {}
for l in open(IDX, encoding="utf-8"):
    l=l.strip()
    if l:
        r=json.loads(l); rows[r["id"]]=r

v = json.load(open(OUT, encoding="utf-8"))

SYS = ("Si expert na klasifikaciu is-a taxonomii. IS-A: dieta JE instancia/podtyp rodica, rodic je "
       "ABSTRAKTNEJSI. SUROSENCI: rovnaka uroven abstrakcie, ani jeden nadradeny. Odpovedas VYLUCNE "
       "kompaktnym platnym JSON bez formatovania, ziadny text navyse.")

def build(hub, kids):
    hub_txt = rows[hub]["text"].replace("\n"," ").strip()
    lines=[f'{{"id":{k},"text":"{rows[k]["text"].replace(chr(10)," ").strip()[:200]}"}}' for k in kids]
    return (f'RODIC #{hub}: "{hub_txt}"\n\nDETI: [{",".join(lines)}]\n\n'
            'Pre kazde dieta rozhodni relation "is_a" alebo "sibling" voci rodicovi. '
            'Vrat kompaktny JSON: {"cluster_verdict":"is_a_tree|siblings|mixed","hub_is_true_apex":bool,'
            '"hub_should_be_layer":"L1|L2|L3|same","children":[{"id":int,"relation":"is_a|sibling"}]}')

# dobehni gemini #685
hub=685
kids=v["685"]["children_ids"]
raw=""
try:
    raw=chat(build(hub,kids), model="gemini", max_tokens=8000, system=SYS).strip()
    if raw.startswith("```"):
        raw=raw.split("```",2)[1]
        if raw.startswith("json"): raw=raw[4:]
        raw=raw.strip()
    v["685"]["gemini"]={"ok":True,"parsed":json.loads(raw),"raw_len":len(raw),"retry":True}
    print("gemini #685 retry OK")
except Exception as e:
    v["685"]["gemini"]={"ok":False,"error":f"{type(e).__name__}: {e}","raw":raw[:300],"retry":True}
    print("gemini #685 retry FAIL:", e)

json.dump(v, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

# konsenzus per hub
def rels(node):
    if not node.get("ok"): return {}
    return {c["id"]: c.get("relation") for c in node["parsed"].get("children",[])}

for hub in ("685","558"):
    o=rels(v[hub]["opus"]); g=rels(v[hub]["gemini"])
    both=set(o)&set(g)
    agree_sib=[i for i in both if o[i]=="sibling" and g[i]=="sibling"]
    agree_isa=[i for i in both if o[i]=="is_a" and g[i]=="is_a"]
    disp=[i for i in both if o[i]!=g[i]]
    ov=v[hub]["opus"]["parsed"] if v[hub]["opus"]["ok"] else {}
    gv=v[hub]["gemini"]["parsed"] if v[hub]["gemini"]["ok"] else {}
    print(f"\n=== HUB #{hub} ===")
    print(f"  opus: verdict={ov.get('cluster_verdict')} apex={ov.get('hub_is_true_apex')} layer->{ov.get('hub_should_be_layer')}")
    print(f"  gem : verdict={gv.get('cluster_verdict')} apex={gv.get('hub_is_true_apex')} layer->{gv.get('hub_should_be_layer')}")
    print(f"  deti spolu porovnatelne: {len(both)}")
    print(f"  ZHODA sibling (->related): {len(agree_sib)}  {sorted(agree_sib)}")
    print(f"  ZHODA is_a (necha parent): {len(agree_isa)}  {sorted(agree_isa)}")
    print(f"  SPORNE (opus!=gem):        {len(disp)}  {sorted(disp)}")
