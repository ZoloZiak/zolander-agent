#!/usr/bin/env python3
"""_translate_sk_en.py — prelozi SK texty spomienok (len tie v gold paroch) do EN cez Opus.
Cielom je izolovat JAZYK ako konfaund v Gate 2b (HiT=anglicky MiniLM vs multiling Gemma).
ID injektujem lokalne z inputu; model vracia len {id: en_text}. Zapise state/mem_en.json.
"""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/projects/__PROJECT__/toolkit"))
from palantir_client import chat

STATE = os.path.expanduser("~/projects/zolander/state")
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items()}
GOLDS = ["gold_pairs.jsonl", "gold_pairs_gpt.jsonl", "gold_pairs_gemini.jsonl"]

need = set()
for path in GOLDS:
    for l in open(os.path.join(STATE, path), encoding="utf-8"):
        l = l.strip()
        if not l: continue
        g = json.loads(l)
        if not g.get("parents"): continue
        need.add(g["child"]); need.update(g["pool"])
ids = sorted(i for i in need if i in data and "text" in data[i])

out = {}
BATCH = 40
for s in range(0, len(ids), BATCH):
    chunk = ids[s:s+BATCH]
    payload = {str(i): data[i]["text"] for i in chunk}
    prompt = (
        "Translate each Slovak sentence to natural English. These are personal memory facts "
        "about an AI persona and its user. Keep proper names/technical terms as-is. "
        "Return ONLY a JSON object mapping the SAME numeric keys to the English translation, "
        "no commentary.\n\nINPUT JSON:\n" + json.dumps(payload, ensure_ascii=False)
    )
    resp = chat(prompt, model="opus", max_tokens=4000)
    # vytiahni JSON blok
    t = resp.strip()
    a, b = t.find("{"), t.rfind("}")
    d = json.loads(t[a:b+1])
    for k, v in d.items():
        out[int(k)] = v
    print(f"batch {s//BATCH+1}: +{len(d)} (total {len(out)}/{len(ids)})", flush=True)

json.dump(out, open(os.path.join(STATE, "mem_en.json"), "w"), ensure_ascii=False, indent=0)
print("DONE", len(out), "->", os.path.join(STATE, "mem_en.json"))
# kontrola pokrytia
miss = [i for i in ids if i not in out]
print("MISSING:", miss[:20], "count", len(miss))
