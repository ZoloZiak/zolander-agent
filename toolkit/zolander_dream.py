#!/usr/bin/env python3
"""zolander_dream.py — F4 nočný "sen" (one-shot, launchd raz denne ~3:00).

Fázy:
  1. DECAY      — prepočíta salience (volá zol_mem.py decay), dostane forget/promote návrhy
  2. KONSOLIDÁCIA — dnešné L0 epizódy -> gpt-mini destilát -> uloží ako nový L1 semantic
                    koncept (lokálne; MCP consolidate_memories je mŕtve = embed engine off)
  3. RANNÝ BRIEF — denniky/brief_<dátum>.md: čo sa dialo, nové L1, NÁVRHY forget

READ-ONLY voči DB: NIČ nemaže (P2/P3 — deštrukcia až po rannom audite od vedúcka).
Beží pod /usr/bin/python3 (palantir_client = stdlib urllib). zol_mem.py = subprocess.
"""
import os
import sys
import json
import time
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
DENNIKY = os.path.join(ROOT, "denniky")
LOGS = os.path.join(ROOT, "logs")
IDX = os.path.join(STATE, "mem_index.jsonl")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")
ASCEND = os.path.join(ROOT, "toolkit", "ascend.py")
DREAMLOG = os.path.join(LOGS, "dream.log")
# zol_mem/ascend potrebuju YAR v5 embedder (torch) -> dedikovany .venv-yar,
# NIE stary vmlx python ani /usr/bin/python3 (tie torch nemaju).
VPY = os.path.join(ROOT, ".venv-yar", "bin", "python")
EMBED = os.path.join(ROOT, "toolkit", "embed_yar.py")
# model pre nocnu konsolidaciu/ascend. Default opus (kvalita pamate; LLM je zadarmo,
# nocny automat nema kontext-limit problem). Prepisatelne cez DREAM_MODEL.
DREAM_MODEL = os.environ.get("DREAM_MODEL", "opus")

