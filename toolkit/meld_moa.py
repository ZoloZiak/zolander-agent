#!/usr/bin/env python3
"""MELD admission cez Mixture-of-Agents (3 LLM cross-check).

Pre grey-zone páry (cos_dist 0.15..0.40 — tie čo dnešný near-exact gate NErieši)
spustí 3 nezávislé laby (Opus + GPT-5 + Gemini) na klasifikáciu vzťahu:
  MERGE    — ten istý fakt, jeden je parafráza/nadmnožina -> zlúčiť
  RELATE   — príbuzné ale odlišné -> hrana, ponechať oba
  CONFLICT — protirečia si -> označiť, NEadjudikovať ticho
  DISTINCT — nezávislé -> nič

Cross-lab (nie self-konzistencia 1 modelu): konsenzus = všetci 3 rovnako;
majorita = 2/3; split = všetci rôzne (-> human review).

NIČ NEMAŽE, NIČ NEZLUČUJE. Píše len NÁVRHY do state/meld_proposals.jsonl.
Writeback je DEŠTRUKTÍVNY -> schvaľuje vedúcko (dream-vzor: read-only, human ráno).

Spusti: .venv-yar/bin/python toolkit/meld_moa.py [N]     (N = počet párov, default 12)
"""
import os
import sys
import json
import re

ROOT = os.path.expanduser("~/projects/zolander")
STATE = os.path.join(ROOT, "state")
NPZ = os.path.join(STATE, "gemma_all_nodes.npz")
IDX = os.path.join(STATE, "mem_index.jsonl")
OUT = os.path.join(STATE, "meld_proposals.jsonl")
sys.path.insert(0, os.path.expanduser("~/projects/zolo2.0/toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)

LABS = ["opus", "gpt", "gemini"]
VERDICTS = {"MERGE", "RELATE", "CONFLICT", "DISTINCT"}

PROMPT = """Si pamäťový admission klasifikátor. Dostaneš DVA pamäťové záznamy toho istého AI agenta.
Klasifikuj ich vzťah PRESNE jedným slovom a stručným dôvodom.

Kategórie:
- MERGE: hovoria ten istý fakt; jeden je parafráza alebo nadmnožina druhého. Zlúčiť do jedného.
- RELATE: príbuzné, ale odlišné fakty. Ponechať oba, spojiť hranou.
- CONFLICT: protirečia si (nedajú byť oba pravda naraz). Ponechať oba, označiť na rozhodnutie.
- DISTINCT: nezávislé, len povrchná podobnosť slov. Netreba nič.

Záznam A: {a}
Záznam B: {b}

Odpovedz IBA validným JSON na jednom riadku: {{"verdict":"MERGE|RELATE|CONFLICT|DISTINCT","reason":"<max 12 slov>"}}"""


def _parse(txt):
    if not txt:
        return None, None
    # 1) skús plný JSON objekt
    m = re.search(r'\{[^{}]*"verdict"[^{}]*\}', txt)
    if m:
        try:
            o = json.loads(m.group(0))
            v = str(o.get("verdict", "")).strip().upper()
            if v in VERDICTS:
                return v, str(o.get("reason", ""))[:120]
        except Exception:
            pass
    # 2) fallback: verdikt vytiahni aj z odseknutého JSON ("verdict":"MERGE bez })
    #    Gemini občas prekročí token limit a JSON nedokončí — verdikt je aj tak jasný.
    mv = re.search(r'"verdict"\s*:\s*"?(MERGE|RELATE|CONFLICT|DISTINCT)', txt, re.I)
    if mv:
        mr = re.search(r'"reason"\s*:\s*"([^"]{0,120})', txt)
        return mv.group(1).upper(), (mr.group(1) if mr else "")
    return None, (txt or "")[:80]


def main():
    from llm_client import chat
    import numpy as np

    n_pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 12

    d = np.load(NPZ, allow_pickle=True)
    ids = [int(x) for x in d["ids"]]
    V = d["vecs"].astype("float64")
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)

    texts = {}
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if line:
            o = json.loads(line)
            texts[o["id"]] = o.get("text", "")

    # len uzly ktoré sú aj v indexe (žlive), inak porovnávame s mŕtvymi orphanmi
    live = [(i, m) for i, m in enumerate(ids) if m in texts and texts[m].strip()]
    li = [i for i, _ in live]
    Vl = V[li]
    S = Vl @ Vl.T
    np.fill_diagonal(S, -2.0)

    # grey_merge páry (0.15..0.40), dedup cez frozenset, zoradené najbližšie prvé
    seen = set()
    pairs = []
    for r in range(len(li)):
        c = int(S[r].argmax())
        dist = 1.0 - float(S[r, c])
        if 0.15 <= dist < 0.40:
            a_id, b_id = ids[li[r]], ids[li[c]]
            key = frozenset((a_id, b_id))
            if key not in seen:
                seen.add(key)
                pairs.append((a_id, b_id, round(dist, 3)))
    pairs.sort(key=lambda x: x[2])
    pairs = pairs[:n_pairs]

    print(f"grey_merge unikátnych párov spolu: {len(seen)}; spracúvam {len(pairs)}", flush=True)

    results = []
    tally = {"consensus": 0, "majority": 0, "split": 0}
    for k, (a_id, b_id, dist) in enumerate(pairs, 1):
        a_txt, b_txt = texts[a_id], texts[b_id]
        p = PROMPT.format(a=a_txt[:300], b=b_txt[:300])
        votes = {}
        for lab in LABS:
            try:
                out = chat(p, model=lab, max_tokens=400)
            except Exception as e:
                out = f"__ERR__ {e}"
            v, reason = _parse(out)
            votes[lab] = {"verdict": v, "reason": reason}
        vs = [votes[l]["verdict"] for l in LABS if votes[l]["verdict"]]
        agree = "split"
        consensus_verdict = None
        if len(vs) == 3 and len(set(vs)) == 1:
            agree = "consensus"
            consensus_verdict = vs[0]
        elif vs:
            from collections import Counter
            top, cnt = Counter(vs).most_common(1)[0]
            if cnt >= 2:
                agree = "majority"
                consensus_verdict = top
        tally[agree] += 1
        rec = {"a": a_id, "b": b_id, "dist": dist, "agree": agree,
               "verdict": consensus_verdict, "votes": votes,
               "a_text": a_txt[:120], "b_text": b_txt[:120]}
        results.append(rec)
        print(f"[{k}/{len(pairs)}] #{a_id}~#{b_id} d={dist} -> {agree}:{consensus_verdict} "
              f"({'/'.join(v or '?' for v in [votes[l]['verdict'] for l in LABS])})", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nSÚHRN: {tally}   -> návrhy v {OUT}", flush=True)
    print("NIČ sa nezmenilo v pamäti. Writeback až po schválení vedúckom.", flush=True)


if __name__ == "__main__":
    main()
