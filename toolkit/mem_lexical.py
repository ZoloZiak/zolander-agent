#!/usr/bin/env python3
"""mem_lexical.py — lexikalna (BM25) poistka nad mem_index.jsonl.

Preco: YAR 129D Lorentz embedder je slaby na parafrazu/semantiku (namerane ~52%),
takze recall obcas nevrati fakt co v pamati JE, ked query nesedi na tvar textu.
BM25 nad textami spomienok je deterministicky, bez modelu, bez GPU a chyti presne
tie pripady kde padne semantika (zhoda klucovych slov). Kombinuje sa s YAR cez RRF
v zol_mem.cmd_recall.

Korpus = mem_index.jsonl (jediny hromadny zoznam spomienok; DB nema listing a
getPoints halucia NOT_FOUND). Text je tam orezany na ~120 znakov, na klucove slova staci.

Bez zavislosti (stdlib). Diakritika sa foldu (SK/PL) aby 'izby' matchlo 'Izby'/'izbami'.
"""
import os
import re
import math
import json
import unicodedata

HOME = os.path.expanduser("~")
IDX = os.path.join(HOME, "projects", "zolander", "state", "mem_index.jsonl")

_TOKEN = re.compile(r"[a-z0-9]+")

# Light SK/PL stemmer: odstran bezne padove/cislo koncovky aby 'izba/izby/izbe/
# izbami/izbu' zdielali jeden token. Min dlzka kmena 3 (slovanske slova su kratke:
# izb-a). Koncovky od najdlhsich (ziadny agresivny Porter — over-stemming = false match).
_SUFFIXES = (
    "ovaniami", "ovaniam", "ovania", "iami", "ami", "ach", "och", "ov",
    "emu", "ymi", "imi", "ych", "ich", "ou", "mi", "om", "em", "my",
    "a", "e", "i", "o", "u", "y",
)


def _fold(s):
    """lowercase + odstran diakritiku (NFKD) -> ASCII-ish pre robustny match."""
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _stem(tok):
    """Odsekni jednu najdlhsiu zhodnu koncovku, ak kmen ostane aspon 3 znaky."""
    for suf in _SUFFIXES:
        if len(tok) - len(suf) >= 3 and tok.endswith(suf):
            return tok[:-len(suf)]
    return tok


def tokenize(text):
    return [_stem(t) for t in _TOKEN.findall(_fold(text or ""))]


# Zombie stavy: episoda je uz mimo aktivnej hry (nizka salience, stara). BM25 ich
# NEMA prehladavat — inak sa aktivne fakty topia v sume mrtvych riadkov (namerane:
# rast korpusu 318->2437 zrazil BM25 R@1 z 0.83 na 0.58). Reverzibilne: filter je
# CITACI (data ostavaju v mem_index.jsonl), a vypnutelny pre eval/audit cez
# ZOL_LEXICAL_INCLUDE_DORMANT=1 (vtedy sa citaju vsetky riadky ako predtym).
_DORMANT_STATES = {"dormant", "retired_candidate", "retired"}
_INCLUDE_DORMANT = os.environ.get("ZOL_LEXICAL_INCLUDE_DORMANT", "0") == "1"


def load_corpus(idx_path=IDX, include_dormant=None):
    """Vrat list {id, text, kind, layer, ts, forget_state} z mem_index.jsonl (fail-open).

    Default preskoci dormant/retired episody (mimo hry). include_dormant=True (alebo
    env ZOL_LEXICAL_INCLUDE_DORMANT=1) ich zaradi spat — pre eval/audit ktore chcu
    vidiet cely korpus.
    """
    if include_dormant is None:
        include_dormant = _INCLUDE_DORMANT
    docs = []
    if not os.path.exists(idx_path):
        return docs
    for line in open(idx_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "id" not in r:
            continue
        fstate = r.get("forget_state", "active")
        if not include_dormant and fstate in _DORMANT_STATES:
            continue  # zombie — mimo BM25 korpusu (data ostavaju v subore)
        docs.append({"id": r["id"], "text": r.get("text", ""),
                     "kind": r.get("kind") or r.get("memory_type") or "episodic",
                     "layer": r.get("layer", "L0"), "ts": r.get("ts", ""),
                     "forget_state": fstate})
    return docs


def bm25(query, docs, k1=1.5, b=0.75):
    """Vrat [(id, score, doc)] zoradene desc podla BM25. Prazdne ak nic nematchne."""
    q = tokenize(query)
    if not q or not docs:
        return []
    N = len(docs)
    toks = [tokenize(d["text"]) for d in docs]
    avgdl = sum(len(t) for t in toks) / N if N else 0.0
    # document frequency
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log(1 + (N - n + 0.5) / (n + 0.5)) for w, n in df.items()}
    scored = []
    for d, t in zip(docs, toks):
        if not t:
            continue
        dl = len(t)
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            f = tf[w]
            s += idf.get(w, 0.0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if s > 0:
            scored.append((d["id"], s, d))
    scored.sort(key=lambda x: -x[1])
    return scored


def search(query, topk=10, idx_path=IDX):
    docs = load_corpus(idx_path)
    return bm25(query, docs)[:topk]


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "izby pokoj"
    for i, (mid, sc, d) in enumerate(search(q, 10), 1):
        print(f"{i:2}. #{mid} {sc:.3f} [{d['kind']}] {d['text'][:80]}")
