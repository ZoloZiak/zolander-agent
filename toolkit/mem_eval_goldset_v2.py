#!/usr/bin/env python3
"""mem_eval_goldset_v2.py — VELKY kvalitny recall gold-set (stratifikovany, validovany).

Preco v2 (v1 mal diery, viz memory-recall-state.md 2026-09-27):
  - v1: N=24, jeden Opus call, vzorkoval rows[::step] naslepo (chytal dormant aj
    near-duplikaty), ZIADNA validacia jednoznacnosti otazky.
  - v2: stratifikacia naprie kind, skip dormant/kratke/near-dup targety, batched
    generacia, a DVE kvalitne brany:
      (1) PARAPHRASE GATE (lexikalny): odmietne otazku co kopiruje >MAX_OVERLAP
          obsahovych slov ciela — vynuti realnu parafrazu (test vyznamu, nie zhody slov).
      (2) UNIQUENESS JUDGE (Opus, nezavisly od recall fuzie): otazka + ciel + K
          lexikalnych konfuzorov (nahodne premiesane, labely A..); Opus vyberie ktory
          label otazka popisuje. Ak != ciel -> DROP (nejednoznacne / zla parafraza).
          Token-overlap len NAJDE konfuzory, NEskoruje ich -> ziadna cirkularita s
          BM25/YAR/Gemma fuziou co eval meria.

ANTI-CIRKULARITA: kuratela NIKDY nepouziva recall engine (embed->search). Confuseri
sa hladaju holym token-overlapom, rozhodnutie robi Opus reasoning (iny mechanizmus nez
fuzia). Default eval rezimy (yar_only/bm25_only/hybrid bez rerank) Opusa nepouzivaju ->
curbing Opusom ich nerigne. (Rerank rezim ma miernu prekryvku — poznamenane.)

Vystup: state/mem_eval_gold_v2.json = [{"id","query","kind"}]. Zaloha stareho pred zapisom.
Bezi pod .venv-yar (palantir_client). Env: EVAL_N (default 120), GOLD_OUT, EVAL_JUDGE=0 vypne judge.
"""
import os
import re
import sys
import json
import random
import time

HOME = os.path.expanduser("~")
ZROOT = os.environ.get("ZOLANDER_ROOT", os.path.join(HOME, "projects", "zolander"))
IDX = os.path.join(ZROOT, "state", "mem_index.jsonl")
OUT = os.environ.get("GOLD_OUT", os.path.join(ZROOT, "state", "mem_eval_gold_v2.json"))
# palantir_client zije v zolo2.0/toolkit
for cand in (os.path.join(HOME, "projects", "zolo2.0", "toolkit"),
             os.path.join(HOME, "zolo2.0", "toolkit")):
    if os.path.isdir(cand):
        sys.path.insert(0, cand)
        sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
        break

N_SAMPLE = int(os.environ.get("EVAL_N", "120"))
GEN_BATCH = int(os.environ.get("EVAL_GEN_BATCH", "20"))
JUDGE_BATCH = int(os.environ.get("EVAL_JUDGE_BATCH", "10"))
N_CONFUSERS = int(os.environ.get("EVAL_CONFUSERS", "4"))
MAX_OVERLAP = float(os.environ.get("EVAL_MAX_OVERLAP", "0.65"))
DO_JUDGE = os.environ.get("EVAL_JUDGE", "1") == "1"
MIN_LEN = 45
SEED = int(os.environ.get("EVAL_SEED", "29"))

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a aby aj ako ale alebo ani az bez bol bola bolo boli by cez co da do ho "
            "i ich je ako ju k ke ked kto ktora ktore ktory le len ma mi mu na nad nie "
            "no o od pre pri po sa se si so su ta tak tam te to tu ty uz v vo z za ze "
            "the of to in is it and or for that this with".split())


def _fold(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower())
                    if not unicodedata.combining(c))


def _content_toks(s):
    return {t for t in _TOKEN.findall(_fold(s)) if len(t) >= 3 and t not in _STOP}


