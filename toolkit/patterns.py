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

MATCH_THRESHOLD = float(os.environ.get("PATTERNS_MATCH", "0.6"))   # Lorentz dist pod tuto = ISTY match uz z embeddingu
# okno kde embedding sam nestaci, ale stoji za LLM re-check (vzorec naprieic domenami:
# "gitara zapada prachom" vs "projekty necha rozrobene" = ten isty vzorec, ale slova
# z inych domen -> vacsia Lorentz distance; embedding to nespoji, LLM ano)
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
    hits = recall(situation, topk=obj.get("topk", 8), mode="sem")
    # lokalny filter na ulozene vzorce (prefix VZOREC: v texte, kind=semantic)
    patterns = [h for h in hits
                if str(h.get("meta", {}).get("text", "")).startswith(PATTERN_PREFIX)]
    known = patterns[0] if patterns else None
    out = {"situation": situation}
    kd = known.get("distance", 1e9) if known else 1e9
    matched, why = False, ""
    if known and kd < MATCH_THRESHOLD:
        matched, why = True, "zhoda uz na urovni embeddingu (Lorentz dist < prah)"
    elif known and kd < RECHECK_WINDOW:
        # embedding nestaci, ale je v okne -> LLM re-check naprieic domenami
        matched, why = pattern_matches(situation, known["meta"].get("text", ""), model=model)
    if matched:
        out["match"] = "ZNAMY_VZOREC"
        out["pattern"] = known["meta"].get("text")
        out["pattern_id"] = known["id"]
        out["distance"] = round(kd, 4)
        out["why"] = why
        out["note"] = "Toto uz poznas — je to instancia ulozeneho vzorca vyssie."
    else:
        cand = name_new_pattern(situation, model=model)
        out["match"] = "NOVY_KANDIDAT"
        out["candidate"] = cand
        out["note"] = ("Neznamy vzorec. Navrhujem ho pomenovat takto (neulozil som "
                       "sam — potvrd cez: patterns.py learn).")
        if patterns:
            out["nearest_known"] = {"id": patterns[0]["id"],
                                    "text": patterns[0]["meta"].get("text"),
                                    "distance": round(patterns[0].get("distance", -1), 4)}
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
    vecs = embed_many([r.get("text", "") for r in rows])
    # greedy cluster (Lorentzova vzdialenost, mensie=blizsie)
    groups, reps = [], []
    for r, v in zip(rows, vecs):
        placed = False
        for gi, rep in enumerate(reps):
            if ldist(v, rep) <= RECHECK_WINDOW:
                groups[gi].append(r)
                placed = True
                break
        if not placed:
            reps.append(v)
            groups.append([r])
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
