#!/usr/bin/env python3
"""cluster_llm.py — LLM-asistovany clustering (Roadmap #1, Zolander F8/F9).

PRECO: cisty embedding cluster (YAR v5 129D Lorentz) je cross-domain NESPOLAHLIVY.
Dokazane 2x naostro (PLAN §20):
  - SPLIT zlyhanie: embedding ZLIEPOL nesuvisiace koncepty (id 9 odolnost pamate +
    id 10 Rozbehova euf: ldist 1.18) len preto ze boli blizko v povrchovych slovach.
  - MERGE zlyhanie: embedding NESPOJIL co patri spolu ("kamera v skrini" vs
    "odkladanie projektov" = ten isty vzorec, ale ine slova -> velka Lorentz dist;
    dokonca "gulas" bol BLIZSIE ku kamere nez spravny vzorec).
LLM vie OBA smery naraz: dostane vsetky koncepty a zoskupi ich podla PRINCIPU,
nie podla povrchovych slov. Toto je jadro Roadmap #1.

STRATEGIA (LLM-first, embedding-fallback):
  - Ak je konceptov <= MAX_DIRECT (default 18), LLM dostane VSETKY ocislovane naraz
    a vrati kompletne zoskupenie {"groups": [[0,2],[1],...]}. Rozhoduje o split aj
    merge v jednom kroku. Toto je pripad Zolandera (desiatky konceptov).
  - Ak je ich viac, embedding sprav HRUBE predskupenie sirokym prahom (lacne), potom
    LLM per-bucket doladi. (skalovaci fallback, zatial malo pouzivany.)
  - Ak LLM zlyha / nedostupny / vrati nezmysel -> FALLBACK na cisty embedding greedy
    cluster (spravanie pred touto zmenou). Nic sa nerozbije.

READ-ONLY: modul NIC neuklada, len vracia zoskupenie. Zapis rozhoduje volajuci
(ascend.step / patterns.mine) az po pripadnom audite veducka.
"""
import os
import json

# palantir_client (chat/LLM) zije v zolo2.0/toolkit — volajuci moduly uz maju
# sys.path.insert na neho; import robime LAZY vo funkcii (ako inde v projekte).

MAX_DIRECT = int(os.environ.get("CLUSTER_LLM_MAX_DIRECT", "18"))

_SYSTEM = (
    "Si Zolander — dekonstrukcny nastroj na luciditu. Tvoja uloha: zoskupit "
    "koncepty podla toho, ci su INSTANCIOU TOHO ISTEHO principu/vzorca — aj ked su "
    "z uplne inych oblasti zivota a pouzivaju ine slova. Dva koncepty patria spolu "
    "IBA ak zdielaju rovnaky HLBKOVY princip, nie len povrchove slova. Nespajaj "
    "nasilu nesuvisiace veci; nech radsej ostane samostatna skupina nez zle zliate. "
    "Po slovensky. Ziadna omacka."
)


def _parse_groups(raw, n):
    """Vytiahne {"groups": [[indexy],...]} z LLM odpovede. Overi ze kazdy index
    0..n-1 je pokryty prave raz; inak vrati None (-> fallback)."""
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        obj = json.loads(raw[s:e + 1])
    except Exception:
        return None
    groups = obj.get("groups")
    if not isinstance(groups, list) or not groups:
        return None
    seen = set()
    out = []
    for g in groups:
        if not isinstance(g, list):
            return None
        idxs = []
        for i in g:
            if not isinstance(i, int) or i < 0 or i >= n or i in seen:
                return None  # duplicita / mimo rozsah -> nedoveryhodne
            seen.add(i)
            idxs.append(i)
        if idxs:
            out.append(idxs)
    if len(seen) != n:
        return None  # nie kazdy koncept zaradeny prave raz
    return out


def _embedding_groups(rows, embed_fn, ldist_fn, threshold):
    """Fallback: povodny greedy embedding cluster (Lorentzova vzdialenost)."""
    if not rows:
        return []
    vecs = embed_fn([r.get("text", "") for r in rows])
    groups, reps = [], []
    for r, v in zip(rows, vecs):
        placed = False
        for gi, rep in enumerate(reps):
            if ldist_fn(v, rep) <= threshold:
                groups[gi].append(r)
                placed = True
                break
        if not placed:
            reps.append(v)
            groups.append([r])
    return groups


def llm_cluster(rows, embed_fn, ldist_fn, threshold, model="opus",
                max_direct=MAX_DIRECT, log_fn=None):
    """Hlavny vstup. rows = list dictov s klucom 'text'. Vrati list skupin
    (list[list[row]]). LLM-first, embedding-fallback.

    embed_fn(list[str])->list[vec] a ldist_fn(vec,vec)->float dodava volajuci
    (aby sa pouzil jeho VENV_YAR subprocess a rovnaka Lorentz metrika)."""
    def _log(m):
        if log_fn:
            log_fn(m)

    if len(rows) < 2:
        return [rows] if rows else []

    # vela dat -> hrube embedding predskupenie, potom LLM per-bucket
    if len(rows) > max_direct:
        buckets = _embedding_groups(rows, embed_fn, ldist_fn, threshold)
        refined = []
        for b in buckets:
            if len(b) <= 2:
                refined.append(b)
            else:
                refined.extend(llm_cluster(b, embed_fn, ldist_fn, threshold,
                                           model=model, max_direct=max_direct,
                                           log_fn=log_fn))
        return refined

    # <= max_direct: LLM dostane vsetky naraz a zoskupi od nuly
    try:
        from palantir_client import chat
        listing = "\n".join(f"[{i}] {r.get('text', '')}" for i, r in enumerate(rows))
        prompt = (
            f"Mam {len(rows)} konceptov. Zoskup ich podla toho, ktore su instanciou "
            f"TOHO ISTEHO hlbkoveho principu (aj cez rozne oblasti/slova). Koncept "
            f"ktory nepatri k ziadnemu inemu daj do vlastnej samostatnej skupiny.\n\n"
            f"{listing}\n\n"
            'Vrat IBA JSON: {"groups": [[indexy jednej skupiny], [indexy dalsej], ...]}. '
            "Kazdy index 0.." + str(len(rows) - 1) + " sa musi objavit PRAVE RAZ."
        )
        raw = chat(prompt, model=model, max_tokens=500, system=_SYSTEM).strip()
        parsed = _parse_groups(raw, len(rows))
        if parsed is None:
            _log(f"llm_cluster: LLM vratil nevalidne zoskupenie -> fallback embedding")
            return _embedding_groups(rows, embed_fn, ldist_fn, threshold)
        _log(f"llm_cluster: LLM zoskupil {len(rows)} konceptov do {len(parsed)} skupin")
        return [[rows[i] for i in g] for g in parsed]
    except Exception as ex:
        _log(f"llm_cluster: LLM zlyhal ({str(ex)[:120]}) -> fallback embedding")
        return _embedding_groups(rows, embed_fn, ldist_fn, threshold)
