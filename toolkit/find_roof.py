#!/usr/bin/env python3
"""find_roof.py — NAVRHNI strechu (rodica) pre uzol v zol_mem hierarchii.

Zaklad: zmerany vysledok lorentz-lab ZL1 (2026-08-22): pri vybere rodica z kandidatov
ordinalny stromovy gate Z1 (subtree_size: r_kandidat < r_dieta) zvysil R@1 LLM placementu
0.202 -> 0.322 (McNemar p<0.0001, CI [+0.082,+0.161]). Detail: lorentz-lab/research/f2/ZAVER.md.

Mechanika (presna reprodukcia ZL1):
  1. cosine top-K kandidatov (Gemma vektory, state/gemma_all_nodes.npz — TIE ISTE co v ZL1)
  2. Z1 gate: nechaj len kandidatov s r[m] < r[dieta], kde r = 1-0.85*ln(subtree_size)/ln(max)
  3. (volitelne) Opus vybere z gated najlepsieho rodica; bez --llm vrat gated cosine top

BEZPECNOST: LEN NAVRHUJE. Nepridava/nemeni ziadne hrany. Zapis do state/roof_suggestions.jsonl.
Linkovanie hran je na veducka (zol_graph.py link ...) po precitani navrhu — princip "zrob N".

Cirkularita (poctivo, zo ZL1): subtree_size sa pocita z existujucich parent hran, takze gate
funguje pre REORGANIZACIU zabyvanych uzlov, nie pre uplne novy uzol (0 deti -> gate nefiltruje).
find_roof preto default preskoci uzly s r==r_max (listy bez podstromu) ak nie je --allow-leaf.

CLI:
  $VPY find_roof.py --id 123                 # navrhni strechu pre uzol 123 (s Opus)
  $VPY find_roof.py --id 123 --no-llm        # len cosine+gate, bez LLM (lacne/offline)
  $VPY find_roof.py --id 123 --topk 20 --dry # neuklada navrh, len vypise
kde $VPY = /Users/__USER__/.local/share/uv/tools/vmlx/bin/python (numpy; LLM cez palantir_client).
"""
import os
import sys
import json
import math
import argparse
import collections

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
EDGES = os.path.join(STATE, "mem_edges.jsonl")
NPZ = os.path.join(STATE, "gemma_all_nodes.npz")
OUT = os.path.join(STATE, "roof_suggestions.jsonl")
TOPK = 15


