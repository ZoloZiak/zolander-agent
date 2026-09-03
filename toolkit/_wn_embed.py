#!/usr/bin/env python3
"""_wn_embed.py — embed WordNet slov cez BEZIACI gemma_embed_server (:8901), mode=document.
Pouziva HTTP daemon (ziadny 2. model v RAM -> ziadny SIGKILL). Zapise state/wn_vecs.json.
"""
import os, json, urllib.request, time

STATE = os.path.expanduser("~/projects/zolander/state")
URL = "http://127.0.0.1:8901/embed"

words = []
for l in open(os.path.join(STATE, "wn_words.jsonl"), encoding="utf-8"):
    l = l.strip()
    if l:
        words.append(json.loads(l)["text"])

def embed_batch(texts):
    body = json.dumps({"texts": texts, "mode": "document"}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["vectors"]

vecs = {}
B = 64
t0 = time.time()
for i in range(0, len(words), B):
    chunk = words[i:i+B]
    for attempt in range(3):
        try:
            vv = embed_batch(chunk)
            break
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    for w, v in zip(chunk, vv):
        vecs[w] = v
    if (i // B) % 10 == 0:
        print(f"{len(vecs)}/{len(words)} ({time.time()-t0:.0f}s)", flush=True)

json.dump(vecs, open(os.path.join(STATE, "wn_vecs.json"), "w"))
print(f"DONE {len(vecs)} vektorov, {time.time()-t0:.0f}s")
