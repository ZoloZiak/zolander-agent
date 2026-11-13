#!/usr/bin/env python3
"""mem_rerank.py — VOLITELNY LLM re-rank kandidatov z hybrid recallu (Opus).

Preco volitelny: recall bezi cez hook na starte KAZDEJ session -> LLM re-rank by pridal
~8s + 1 API call na kazdy nabeh. Preto DEFAULT OFF; zapina sa obj["rerank"]=true alebo
env ZOL_RECALL_RERANK=1. Riesi to, co BM25 aj YAR nechytia: semanticku relevanciu naprie
parafrazou/morfologiou (Opus chape ze "izbu" == "izby" == zamer hladat izbu).

Vstup: query + kandidati [{id, text, ...}] (z hybrid fuzie, uz orezany na ~top-8).
Vystup: preusporiadane ID podla relevancie (Opus vrati JSON zoznam id). Fail-open:
ak Opus zlyha/nedostupny, vrati povodne poradie (recall nikdy nespadne kvoli re-ranku).
"""
import os
import re
import sys
import json
import time
import hashlib

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "projects", "zolo2.0", "toolkit")) if os.path.isdir(os.path.join(os.path.expanduser("~"),"projects","zolo2.0","toolkit")) else sys.path.insert(0, os.path.join(os.path.expanduser("~"),"zolo2.0","toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)

_SYS = (
    "Si presny re-ranker pamate. Dostanes OTAZKU a ZOZNAM kandidatnych spomienok "
    "s ich id. Vrat IBA JSON pole id zoradene od NAJRELEVANTNEJSEJ po najmenej "
    "relevantnu k otazke. Relevancia = odpoveda spomienka na zamer otazky (chap "
    "synonyma, pady, parafrazy). Nepridavaj text, iba JSON pole cisel, napr. [383,52,140]. "
    "Nerelevantne kandidaty vynechaj z pola."
)

CACHE_PATH = os.environ.get(
    "ZOL_RERANK_CACHE",
    os.path.join(os.path.expanduser("~"), "projects", "zolander", "state", "mem_rerank_cache.json"),
)
CACHE_MAX = int(os.environ.get("ZOL_RERANK_CACHE_MAX", "2000"))
CACHE_TTL_DAYS = float(os.environ.get("ZOL_RERANK_CACHE_TTL_DAYS", "60"))


def _cache_key(query, candidates, model="opus"):
    payload = {
        "v": 1,
        "model": model,
        "query": query,
        "candidates": [
            {"id": c.get("id"), "text": (c.get("text") or "")[:280]}
            for c in candidates
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _load_cache(path=None):
    path = path or CACHE_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_cache(cache, path=None):
    path = path or CACHE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        items = sorted(cache.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:CACHE_MAX]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(items), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cache_get(key, valid_ids, path=None, now=None):
    cache = _load_cache(path)
    ent = cache.get(key)
    if not isinstance(ent, dict):
        return None
    now = now or time.time()
    ts = float(ent.get("ts", 0) or 0)
    if CACHE_TTL_DAYS > 0 and ts and now - ts > CACHE_TTL_DAYS * 86400:
        return None
    order = ent.get("order")
    if not isinstance(order, list):
        return None
    valid = set(valid_ids)
    ranked = [int(i) for i in order if i in valid]
    ranked += [i for i in valid_ids if i not in ranked]
    return ranked


def _cache_put(key, order, path=None):
    cache = _load_cache(path)
    cache[key] = {"ts": time.time(), "order": [int(i) for i in order]}
    _save_cache(cache, path)



def rerank(query, candidates, model="opus", max_ids=None):
    """candidates: list dict s 'id' a 'text'. Vrat list id (preusporiadane).
    Fail-open: pri chybe vrati povodne poradie kandidatov."""
    orig = [c["id"] for c in candidates]
    if not candidates:
        return orig
    key = _cache_key(query, candidates, model=model)
    cached = _cache_get(key, orig)
    if cached is not None:
        return cached[:max_ids] if max_ids else cached
    try:
        from llm_client import chat
    except Exception:
        return orig
    lines = [f"OTAZKA: {query}", "", "KANDIDATI:"]
    for c in candidates:
        txt = (c.get("text") or "")[:280]
        lines.append(f"- id={c['id']}: {txt}")
    prompt = "\n".join(lines)
    try:
        out = chat(prompt, model=model, max_tokens=200, system=_SYS)
    except Exception:
        return orig
    if not out:
        return orig
    m = re.search(r"\[[\d,\s]*\]", out)
    if not m:
        return orig
    try:
        ranked = [int(x) for x in json.loads(m.group(0))]
    except Exception:
        return orig
    valid = set(orig)
    ranked = [i for i in ranked if i in valid]
    # dolep kandidatov co Opus vynechal (na koniec, aby sa nestratili)
    ranked += [i for i in orig if i not in ranked]
    _cache_put(key, ranked)
    return ranked[:max_ids] if max_ids else ranked


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "hladam izbu blizko roboty"
    cands = [
        {"id": 383, "text": "IZBY (pokoj) na prenajom = projekt zolander-rooms"},
        {"id": 52, "text": "OrbStack kontajner hyperspace na porte 50051"},
        {"id": 140, "text": "__USER__ trva na praci urobenej poriadne"},
    ]
    print(rerank(q, cands))
