#!/usr/bin/env python3
"""_wn_prep.py — WordNet MultiHop-HardNegatives-Pairs -> {child,parents,pool} + slova na embed.

Cielom je Gate 2a: krivka ucenia Lorentz hlavy na REALNYCH WordNet is-a paroch (nie Opus,
nie cirkularita). Pripravi gold-like strukturu kompatibilnu s train_lorentz_head.py:
  {child, parents:[pos], pool:[pos+hard_negs]}
Deti train/test DISJUNKTNE. Zapise:
  state/wn_gold.json          (train_gold, test_gold)
  state/wn_words.jsonl        ({id,text} unikatne slova pre embed.py; id == slovo)
"""
import os, json, random
from collections import defaultdict
from datasets import load_dataset

STATE = os.path.expanduser("~/projects/zolander/state")
random.seed(29)

ds = load_dataset("Hierarchy-Transformers/WordNetNoun", "MultiHop-HardNegatives-Pairs")
# zgrupuj train split podla dietata
pos = defaultdict(set)   # child -> set(true parents, label=1)
neg = defaultdict(set)   # child -> set(hard negs, label=0)
for row in ds["train"]:
    c, p, y = row["child"], row["parent"], row["label"]
    (pos if y == 1 else neg)[c].add(p)

# ponechaj deti s aspon 1 pozitivom a aspon 3 negativmi
children = [c for c in pos if len(pos[c]) >= 1 and len(neg[c]) >= 3]
random.shuffle(children)

# kap: dost na krivku ucenia, ale embed rozumny (~ par tisic slov)
N_TRAIN, N_TEST = 1200, 400
children = children[: N_TRAIN + N_TEST]
train_ch = set(children[:N_TRAIN])
test_ch = set(children[N_TRAIN:])

def build(cset):
    out = []
    for c in cset:
        pp = sorted(pos[c])
        nn = sorted(neg[c])
        random.shuffle(nn)
        pool = pp + nn[:8]          # pos + max 8 hard negs
        if len(pool) < 2:
            continue
        out.append({"child": c, "parents": pp, "pool": pool})
    return out

train_gold = build(train_ch)
test_gold = build(test_ch)

# unikatne slova (deti + vsetky pool rodicia)
words = set()
for g in train_gold + test_gold:
    words.add(g["child"])
    words.update(g["pool"])

with open(os.path.join(STATE, "wn_gold.json"), "w", encoding="utf-8") as f:
    json.dump({"train": train_gold, "test": test_gold}, f)
with open(os.path.join(STATE, "wn_words.jsonl"), "w", encoding="utf-8") as f:
    for w in sorted(words):
        f.write(json.dumps({"id": w, "text": w}) + "\n")

print(f"train_gold={len(train_gold)}  test_gold={len(test_gold)}  unique_words={len(words)}")
print("priklad:", train_gold[0])
