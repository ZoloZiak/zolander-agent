#!/usr/bin/env python3
"""patterns.py — F9 detektor vzorcov / skriptov.

Userovo "vidim za oponu" spravene mechanicky: katalog opakujucich sa scenarov
v situaciach, ludoch a KLUCOVO v userovi. Ked pride problem, Zolander sa najprv
pyta "aky je to vzorec? kde si to uz videl?".

Vzorce zij ako kind=semantic, layer=L2, s prefixom "VZOREC:" v texte (princip =
blizko jadra r->0). NErobime extra kolekciu ani kind=pattern (ten by v zol_mem
padol na episodic a DECAYOVAL by) — vzorec je trvaly princip, patri do
zol_semantic a L2 nedecayuje.

Rezimy:
  detect  — nova situacia -> embed -> najdi podobne ULOZENE vzorce (recall +
            lokalny filter na "VZOREC:" texty). Ak blizky (Lorentz distance <
            prah) -> "toto je instancia vzorca X". Inak -> LLM pomenuje NOVY
            kandidat vzorec (navrh, neuklada sam — rozhodne veducko / learn).
  learn   — uloz potvrdeny vzorec ako kind=semantic layer=L2 (prefix VZOREC:).
  mine    — z L0/L1 konceptov (mem_index) najdi opakujuce sa scenare (cluster >=2)
            a LLM ich pomenuje ako kandidatske vzorce (navrhy, neuklada).

EMBEDDING: natívny YAR v5 (embed_yar.py) cez .venv-yar, NIE cosine embed.py.
Clustering + match = Lorentzova vzdialenost (mensie=blizsie).

Beh:
  echo '{"situation":"..."}' | $VENV_YAR patterns.py detect
  echo '{"name":"...","desc":"..."}' | $VENV_YAR patterns.py learn
  $VENV_YAR patterns.py mine
"""
import os
import sys
import json
import math
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")
VENV_YAR = os.path.join(ROOT, ".venv-yar", "bin", "python")
EMBED = os.path.join(ROOT, "toolkit", "embed_yar.py")

# palantir_client (chat/LLM) zije v zolo2.0/toolkit; embedding je ODDELENY
# subprocess do VENV_YAR (torch tam, nie tu).
sys.path.insert(0, os.path.join(HOME, "zolo2.0", "toolkit"))

MATCH_THRESHOLD = float(os.environ.get("PATTERNS_MATCH", "0.6"))   # Lorentz dist pod tuto = ISTY match uz z embeddingu, bez LLM
# Kolko NAJBLIZSICH ulozenych vzorcov dat LLM na re-check. NIE prah vzdialenosti:
# cross-domain je absolutna Lorentz vzdialenost NESPOLAHLIVA (embedder vidi "gulas"
# blizsie ku "kamera v skrini" nez abstraktny vzorec o odkladani), takze prah by
# cross-domain match zahodil. Preto top-N poradie + LLM rozhodne (LLM cross-domain vie).
RECHECK_N = int(os.environ.get("PATTERNS_RECHECK_N", "5"))
# (mine() nizsie stale pouziva okno na clustering)
RECHECK_WINDOW = float(os.environ.get("PATTERNS_RECHECK", "1.4"))
PATTERN_PREFIX = "VZOREC:"


