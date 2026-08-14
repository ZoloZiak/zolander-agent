#!/usr/bin/env python3
"""zol_mem.py — pamäť Zolandera (F2, v2 čistý Lorentz). PLAN §14 čistý rez.

ZMENA oproti v1: koniec dvojkolajnosti cosine768 + toy-lorentz129.
Teraz JEDNA natívna 129D Lorentz reprezentácia z YAR v5 (embed_yar.py).
Polomer/hĺbku určuje MODEL (naučená norma v LorentzMRLHead), NIE tabuľka LAYER_R.

Jedna kolekcia zol_mem (lorentz 129) — druh pamäte je v meta poli memory_type
(migrácia 4->1, 2026-08-08; benchmark: 1 kol == 4 kol kvalitou, 4 kol pomalšie).
Druhy pamäte (kognitívna trojica semantic/episodic/
procedural + naša identity), všetky lorentz 129:
  zol_semantic   — fakty, poznatky, princípy (destiláty)
  zol_episodic   — zážitky, udalosti, čo sa v sesii stalo (zabúda cez decay)
  zol_procedural — naučené postupy: "ako sa rieši X", "keď zlyhá Y, sprav Z"
  zol_identity   — jadro identity, hodnoty, kto Zolander je (nezabúda)

Pozn.: procedurálna pamäť je aj v Hermes skilloch (načítané pravidlá); táto
kolekcia je pre postupy, ktoré má Zolander vedieť sémanticky VYHĽADAŤ, nie len
keď sa skill načíta.

Hippocampus NIE je kolekcia — je to PROCES konsolidácie v 'sen' (F4,
zolander_dream.py): episodic L0 -> destilát -> semantic/procedural L1 + návrh
čo zabudnúť. Kolekcie = kde spomienky ležia; hippocampus = čo ich presúva.

Vrstvy zostávajú ako METADATA (nie polomer):
  layer: L0 (working/epizoda) | L1 (destilát) | L2 (jadro) | L3 (meta-rámec)
  salience(0..1), confidence(0..1) — pre decay/konsolidáciu v 'sen' (F4)

Použitie:
  VPY=/Users/__USER__/zolander/.venv-yar/bin/python
  echo '{"text":"...", "kind":"semantic", "layer":"L1"}' | $VPY zol_mem.py remember
  echo '{"query":"...", "kind":"semantic", "topk":5}'    | $VPY zol_mem.py recall
  $VPY zol_mem.py decay
  $VPY zol_mem.py stats
  $VPY zol_mem.py init      # vytvorí kolekciu zol_mem (idempotentne)
"""
import os
import sys
import json
import time
import subprocess

HOME = os.path.expanduser("~")
NODE = "/Users/__USER__/Applications/homebrew/bin/node"
HS = "/Users/__USER__/zolo2.0/toolkit/hs.mjs"
STATE = os.path.join(HOME, "zolander/state")
IDFILE = os.path.join(STATE, "mem_next_id.txt")
NODE_ENV = dict(os.environ, NODE_PATH="/Users/__USER__/.npm/_npx/9e13365ae4a6529c/node_modules")

DIM = 129
METRIC = "lorentz"
# MIGRACIA 4->1 (2026-08-08): jedna kolekcia, druh pamate ide do meta memory_type.
# Benchmark (MEMORY_BENCHMARK.md): 1 kol == 4 kol kvalitou, 4 kol 2.6-3.6x pomalsie.
MEM_COL = "zol_mem"
VALID_KINDS = ("semantic", "episodic", "procedural", "identity")
DEFAULT_KIND = "episodic"

# DEDUP (P2, 2026-08-08): dvojvrstvovy.
# 1) WRITE gate (tu): NEAR-EXACT gate. YAR Lorentz chyta len takmer-identicky text
#    (namerane: exact dup d~0.0, parafraza d~1.0 = YAR NEVIE parafrazy). Preto tu
#    len tvrdy prah proti presnym kopiam (napr. session spracovana 2x). Parafrazy
#    riesi az nocny dream loop cez opus (semanticky dedup, ma cas + LLM zadarmo).
DEDUP_EXACT_DIST = float(os.environ.get("ZOL_DEDUP_DIST", "0.15"))