def load_active():
    rows = []
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if (r.get("text") and r.get("id") is not None
                and r.get("forget_state", "active") == "active"
                and len(r.get("text", "")) >= MIN_LEN):
            rows.append(r)
    return rows


def dedup_near(rows, jac=0.8):
    """Vyhod near-identicke texty (token Jaccard > jac) — inak by 2 podobne targety
    robili otazku nejednoznacnou uz z podstaty."""
    kept, sigs = [], []
    for r in rows:
        t = _content_toks(r["text"])
        if not t:
            continue
        dup = False
        for s in sigs:
            inter = len(t & s)
            if inter and inter / len(t | s) > jac:
                dup = True
                break
        if not dup:
            kept.append(r)
            sigs.append(t)
    return kept


def stratified(rows, n):
    """Vyvazena vzorka naprie kind: proporcne, ale s podlahou min 12 (alebo kolko je)."""
    by = {}
    for r in rows:
        by.setdefault(r.get("kind", "?"), []).append(r)
    rnd = random.Random(SEED)
    for v in by.values():
        rnd.shuffle(v)
    kinds = list(by)
    total = sum(len(by[k]) for k in kinds)
    quota = {}
    for k in kinds:
        q = max(12, round(n * len(by[k]) / total))
        quota[k] = min(q, len(by[k]))
    # orez na presne n (proporcne uber od najvacsich)
    while sum(quota.values()) > n:
        k = max(quota, key=lambda x: quota[x])
        quota[k] -= 1
    sample = []
    for k in kinds:
        sample.extend(by[k][:quota[k]])
    rnd.shuffle(sample)
    return sample, quota


_GEN_SYS = (
    "Si tvorca testovacich otazok pre pamatovy recall system. Dostanes ZOZNAM "
    "zapamatanych faktov s id. Pre KAZDY napis jednu realisticku otazku po slovensky, "
    "ktoru by polozil pouzivatel KED HLADA PRAVE TENTO fakt — ale INYMI slovami "
    "(synonyma, ina formulacia, prirodzena rec). NEkopiruj klucove slova doslovne. "
    "Otazka musi jednoznacne mierit na TEN fakt. Vrat IBA JSON pole "
    '[{"id":<cislo>,"query":"<otazka>"}], nic ine.'
)