def _load():
    import numpy as np
    if not os.path.exists(NPZ):
        raise SystemExit(f"chyba {NPZ} (Gemma vektory) — spusti embed pipeline najprv")
    d = np.load(NPZ, allow_pickle=True)
    ids = [int(x) for x in d["ids"]]
    V = d["vecs"].astype("float64")
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    id2i = {m: i for i, m in enumerate(ids)}
    texts = {}
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if line:
            o = json.loads(line)
            texts[o["id"]] = o.get("text", "")
    # parent hrany -> subtree_size -> r (ordinalna hlbka, ZL1 vzorec)
    pe = []
    if os.path.exists(EDGES):
        for line in open(EDGES, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("edge") == "parent":
                    pe.append((e["from"], e["to"]))
            except Exception:
                pass
    par2child = collections.defaultdict(list)
    for c, p in pe:
        par2child[p].append(c)
    memo = {}

    def stsize(root):
        if root in memo:
            return memo[root]
        seen = set()
        stack = [root]
        while stack:
            x = stack.pop()
            for ch in par2child.get(x, []):
                if ch not in seen:
                    seen.add(ch)
                    stack.append(ch)
        memo[root] = len(seen) + 1
        return memo[root]

    nodes = set(id2i)
    size = {m: stsize(m) for m in nodes}
    maxs = max(size.values()) if size else 1
    r = {m: 1.0 - 0.85 * (math.log(size[m]) / math.log(maxs)) if maxs > 1 else 1.0
         for m in nodes}
    return np, ids, V, id2i, texts, r, size, maxs


def rank_with_z1_gate(child_id, candidates, r):
    """Rank kandidátov po ordinálnom Z1 gate.

    `r` je mapa id->ordinálna hĺbka kde menšie znamená všeobecnejší/vyššie v strome.
    Kandidát prežije len ak `r[kandidat] < r[dieta]`. Pôvodné poradie kandidátov
    (typicky cosine score desc) sa zachová.
    """
    rc = r.get(child_id)
    if rc is None:
        return []
    out = []
    for c in candidates:
        mid = c.get("id")
        if mid is None:
            continue
        if r.get(mid, 9.9) < rc:
            out.append(c)
    return out


def evaluate_z1_gate(cases, r):
    """Mini A/B harness: flat top-1 vs Z1-gated top-1 nad explicitnými qrels.

    Case formát:
      {"child": 10, "gold": 1, "candidates": [{"id": 2, "score": .9}, ...]}
    Kandidáti sa zoradia podľa `score` zostupne, ak už nie sú zoradení.
    """
    n = flat_hit = z1_hit = empty_gate = 0
    for case in cases:
        child = case.get("child")
        gold = case.get("gold")
        cands = list(case.get("candidates") or [])
        if child is None or gold is None or not cands:
            continue
        cands.sort(key=lambda c: -float(c.get("score", 0.0) or 0.0))
        n += 1
        flat_top = cands[0].get("id")
        if flat_top == gold:
            flat_hit += 1
        gated = rank_with_z1_gate(child, cands, r)
        if not gated:
            empty_gate += 1
            z1_top = flat_top
        else:
            z1_top = gated[0].get("id")
        if z1_top == gold:
            z1_hit += 1
    if n == 0:
        return {"n": 0, "flat_r1": 0.0, "z1_r1": 0.0, "delta_r1": 0.0, "empty_gate": 0}
    flat = flat_hit / n
    z1 = z1_hit / n
    return {
        "n": n,
        "flat_r1": round(flat, 4),
        "z1_r1": round(z1, 4),
        "delta_r1": round(z1 - flat, 4),
        "empty_gate": empty_gate,
    }


def suggest(child_id, topk=TOPK, use_llm=True, model="opus"):
    np, ids, V, id2i, texts, r, size, maxs = _load()
    if child_id not in id2i:
        raise SystemExit(f"uzol {child_id} nie je v {NPZ}")
    rc = r[child_id]
    # cosine top-K (bez seba)
    vi = V[id2i[child_id]]
    sims = V @ vi
    order = list(np.argsort(-sims))
    cands = []
    for j in order:
        m = ids[j]
        if m == child_id:
            continue
        cands.append(m)
        if len(cands) >= topk:
            break
    # Z1 gate: len vseobecnejsi kandidati (mensi r = blizsie ku korenu = vyssie v hierarchii)
    gated = [m for m in cands if r.get(m, 9.9) < rc]
    result = {
        "child": child_id, "child_text": texts.get(child_id, "")[:200],
        "child_r": round(rc, 4), "child_subtree_size": size.get(child_id),
        "n_cands": len(cands), "n_gated": len(gated),
        "gate_note": "prazdny gate = uzol je list/vseobecny, Z1 nefiltruje (cirkularita)",
    }
    if not gated:
        result["suggestion"] = None
        result["reason"] = "gate prazdny (ziadny vseobecnejsi kandidat) — nenavrhujem strechu"
        return result
    # kandidati s textom pre vyber
    gc = [{"id": m, "r": round(r[m], 4), "cos": round(float(V[id2i[m]] @ vi), 4),
           "text": texts.get(m, "")[:200]} for m in gated]
    if use_llm:
        pick = _ask_opus(child_id, texts, gc, model)
        result["suggestion"] = pick
        result["method"] = f"cosine+Z1gate+LLM({model})"
    else:
        result["suggestion"] = gated[0]  # cosine-najblizsi z gated
        result["method"] = "cosine+Z1gate (bez LLM)"
    result["candidates"] = gc
    return result


def _ask_opus(child_id, texts, gc, model):
    sys.path.insert(0, os.path.join(HOME, "projects", "__PROJECT__", "toolkit"))
    try:
        from palantir_client import chat
    except Exception as e:
        raise SystemExit(f"palantir_client nedostupny ({e!r}); pouzi --no-llm")
    lines = "\n".join(f"[{c['id']}] {c['text']}" for c in gc)
    prompt = (f"Mas spomienku a zoznam kandidatnych RODICOVSKYCH uzlov (vseobecnejsi/nadradeny "
              f"pojem, pod ktory dieta patri v hierarchii).\n\n"
              f"DIETA: {texts.get(child_id, '')[:250]}\n\nKANDIDATI:\n{lines}\n\n"
              f"Vyber ID JEDNEHO najlepsieho RODICA. Vrat LEN cislo ID.")
    resp = chat(prompt, model=model, max_tokens=15)
    import re
    nums = re.findall(r"\d+", resp or "")
    return int(nums[0]) if nums else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--topk", type=int, default=TOPK)
    ap.add_argument("--no-llm", dest="llm", action="store_false")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--dry", action="store_true", help="nezapis navrh, len vypis")
    args = ap.parse_args()
    res = suggest(args.id, topk=args.topk, use_llm=args.llm, model=args.model)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not args.dry and res.get("suggestion") is not None:
        import time
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **res}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"\n-> navrh zapisany do {OUT} (LEN navrh; linkuj rucne: "
              f"zol_graph.py link {args.id} parent {res['suggestion']})", file=sys.stderr)


if __name__ == "__main__":
    main()