# DECAY v2 (2026-08-13, oprava 3 bugov):
#  BUG 3 (killer): stary cmd_decay prepisal salience a kazdu noc znova odcital
#    rate*FULL_age -> kompundovalo do 0 za 4 noci (fakt z 0.6 -> 0.0), hoci
#    spravne 0.6-0.08*5=0.2. FIX: decay je IDEMPOTENTNY = current = base - rate*age,
#    ratane VZDY z povodnej base_salience, nie z uz zdecayovanej hodnoty.
#  BUG 2: writeback sypal aj semantic/procedural/identity ako L0 -> rychly layer
#    decay ich zabijal ako epizody. FIX: decay riadi KIND, nie layer. Durable
#    druhy (identity/procedural/semantic) skoro nezabudaju; zabuda len episodic.
# rate = pokles salience za den podla DRUHU pamate (memory_type/kind):
KIND_DECAY = {"identity": 0.0, "procedural": 0.004, "semantic": 0.008, "episodic": 0.05}
# fallback ked kind chyba (stare riadky bez kind v indexe)
DEFAULT_DECAY = 0.05
# rozumna base salience podla druhu (pouzita pri migracii poskodenych riadkov)
KIND_BASE = {"identity": 0.9, "procedural": 0.8, "semantic": 0.7, "episodic": 0.5}
# forget navrh: LEN episodic, starsie ako N dni a pod prahom salience
FORGET_MIN_AGE_DAYS = float(os.environ.get("ZOL_FORGET_MIN_AGE", "14"))
FORGET_SALIENCE = float(os.environ.get("ZOL_FORGET_SALIENCE", "0.12"))

# YAR embedder (natívny 129D Lorentz) — import z rovnakého toolkitu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embed_yar import embed_one  # noqa: E402


def col_for(kind=None):
    # Migracia 4->1: vzdy jedna kolekcia. Druh pamate je v meta memory_type.
    return MEM_COL


def next_id():
    os.makedirs(STATE, exist_ok=True)
    cur = 1
    if os.path.exists(IDFILE):
        cur = int(open(IDFILE).read().strip() or "1")
    with open(IDFILE, "w") as f:
        f.write(str(cur + 1))
    return cur


def hs(cmd, *args, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd} zlyhal: " + p.stderr[-500:])
    out = p.stdout.strip()
    return json.loads(out) if out else None


def cmd_init():
    """Vytvorí jednu Lorentz kolekciu zol_mem (idempotentne)."""
    made = {}
    try:
        hs("create", MEM_COL, DIM, METRIC)
        made[MEM_COL] = "created"
    except RuntimeError as e:
        made[MEM_COL] = "exists?" if ("exist" in str(e).lower() or "already" in str(e).lower()) else f"ERR {e}"
    print(json.dumps({"init": made, "dim": DIM, "metric": METRIC}, ensure_ascii=False, indent=2))