def embed_many(texts):
    payload = "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                      for i, t in enumerate(texts))
    p = subprocess.run([VENV_YAR, EMBED], input=payload, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("embed_yar zlyhal: " + p.stderr[-400:])
    by = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if line and line.startswith("{"):
            o = json.loads(line)
            by[o["id"]] = o["vector"]
    return [by[i] for i in range(len(texts))]


def recall(query, topk=8, mode="sem"):
    payload = json.dumps({"query": query, "topk": topk, "mode": mode}, ensure_ascii=False)
    p = subprocess.run([VENV_YAR, ZOL_MEM, "recall"], input=payload,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("recall zlyhal: " + p.stderr[-400:])
    return json.loads(p.stdout.strip())


def remember_pattern(name, desc):
    text = f"{PATTERN_PREFIX} {name} — {desc}"
    payload = json.dumps({"text": text, "kind": "semantic", "layer": "L2",
                          "salience": 0.85, "confidence": 0.7,
                          "source": "patterns", "project": "zolander"},
                         ensure_ascii=False)
    p = subprocess.run([VENV_YAR, ZOL_MEM, "remember"], input=payload,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("remember pattern zlyhal: " + p.stderr[-400:])
    return json.loads(p.stdout.strip()).get("remembered")


def load_index():
    if not os.path.exists(IDX):
        return []
    rows = []
    for line in open(IDX):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_patterns():
    """Vsetky ULOZENE vzorce z mem_index (kind=semantic, text s prefixom VZOREC:).
    Vracia ich VSETKY — nie cez embedding recall (ten cross-domain vzorce nevytiahne
    do top-k, viz diag_detect.py). Vzorcov je malo (desiatky), da sa ich prejst vsetky."""
    return [r for r in load_index()
            if str(r.get("text", "")).startswith(PATTERN_PREFIX)]


def nearest_patterns(situation, n=RECHECK_N):
    """Zoradi ulozene vzorce podla Lorentzovej vzdialenosti k situacii a vrati top-n.
    Poradie je len HEURISTIKA pre poradie LLM re-checku — NIE prah (cross-domain je
    absolutna vzdialenost nespolahliva). Bez ulozenych vzorcov vrati []."""
    pats = load_patterns()
    if not pats:
        return []
    sit_vec = embed_many([situation])[0]
    pat_vecs = embed_many([p["text"] for p in pats])
    scored = []
    for p, pv in zip(pats, pat_vecs):
        scored.append((ldist(sit_vec, pv), p))
    scored.sort(key=lambda x: x[0])
    return [{"id": p["id"], "text": p["text"], "distance": d}
            for d, p in scored[:n]]


def ldist(a, b):
    """Lorentzova vzdialenost dvoch 129D bodov (arccosh(-<a,b>_L)). Mensie=blizsie."""
    mink = -a[0] * b[0] + sum(x * y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0:
        val = 1.0
    return math.acosh(val)


def name_new_pattern(situation, model="opus"):
    """LLM pomenuje NOVY kandidatsky vzorec pre danu situaciu (navrh)."""
    from palantir_client import chat
    system = ("Si Zolander — dekonstrukcny nastroj na luciditu. Pomenuvas opakujuce "
              "sa VZORCE/skripty za konkretnymi situaciami (v situaciach, ludoch aj "
              "v samotnom userovi). Ziadna lichotka. Po slovensky.")
    prompt = (f"Situacia:\n{situation}\n\n"
              "Aky OPAKUJUCI SA vzorec/skript sa za nou skryva? Daj kratky NAZOV "
              "vzorca (2-4 slova) a 1 vetu popis. Vrat IBA JSON: "
              '{"name":"...","desc":"..."}')
    raw = chat(prompt, model=model, max_tokens=250, system=system).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(raw[s:e + 1])
        except Exception:
            pass
    return {"name": "?", "desc": raw[:200]}


def pattern_matches(situation, pattern_text, model="gpt-mini"):
    """LLM re-check: je situacia INSTANCIOU daneho vzorca? (spaja naprieic domenami,
    kde cisty embedding zlyha). Vrati True/False + kratke zdovodnenie."""
    from palantir_client import chat
    prompt = (f"Vzorec:\n{pattern_text}\n\nSituacia:\n{situation}\n\n"
              "Je tato situacia INSTANCIOU toho isteho vzorca (aj ked je z inej "
              "oblasti zivota)? Vrat IBA JSON: {\"match\":true|false,\"why\":\"<1 veta>\"}")
    raw = chat(prompt, model=model, max_tokens=150).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        try:
            j = json.loads(raw[s:e + 1])
            return bool(j.get("match")), j.get("why", "")
        except Exception:
            pass
    return False, raw[:120]


def detect(obj):
    situation = obj["situation"]
    model = obj.get("model", "opus")
    cands = nearest_patterns(situation, n=obj.get("recheck_n", RECHECK_N))
    out = {"situation": situation}
    matched, why, hit = False, "", None

    if cands and cands[0]["distance"] < MATCH_THRESHOLD:
        # isty match uz z embeddingu (skoro identicka situacia) — bez LLM
        matched, why, hit = True, "zhoda uz na urovni embeddingu (Lorentz dist < prah)", cands[0]
    else:
        # embedding cross-domain nestaci -> LLM re-check top-N NAJBLIZSICH vzorcov.
        # LLM vie spojit vzorec naprieic domenami (kamera v skrini == odkladanie projektov),
        # co cisty embedding nevie. Prvy potvrdeny = match.
        for c in cands:
            m, w = pattern_matches(situation, c["text"], model=model)
            if m:
                matched, why, hit = True, w, c
                break

    if matched and hit:
        out["match"] = "ZNAMY_VZOREC"
        out["pattern"] = hit["text"]
        out["pattern_id"] = hit["id"]
        out["distance"] = round(hit["distance"], 4)
        out["why"] = why
        out["note"] = "Toto uz poznas — je to instancia ulozeneho vzorca vyssie."
    else:
        cand = name_new_pattern(situation, model=model)
        out["match"] = "NOVY_KANDIDAT"
        out["candidate"] = cand
        out["note"] = ("Neznamy vzorec. Navrhujem ho pomenovat takto (neulozil som "
                       "sam — potvrd cez: patterns.py learn).")
        if cands:
            out["nearest_known"] = {"id": cands[0]["id"],
                                    "text": cands[0]["text"],
                                    "distance": round(cands[0]["distance"], 4),
                                    "checked": len(cands)}
    return out


def learn(obj):
    name = obj["name"]
    desc = obj["desc"]
    pid = remember_pattern(name, desc)
    return {"learned_pattern_id": pid, "name": name}


def mine(model="opus"):
    """Z L0/L1 konceptov najdi opakujuce sa scenare (cluster>=2) -> kandidatske vzorce."""
    rows = [r for r in load_index() if r.get("layer") in ("L0", "L1")]
    if len(rows) < 3:
        return {"note": f"malo dat na mining ({len(rows)})", "candidates": []}
    # LLM-asistovany clustering (Roadmap #1): zoskup podla PRINCIPU, nie povrchovych
    # slov (cross-domain, kde cisty embedding zlyhava — PLAN §20). Fallback na
    # embedding je vnutri llm_cluster.
    from cluster_llm import llm_cluster
    groups = llm_cluster(rows, embed_many, ldist, RECHECK_WINDOW, model=model)
    from palantir_client import chat
    system = ("Si Zolander. Z opakujucich sa udalosti pomenuj VZOREC (nazov 2-4 slova "
              "+ 1 veta). Po slovensky, ziadna lichotka. JSON {\"name\":..,\"desc\":..}.")
    candidates = []
    for g in groups:
        if len(g) < 2:
            continue
        joined = "\n".join(f"- {r.get('text', '')}" for r in g)
        raw = chat(f"Opakujuce sa:\n{joined}\n\nVzorec (JSON):",
                   model=model, max_tokens=200, system=system).strip()
        s, e = raw.find("{"), raw.rfind("}")
        cand = None
        if s >= 0 and e > s:
            try:
                cand = json.loads(raw[s:e + 1])
            except Exception:
                cand = None
        candidates.append({"from_ids": [r["id"] for r in g],
                           "candidate": cand or {"raw": raw[:160]}})
    return {"candidates": candidates,
            "note": "Kandidatske vzorce (neulozene). Potvrd cez learn."}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "detect"
    if cmd == "detect":
        print(json.dumps(detect(json.loads(sys.stdin.read())), ensure_ascii=False, indent=2))
    elif cmd == "learn":
        print(json.dumps(learn(json.loads(sys.stdin.read())), ensure_ascii=False, indent=2))
    elif cmd == "mine":
        print(json.dumps(mine(), ensure_ascii=False, indent=2))
    else:
        print("neznamy prikaz: " + cmd, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