def gen_batch(chat, batch):
    listing = "\n".join(f'- id={r["id"]}: {r["text"]}' for r in batch)
    prompt = f"Fakty:\n{listing}\n\nPre kazdy napis testovaciu otazku (parafraza)."
    out = chat(prompt, model="opus", max_tokens=4000, system=_GEN_SYS)
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def confusers(target, pool, k):
    """K lexikalne najblizsich INYCH zaznamov (holy token-overlap, NIE recall fuzia)."""
    tt = _content_toks(target["text"])
    scored = []
    for r in pool:
        if r["id"] == target["id"]:
            continue
        ov = len(tt & _content_toks(r["text"]))
        if ov:
            scored.append((ov, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]


_JUDGE_SYS = (
    "Si rozhodca kvality testovacich otazok. Pre kazdu polozku dostanes OTAZKU a "
    "niekolko faktov oznacenych pismenami. Rozhodni, ktory JEDINY fakt otazka "
    "najpresnejsie a jednoznacne popisuje. Ak je otazka nejednoznacna (sedi na viac "
    "faktov rovnako dobre) alebo nesedi na ziadny, vrat \"?\". Vrat IBA JSON objekt "
    '{"<qid>":"<pismeno alebo ?>", ...}, nic ine.'
)


def judge_batch(chat, items):
    """items: list of {qid, query, choices:[(letter,text)], target_letter}.
    Vrati set qid ktore Opus spravne priradil k target_letter (= jednoznacne)."""
    lines = []
    for it in items:
        lines.append(f'\n[{it["qid"]}] OTAZKA: {it["query"]}')
        for letter, txt in it["choices"]:
            lines.append(f'   {letter}) {txt}')
    prompt = "Polozky:\n" + "\n".join(lines) + '\n\nVrat {"qid":"pismeno"} pre kazdu.'
    out = chat(prompt, model="opus", max_tokens=2000, system=_JUDGE_SYS)
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return set()
    try:
        verdict = json.loads(m.group(0))
    except Exception:
        return set()
    ok = set()
    for it in items:
        if str(verdict.get(str(it["qid"]), "?")).strip().upper()[:1] == it["target_letter"]:
            ok.add(it["qid"])
    return ok


def main():
    from palantir_client import chat

    rows = load_active()
    rows = dedup_near(rows)
    sample, quota = stratified(rows, N_SAMPLE)
    print(f"korpus active(dedup)={len(rows)}  vzorka={len(sample)}  kvoty={quota}", file=sys.stderr)

    idx_by_id = {r["id"]: r for r in rows}

    # ── generacia (batched) ──────────────────────────────────────────────────
    gold = []
    for i in range(0, len(sample), GEN_BATCH):
        batch = sample[i:i + GEN_BATCH]
        try:
            gen = gen_batch(chat, batch)
        except Exception as e:
            print(f"  gen batch {i} zlyhal: {e}", file=sys.stderr)
            continue
        for g in gen:
            gid, q = g.get("id"), (g.get("query") or "").strip()
            if gid not in idx_by_id or not q:
                continue
            tgt = idx_by_id[gid]
            # PARAPHRASE GATE: query nesmie kopirovat > MAX_OVERLAP obsahovych slov ciela
            qt, tt = _content_toks(q), _content_toks(tgt["text"])
            if tt and len(qt & tt) / max(1, len(qt)) > MAX_OVERLAP:
                continue
            gold.append({"id": gid, "query": q, "kind": tgt.get("kind", "?")})
        print(f"  gen {i//GEN_BATCH+1}: spolu {len(gold)} kandidatov", file=sys.stderr)

    # ── uniqueness judge (batched, Opus, non-circular) ────────────────────────
    if DO_JUDGE:
        rnd = random.Random(SEED + 1)
        letters = "ABCDEFGH"
        items = []
        for g in gold:
            tgt = idx_by_id[g["id"]]
            conf = confusers(tgt, rows, N_CONFUSERS)
            choices_recs = conf + [tgt]
            rnd.shuffle(choices_recs)
            choices = [(letters[j], r["text"]) for j, r in enumerate(choices_recs)]
            target_letter = next(l for (l, _), r in zip(choices, choices_recs) if r["id"] == g["id"])
            items.append({"qid": g["id"], "query": g["query"],
                          "choices": choices, "target_letter": target_letter})
        passed = set()
        for i in range(0, len(items), JUDGE_BATCH):
            chunk = items[i:i + JUDGE_BATCH]
            try:
                passed |= judge_batch(chat, chunk)
            except Exception as e:
                print(f"  judge batch {i} zlyhal (ponechavam): {e}", file=sys.stderr)
                passed |= {it["qid"] for it in chunk}  # fail-open: nezahod pri chybe API
            print(f"  judge {i//JUDGE_BATCH+1}: preslo {len(passed)}", file=sys.stderr)
        before = len(gold)
        gold = [g for g in gold if g["id"] in passed]
        print(f"judge: {before} -> {len(gold)} (zahodenych nejednoznacnych: {before-len(gold)})", file=sys.stderr)

    # ── finalna validacia: vsetky targety active + dedup query na to iste id ──
    seen, final = set(), []
    for g in gold:
        if g["id"] in idx_by_id and g["id"] not in seen:
            final.append(g)
            seen.add(g["id"])

    if os.path.exists(OUT):
        bak = OUT + ".bak-" + time.strftime("%Y%m%d")
        try:
            os.replace(OUT, bak)
        except Exception:
            pass
    json.dump(final, open(OUT, "w"), ensure_ascii=False, indent=2)
    kc = {}
    for g in final:
        kc[g["kind"]] = kc.get(g["kind"], 0) + 1
    print(f"OK: {len(final)} gold otazok -> {OUT}")
    print(f"per-kind: {kc}")
    for g in final[:6]:
        print(f"  #{g['id']} [{g['kind']}]: {g['query']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
