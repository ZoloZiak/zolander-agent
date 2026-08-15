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

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "projects", "zolo2.0", "toolkit")) if os.path.isdir(os.path.join(os.path.expanduser("~"),"projects","zolo2.0","toolkit")) else sys.path.insert(0, os.path.join(os.path.expanduser("~"),"zolo2.0","toolkit"))

_SYS = (
    "Si presny re-ranker pamate. Dostanes OTAZKU a ZOZNAM kandidatnych spomienok "
    "s ich id. Vrat IBA JSON pole id zoradene od NAJRELEVANTNEJSEJ po najmenej "
    "relevantnu k otazke. Relevancia = odpoveda spomienka na zamer otazky (chap "
    "synonyma, pady, parafrazy). Nepridavaj text, iba JSON pole cisel, napr. [383,52,140]. "
    "Nerelevantne kandidaty vynechaj z pola."
)


def rerank(query, candidates, model="opus", max_ids=None):
    """candidates: list dict s 'id' a 'text'. Vrat list id (preusporiadane).
    Fail-open: pri chybe vrati povodne poradie kandidatov."""
    orig = [c["id"] for c in candidates]
    if not candidates:
        return orig
    try:
        from palantir_client import chat
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
    return ranked[:max_ids] if max_ids else ranked


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "hladam izbu blizko roboty"
    cands = [
        {"id": 383, "text": "IZBY (pokoj) na prenajom = projekt zolander-rooms"},
        {"id": 52, "text": "OrbStack kontajner hyperspace na porte 50051"},
        {"id": 140, "text": "__USER__ trva na praci urobenej poriadne"},
    ]
    print(rerank(q, cands))
