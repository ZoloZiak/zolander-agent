#!/usr/bin/env python3
"""OSTRY LLM test llm_cluster cez realny Opus. Pokryva OBA smery zlyhania
cisteho embeddingu (PLAN §20):
  MERGE: 2 cross-domain prejavy TOHO ISTEHO vzorca (odkladanie) -> maju byt SPOLU
  SPLIT: 2 nesuvisiace principy -> NEMAJU byt v jednej skupine s odkladanim
Ocakavanie: skupina {kamera, gitara} spolu; {odolnost pamate}, {rano cvicenie}
mimo nej (samostatne alebo vlastne).
"""
import sys, subprocess, json, math
sys.path.insert(0, "/Users/__USER__/zolander/toolkit")
sys.path.insert(0, "/Users/__USER__/zolo2.0/toolkit")

VENV_YAR = "/Users/__USER__/zolander/.venv-yar/bin/python"
EMBED = "/Users/__USER__/zolander/toolkit/embed_yar.py"

def embed_many(texts):
    payload = "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                      for i, t in enumerate(texts))
    p = subprocess.run([VENV_YAR, EMBED], input=payload, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("embed zlyhal: " + p.stderr[-300:])
    by = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            o = json.loads(line); by[o["id"]] = o["vector"]
    return [by[i] for i in range(len(texts))]

def ldist(a, b):
    mink = -a[0]*b[0] + sum(x*y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0: val = 1.0
    return math.acosh(val)

from cluster_llm import llm_cluster

rows = [
    {"id": 1, "text": "Kupil som drahu kameru, mesiac nadseno fotil, teraz lezi v skrini."},
    {"id": 2, "text": "Zacal som sa ucit na gitare, po troch tyzdnoch zapada prachom v rohu."},
    {"id": 3, "text": "Pamat Zolandera prezila vypadok procesu a obnovila sa z indexu."},
    {"id": 4, "text": "Kazde rano si davam kavu presne o siedmej, je to moj rituak."},
]
print("=== VSTUP ===")
for r in rows:
    print(f"  [{r['id']}] {r['text']}")

# co by spravil cisty embedding (referencia)
print("\n=== EMBEDDING vzdialenosti (referencia, preco embedding zlyha) ===")
vecs = embed_many([r["text"] for r in rows])
for i in range(len(rows)):
    for j in range(i+1, len(rows)):
        print(f"  ldist({rows[i]['id']},{rows[j]['id']}) = {ldist(vecs[i], vecs[j]):.4f}")

print("\n=== LLM CLUSTER (Opus) ===")
groups = llm_cluster(rows, embed_many, ldist, 1.0, model="opus",
                     log_fn=lambda m: print("  [log]", m))
for gi, g in enumerate(groups):
    print(f"  skupina {gi}: {[r['id'] for r in g]}  -> {[r['text'][:40] for r in g]}")

# vyhodnotenie: su 1 a 2 (kamera+gitara) v ROVNAKEJ skupine?
def group_of(pid):
    for gi, g in enumerate(groups):
        if any(r["id"] == pid for r in g):
            return gi
    return -1
merge_ok = group_of(1) == group_of(2)
split_ok = group_of(3) != group_of(1) and group_of(4) != group_of(1)
print("\n=== VYHODNOTENIE ===")
print("  MERGE (kamera+gitara spolu):", "PASS" if merge_ok else "FAIL")
print("  SPLIT (pamat/rituak MIMO odkladania):", "PASS" if split_ok else "FAIL")
print("\nCELKOVO:", "PASS" if (merge_ok and split_ok) else "FAIL")