sys.path.insert(0, os.path.join(HOME, "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.join(ROOT, "toolkit"))  # cluster_llm


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(DREAMLOG, "a") as f:
        f.write(f"{now()} | {msg}\n")


def run_decay():
    """Zavola zol_mem.py decay, vrati dict {forget, promote, kept} alebo {}."""
    p = subprocess.run([VPY, ZOL_MEM, "decay"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"decay zlyhal: {p.stderr[-300:]}")
        return {}
    try:
        out = json.loads(p.stdout.strip())
        return out.get("suggestions", out)  # decay vracia bud suggestions alebo priamo
    except Exception:
        return {}


def load_index():
    if not os.path.exists(IDX):
        return []
    rows = []
    for line in open(IDX):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def todays_episodes(rows):
    today = datetime.date.today().isoformat()
    return [r for r in rows if r.get("layer") == "L0" and r.get("ts", "").startswith(today)]


def _embed_many(texts):
    """Embedding cez subprocess do .venv-yar (dream bezi pod /usr/bin/python3 bez torchu)."""
    payload = "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                      for i, t in enumerate(texts))
    p = subprocess.run([VPY, EMBED], input=payload, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("embed_yar zlyhal: " + p.stderr[-300:])
    by = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            o = json.loads(line)
            by[o["id"]] = o["vector"]
    return [by[i] for i in range(len(texts))]


def _ldist(a, b):
    """Lorentzova vzdialenost (arccosh(-<a,b>_L)). Mensie=blizsie."""
    import math
    mink = -a[0] * b[0] + sum(x * y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0:
        val = 1.0
    elif val > 1e6:
        val = 1e6  # fp guard (red-team #3): clip proti strate presnosti acosh pri obrom r
    return math.acosh(val)


def _distill_group(group, model):
    """LLM destilat JEDNEJ tematicky suvislej skupiny epizod -> 1 L1 poznatok."""
    from palantir_client import chat
    joined = "\n".join(f"- {e.get('text', '')}" for e in group)
    system = ("Si Zolander, pamatovy konsolidator. Z epizod JEDNEJ temy vydestiluj "
              "1-2 vety trvaleho poznatku (semantic memory) po slovensky. Len fakt/"
              "vzorec, ziadny datum, ziadna omacka. Ak niet co destilovat, napis NIC.")
    prompt = f"Epizody (jedna tema):\n{joined}\n\nDestilat (1-2 vety, alebo NIC):"
    try:
        txt = chat(prompt, model=model, max_tokens=200, system=system).strip()
    except Exception as e:
        log(f"distill chat zlyhal: {e!r}")
        return None
    if not txt or txt.upper().startswith("NIC"):
        return None
    return txt


def consolidate(episodes, model=DREAM_MODEL):
    """Plny hippocampalny cyklus (F4): dnesne L0 epizody -> LLM-asistovany clustering
    podla TEMY (llm_cluster) -> KAZDA suvisla skupina destiluje SVOJ L1 poznatok.

    Predtym: vsetky epizody zliate do 1 destilatu -> rozmazany L1 ked su z roznych tem.
    Teraz: viacero cistych L1 (jeden na temu). Vrati list textov destilatov."""
    if len(episodes) < 2:
        return []  # netreba konsolidovat jednu epizodu
    try:
        from cluster_llm import llm_cluster
        groups = llm_cluster(episodes, _embed_many, _ldist, 1.0,
                             model=model, log_fn=log)
    except Exception as e:
        log(f"llm_cluster v consolidate zlyhal ({e!r}) -> 1 skupina fallback")
        groups = [episodes]
    distilled = []
    for g in groups:
        if len(g) < 2:
            continue  # jedina epizoda netvori trvaly poznatok
        txt = _distill_group(g, model)
        if txt:
            distilled.append({"text": txt, "from_ids": [e.get("id") for e in g]})
    log(f"consolidate: {len(episodes)} epizod -> {len(groups)} skupin -> {len(distilled)} L1 destilatov")
    return distilled


def remember_l1(text):
    """Uloží destilát ako L1 semantic cez zol_mem.py remember."""
    payload = json.dumps({"text": text, "kind": "semantic", "layer": "L1",
                          "salience": 0.75, "confidence": 0.8,
                          "source": "loop", "project": "zolander"})
    p = subprocess.run([VPY, ZOL_MEM, "remember"], input=payload,
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"remember L1 zlyhal: {p.stderr[-300:]}")
        return None
    try:
        return json.loads(p.stdout.strip()).get("remembered")
    except Exception:
        return None


def ascend_higher(model="gpt-mini"):
    """F8: po dennom L0->L1 (consolidate) dvihni pamat vyssie po rebriku
    L1->L2 a L2->L3 cez ascend.py. L0->L1 uz spravil consolidate() nizsie,
    takze tu len vyssie priecky (inak by vznikol duplicitny L1).
    Vrati zoznam vytvorenych vyssich konceptov."""
    created = []
    for fr, to in (("L1", "L2"), ("L2", "L3")):
        p = subprocess.run([VPY, ASCEND, "step", "--from", fr, "--to", to,
                            "--model", model], capture_output=True, text=True)
        if p.returncode != 0:
            log(f"ascend {fr}->{to} zlyhal: {p.stderr[-300:]}")
            continue
        try:
            res = json.loads(p.stdout.strip())
            for c in res.get("created", []):
                created.append(c)
        except Exception as e:
            log(f"ascend {fr}->{to} parse zlyhal: {e!r}")
    log(f"ascend_higher: vytvorene vyssie koncepty={len(created)}")
    return created


def _index_text_map():
    """Mapa id -> (text, kind) z mem_index.jsonl pre citatelny forget-navrh."""
    m = {}
    try:
        with open(IDX, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                m[r.get("id")] = (r.get("text", ""), r.get("kind") or r.get("memory_type") or "?")
    except Exception:
        pass
    return m


def write_brief(decay_res, episodes, distilled_l1, ascended=None, merges=None):
    """distilled_l1 = list dictov {text, from_ids, id} novych L1 konceptov."""
    day = datetime.date.today().isoformat()
    path = os.path.join(DENNIKY, f"brief_{day}.md")
    os.makedirs(DENNIKY, exist_ok=True)
    forget = decay_res.get("forget", []) if isinstance(decay_res, dict) else []
    txtmap = _index_text_map()
    with open(path, "w") as f:
        f.write(f"# Ranný brief — {day}\n\n")
        f.write(f"*Sen: {now()}*\n\n")
        f.write(f"## Včerajšok\n- L0 epizód: {len(episodes)}\n")
        if distilled_l1:
            f.write(f"\n## Nové L1 koncepty ({len(distilled_l1)} — jeden na tému)\n")
            for d in distilled_l1:
                cid = d.get("id", "?")
                frm = ",".join(str(i) for i in d.get("from_ids", []))
                f.write(f"- **id={cid}** (z {frm}): {d.get('text', '')}\n")
        else:
            f.write("\n## Konsolidácia\n- nič nové na destiláciu\n")
        if ascended:
            f.write("\n## Výstup po rebríku abstrakcie (F8 — bližšie k jadru)\n")
            for c in ascended:
                lyr = c.get("layer", "?")
                cid = c.get("id", "?")
                frm = ",".join(str(i) for i in c.get("from_ids", []))
                f.write(f"- **{lyr}** (id={cid}, z {frm}): {c.get('text', '')}\n")
        f.write("\n## NÁVRHY na zabudnutie (rozhodni ty — nič som nezmazal)\n")
        f.write("*Len staré epizódy s nízkou salienciou. Durable fakty "
                "(identity/procedural/semantic) sa na forget nenavrhujú.*\n\n")
        if forget:
            for fid in forget:
                txt, kind = txtmap.get(fid, ("(text nenájdený v indexe)", "?"))
                f.write(f"- [ ] id={fid} [{kind}] — {txt}\n")
        else:
            f.write("- žiadne\n")
        # P2 dedup audit: čo opus v noci zlúčil (recovery v state/dedup_trash.jsonl)
        merges = merges or []
        f.write(f"\n## Dedup (opus zlúčil duplikáty — {len(merges)}; recovery v dedup_trash.jsonl)\n")
        if merges:
            for m in merges:
                f.write(f"- zmazané id={m.get('removed')} -> nechané id={m.get('kept')}: "
                        f"{m.get('removed_text', '')} ({m.get('reason', '')})\n")
        else:
            f.write("- žiadne duplikáty\n")
        f.write("\n---\n*Vedúcko, jediné čo som sám zmazal sú dedup-duplikáty vyššie "
                "(recovery v dedup_trash.jsonl). Forget-návrhy čakajú na tvoj audit.*\n")
    return path


def dream():
    decay_res = run_decay()
    rows = load_index()
    episodes = todays_episodes(rows)
    # F4 plny cyklus: epizody -> tematicke skupiny -> viacero cistych L1 destilatov
    distilled_l1 = consolidate(episodes, model=DREAM_MODEL)
    for d in distilled_l1:
        nid = remember_l1(d["text"])
        d["id"] = nid  # dopln realne id do briefu
    ascended = ascend_higher(model=DREAM_MODEL)  # F8: dvihni L1->L2->L3
    # P2 SEMANTICKY DEDUP (cesta A): opus najde parafrazove duplikaty, auto-merge
    # so zachrannou stopou (state/dedup_trash.jsonl). Beh PO consolidate/ascend,
    # nech dedupuje aj cerstvo vzniknute L1/L2 koncepty.
    merges = []
    try:
        from dedup_dream import dedup
        merges = dedup(model=DREAM_MODEL, dry_run=False, log_fn=log)
    except Exception as e:
        log(f"dedup faza zlyhala (fail-open, pamat nedotknuta): {e!r}")
    brief = write_brief(decay_res, episodes, distilled_l1, ascended=ascended, merges=merges)
    log(f"sen OK | epizod={len(episodes)} | nove_L1={len(distilled_l1)} | "
        f"vyssie={len(ascended)} | dedup_merge={len(merges)} | brief={os.path.basename(brief)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(dream())
    except Exception as e:
        log(f"DREAM EXCEPTION: {e!r}")
        sys.exit(1)