def cmd_remember():
    obj = json.loads(sys.stdin.read())
    text = obj["text"]
    kind = obj.get("kind", DEFAULT_KIND)
    layer = obj.get("layer", "L0")
    salience = float(obj.get("salience", 0.5))
    confidence = float(obj.get("confidence", 0.7))
    source = obj.get("source", "session")
    project = obj.get("project", "zolander")
    links = obj.get("links", "")
    ts = obj.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S")

    mid = obj.get("id") or next_id()
    vec = embed_one(text)  # natívny 129D Lorentz
    col = col_for(kind)
    if kind not in VALID_KINDS:
        kind = DEFAULT_KIND

    # NEAR-EXACT dedup gate: ak uz existuje takmer identicky zaznam (d < prah),
    # NEvkladaj duplikat. Vyssia salience vyhrava: ak novy je salientnejsi, uloz
    # ho aj tak (dream loop neskor zluci); inak skip. Vypnutelne obj["no_dedup"].
    if not obj.get("no_dedup"):
        try:
            near = hs("search", MEM_COL, 1, stdin=json.dumps({"vector": vec})) or []
            if near:
                d0 = near[0].get("distance", 9e9)
                if d0 < DEDUP_EXACT_DIST:
                    ex = near[0].get("meta", {}) or {}
                    ex_sal = float(ex.get("salience", 0) or 0)
                    if salience <= ex_sal + 1e-6:
                        print(json.dumps({"skipped_dup": near[0].get("id"),
                                          "dist": round(d0, 4), "kept": "existing"},
                                         ensure_ascii=False))
                        return
        except Exception:
            pass  # fail-open: dedup nikdy nezhodi zapis

    meta = {
        "kind": kind, "memory_type": kind, "layer": layer,
        "salience": round(salience, 3),
        "confidence": round(confidence, 3), "source": source,
        "project": project, "ts": ts, "links": links,
        "text": text[:300],
    }
    rec = json.dumps({"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n"
    hs("insert", col, stdin=rec)

    # lokálny index pre decay/konsolidáciu + BM25 korpus (DB nemá hromadný listing)
    # base_salience = zafixovana povodna hodnota pre IDEMPOTENTNY decay (v2).
    # text[:300] (nie 120) — BM25 aj LLM re-rank potrebuju cely zmysel, nie utrzok.
    with open(os.path.join(STATE, "mem_index.jsonl"), "a") as f:
        f.write(json.dumps({"id": mid, "col": col, "kind": kind, "layer": layer,
                            "salience": salience, "base_salience": round(salience, 3),
                            "confidence": confidence,
                            "ts": ts, "text": text[:300]}, ensure_ascii=False) + "\n")
    print(json.dumps({"remembered": mid, "kind": kind, "col": col, "layer": layer},
                     ensure_ascii=False))


def cmd_recall():
    obj = json.loads(sys.stdin.read())
    query = obj["query"]
    topk = int(obj.get("topk", 5))
    kind = obj.get("kind")  # None => všetky typy; inak filter memory_type
    # HYBRID (2026-08): YAR semantic + BM25 lexikalna poistka, zlucene cez RRF.
    # Dovod: YAR 129D Lorentz je slaby na parafrazu (~52%) -> fakt co v pamati JE
    # sa cez cisto semanticky recall obcas nevrati. BM25 nad mem_index.jsonl chyti
    # zhodu klucovych slov (deterministicky, bez modelu). RRF nepotrebuje ladit vahy
    # medzi nezrovnatelnymi skalami (Lorentz distance vs BM25 skore). Vypnutelne
    # obj["no_lexical"]=true alebo env ZOL_RECALL_LEXICAL=0.
    vec = embed_one(query)
    fetch = topk * 4  # vytiahni sirsie, po zluceni + filtri orez na topk
    res = hs("search", MEM_COL, fetch, stdin=json.dumps({"vector": vec})) or []
    for r in res:
        r["col"] = MEM_COL

    use_lex = (not obj.get("no_lexical")
               and os.environ.get("ZOL_RECALL_LEXICAL", "1") != "0")
    lex = []
    if use_lex:
        try:
            from mem_lexical import search as lex_search
            lex = lex_search(query, topk=fetch)  # [(id, score, doc)]
        except Exception:
            lex = []  # fail-open: lexikalna vrstva nikdy nezhodi recall

    # --- SCORE FUZIA (min-max norm), NIE RRF ---
    # RRF (rank-based) tu zlyhava: odmenuje konsenzus, takze sumove zaznamy co su
    # v OBOCH rebrickoch stredne vysoko predbehnu zaznam so silnym signalom v JEDNOM
    # (BM25 gap 3x sa v ranku strati). Preto normalizujeme SKORE oboch zdrojov na
    # [0,1] a scitame s vahami. YAR je preukazatelne slaby (distances ~0.9-1.04 =
    # skoro sum), preto lexikalny signal smie previazit ked je jednoznacny.
    W_SEM = float(os.environ.get("ZOL_RECALL_W_SEM", "1.0"))
    W_LEX = float(os.environ.get("ZOL_RECALL_W_LEX", "1.3"))

    def _norm(pairs):
        # pairs: list[(id, raw_score)], vyssie=lepsie. Vrat {id: norm[0..1]}.
        if not pairs:
            return {}
        vals = [s for _, s in pairs]
        lo, hi = min(vals), max(vals)
        if hi <= lo:
            return {i: 1.0 for i, _ in pairs}
        return {i: (s - lo) / (hi - lo) for i, s in pairs}

    sem_norm = _norm([(r.get("id"), 1.0 / (1.0 + r.get("distance", 9e9))) for r in res])
    lex_norm = _norm([(mid, sc) for mid, sc, _ in lex])

    meta_by_id = {}
    for r in res:
        meta_by_id[r.get("id")] = r
    for mid, _sc, doc in lex:
        meta_by_id.setdefault(mid, {"id": mid, "col": MEM_COL,
                                    "meta": {"text": doc.get("text", ""),
                                             "kind": doc.get("kind"),
                                             "memory_type": doc.get("kind"),
                                             "layer": doc.get("layer"),
                                             "ts": doc.get("ts")},
                                    "distance": None, "lexical_only": True})

    fused_score = {}
    for mid in meta_by_id:
        fused_score[mid] = (W_SEM * sem_norm.get(mid, 0.0)
                            + W_LEX * lex_norm.get(mid, 0.0))

    ordered = sorted(fused_score.items(), key=lambda kv: -kv[1])
    # najprv aplikuj kind filter, potom priprav kandidatov
    cand = []
    for mid, fused in ordered:
        r = meta_by_id.get(mid)
        if not r:
            continue
        m = r.get("meta", {}) or {}
        if kind and (m.get("memory_type") or m.get("kind")) != kind:
            continue
        r["score"] = round(fused, 4)
        cand.append(r)

    # VOLITELNY LLM re-rank. SMART DEFAULT (2026-08-13): ON pre priamy/interaktivny
    # recall (ked aktivne hladas — presnost sa ceni, +8s nevadi), ale session-start
    # (hook_recall -> zol_session start, aj CLI aj gateway) posiela explicitne
    # rerank:false — tam ide o SIRKU kontextu, nie dokonale poradie, a +8s/1 Opus call
    # na KAZDY nabeh by vratil stary "gateway nereaguje" neduh + prilieval do 429.
    # Priorita: explicitny obj["rerank"] (True/False) > env ZOL_RECALL_RERANK (0/1) > default ON.
    if "rerank" in obj:
        use_rr = bool(obj["rerank"])
    elif "ZOL_RECALL_RERANK" in os.environ:
        use_rr = os.environ["ZOL_RECALL_RERANK"] == "1"
    else:
        use_rr = True  # default ON pre priamy recall
    if use_rr and cand:
        try:
            from mem_rerank import rerank
            pool = cand[:max(topk * 2, 8)]  # re-rankuj sirsi pool, nie len topk
            texts = {r.get("id"): (r.get("meta", {}) or {}).get("text", "") for r in pool}
            order2 = rerank(query, [{"id": r.get("id"), "text": texts[r.get("id")]}
                                    for r in pool])
            by_id = {r.get("id"): r for r in pool}
            reranked = [by_id[i] for i in order2 if i in by_id]
            # dolep zvysok co nebol v poole
            reranked += [r for r in cand if r.get("id") not in {x.get("id") for x in reranked}]
            for r in reranked:
                r["reranked"] = True
            cand = reranked
        except Exception:
            pass  # fail-open: re-rank nikdy nezhodi recall

    print(json.dumps(cand[:topk], ensure_ascii=False, indent=2))


def cmd_stats():
    # getCollectionStats na tomto serveri hadze NOT_FOUND (bug); count vezmi z list.
    out = {}
    try:
        cols = hs("list") or []
        found = next((c for c in cols if c.get("name") == MEM_COL), None)
        out[MEM_COL] = {"count": found.get("count")} if found else {"error": "kolekcia neexistuje"}
    except RuntimeError as e:
        out[MEM_COL] = {"error": str(e)[-200:]}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_decay():
    """Salience decay v2 — IDEMPOTENTNY, riadeny DRUHOM pamate (kind), nie layer.

    Read-only voci DB. Pre kazdy zaznam: current = base_salience - KIND_DECAY[kind]*age.
    base_salience je zafixovana povodna hodnota (nikdy sa neprepisuje), takze
    opakovany beh decay dava ROVNAKY vysledok (ziadne kompundovanie do 0).

    Migracia stareho indexu: riadky bez 'base_salience' ho dostanu. Ak bola
    salience uz poskodena starym bugom (spadla na ~0 hoci ide o durable kind),
    base sa obnovi na KIND_BASE[kind]. Cisto episodic riadky s realne nizkou
    salienciou sa neobnovuju (maju zabudnut).

    Forget navrh: LEN episodic, starsie ako FORGET_MIN_AGE_DAYS a pod prahom.
    Durable kindy (identity/procedural/semantic) sa NIKDY nenavrhuju na forget.
    """
    now = time.time()
    suggestions = {"forget": [], "promote": [], "kept": 0, "migrated": 0}
    idx_path = os.path.join(STATE, "mem_index.jsonl")
    if not os.path.exists(idx_path):
        print(json.dumps({"note": "žiadny mem_index.jsonl — decay no-op", "suggestions": suggestions}, ensure_ascii=False, indent=2))
        return
    rows = [json.loads(l) for l in open(idx_path) if l.strip()]
    out = []
    for r in rows:
        kind = r.get("kind") or r.get("memory_type") or "episodic"
        layer = r.get("layer", "L0")
        cur_sal = float(r.get("salience", 0.5))
        ts = r.get("ts", "")
        try:
            age_days = (now - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 86400.0
        except Exception:
            age_days = 0.0

        # --- MIGRACIA: zafixuj base_salience (jednorazovo pre stare riadky) ---
        if "base_salience" not in r:
            rate = KIND_DECAY.get(kind, DEFAULT_DECAY)
            # ocakavana neposkodena salience keby decay bezal spravne z rozumnej base
            expected = max(0.0, KIND_BASE.get(kind, 0.5) - rate * age_days)
            # ak je ulozena salience VYRAZNE nizsie nez ocakavana (t.j. poskodena
            # starym kompundujucim bugom), obnov base na KIND_BASE. Inak drz max
            # z ulozenej a spat-doratanej (base = current + rate*age).
            if cur_sal < expected - 0.1:
                base = KIND_BASE.get(kind, 0.5)
                suggestions["migrated"] += 1
            else:
                base = min(1.0, cur_sal + rate * age_days)
            r["base_salience"] = round(base, 3)
        base = float(r["base_salience"])

        # --- IDEMPOTENTNY decay z FIXNEJ base ---
        rate = KIND_DECAY.get(kind, DEFAULT_DECAY)
        new_sal = max(0.0, base - rate * age_days)
        r["salience"] = round(new_sal, 3)

        # --- navrhy ---
        if kind == "episodic" and age_days > FORGET_MIN_AGE_DAYS and new_sal < FORGET_SALIENCE:
            suggestions["forget"].append(r["id"])
        elif layer == "L0" and kind == "episodic" and new_sal > 0.7 and age_days > 3:
            suggestions["promote"].append(r["id"])
        else:
            suggestions["kept"] += 1
        out.append(r)
    with open(idx_path, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(suggestions, ensure_ascii=False, indent=2))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    {
        "init": cmd_init,
        "remember": cmd_remember,
        "recall": cmd_recall,
        "decay": cmd_decay,
        "stats": cmd_stats,
    }.get(cmd, lambda: (_ for _ in ()).throw(SystemExit(f"neznámy príkaz: {cmd}")))()


if __name__ == "__main__":
    main()
