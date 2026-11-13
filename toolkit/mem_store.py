#!/usr/bin/env python3
"""mem_store.py — JEDNA vrstva PRED oboma kolekciami pamate (chokepoint).

Pamat zije v DVOCH DB reprezentaciach toho isteho faktu (zamer, nie bug):
  - zol_mem        (lorentz 129D, YAR) — 1. semanticky lens + autorita ID
  - zol_mem_gemma  (cosine  768D, EmbeddingGemma) — 3. lens (silny na parafrazu)
Plus mem_index.jsonl = BM25 lane + decay (JEDINY enumerovatelny zoznam = zdroj pravdy o tom,
co MA zit).

PROBLEM ktory riesi (namerane 2026-08-30): kazdy pisatel/mazac robil dual-write/dual-del PO
SVOJOM, gemma vetva vzdy `except: pass` (fail-open). Ked daemon :8901 padne alebo gemma del
zlyha -> jedna strana sa zmeni, druha nie -> TICHY DRIFT. Vysledok: gemma drzala 482 zivych
vs lorentz 423, vratane soft-deleted duchov.

RIESENIE: kazdy zapis/mazanie ide cez put()/delete() TU. Obe strany sa robia spolu a ked
jedna zlyha, NEZHLTNE sa ticho -> zapise sa do mem_repair.jsonl. sync() to potom dobehne a
zosuladi obe kolekcie s indexom. Tak sa uz nikdy nerozidu potichu.

CLI:
  VPY=$HOME/projects/zolander/.venv-yar/bin/python
  $VPY mem_store.py status          # reálny drift (zive union vs index), read-only
  $VPY mem_store.py sync            # zosulad obe kolekcie s indexom (idempotentne)
  $VPY mem_store.py sync --dry      # co by sync spravil, nic nemeni
  $VPY mem_store.py repair          # dobehni nevybavene z mem_repair.jsonl
"""
import os
import sys
import json
import time
import subprocess
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT

STATE = os.path.join(ZROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
REPAIR = os.path.join(STATE, "mem_repair.jsonl")

LOR_COL = "zol_mem"          # lorentz 129D, autorita
GEM_COL = "zol_mem_gemma"    # cosine 768D
GEMMA_PORT = os.environ.get("GEMMA_EMBED_PORT", "8901")
GEMMA_URL = f"http://127.0.0.1:{GEMMA_PORT}/embed"

# batéria dotazov na zbieranie zivej union (count z `list` klame cez soft-delete)
_QUERIES = [
    "identita Zolander veducko humor mentor",
    "pamat recall YAR BM25 Gemma embedding vektor decay",
    "projekt uloha termin rozpocet dodavatel faktura zmluva",
    "nakup material dodavka objednavka sklad pobocka",
    "sandbox zamknuty server shell prikaz bezpecnost firewall",
    "HyperspaceDB kolekcia lorentz cosine port container OrbStack",
    "LLM API key provider Opus Sonnet GPT Gemini fallback Groq",
    "geometria hyperbolicka cone strom hierarchia klaster product-space",
    "gateway WhatsApp Beeper Matrix bridge notify",
    "git push repo sanitizacia commit skill hermes",
    "dedup dream loop konsolidacia salience supersede",
    "zolo2.0 kniha atom klasifikacia pipeline turiec",
    "anti halucinacia sycophancy zrkadlo verifikacia F11",
    "cron watchdog notifikacia iniciativa daemon launchd",
    "peer A2A Ed25519 podpis peer identity",
    "python subprocess venv toolkit cesta interpreter torch",
    "reasoning lens gate abstrakcia ascend pattern",
    "gabber hardcore techno 909 kick distorzia analog elektronika",
    "browser Obscura stealth playwright scraping",
    "fikcia postava kontaminacia hranica",
]


# ── nizkourovnove helpery ────────────────────────────────────────────────────
def hs(cmd, *args, stdin=None, timeout=60):
    """Node SDK most. Vrati parsnuty JSON alebo None. Raise pri nenulovom exite."""
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True,
                       env=NODE_ENV, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd} zlyhal: {p.stderr[-400:]}")
    out = p.stdout.strip()
    return json.loads(out) if out else None


def hs_try(cmd, *args, stdin=None, timeout=60):
    """Ako hs(), ale nevyhadzuje — vrati (ok: bool, data_or_err)."""
    try:
        return True, hs(cmd, *args, stdin=stdin, timeout=timeout)
    except Exception as e:
        return False, str(e)[-300:]


def hs_insert_clean(col, mid, rec, timeout=60):
    """Insert co PREBIJE soft-delete tombstone (serverovy bug: re-insert ID s
    existujucim tombstonom hlasi inserted:1 ale bod NEVZNIKNE — overene 2026-08-30
    na id 472). FIX: del PRED insert. Na novom ID je del no-op (deleted:false),
    na tombstone ho vycisti. Vracia (ok, data_or_err) z insertu."""
    hs_try("del", col, str(mid), timeout=timeout)  # vycisti pripadny tombstone
    return hs_try("insert", col, stdin=rec, timeout=timeout)


def gemma_embed(texts, mode="document"):
    """Gemma 768D cez perzistentny daemon :8901. Raise ak daemon nebezi."""
    body = json.dumps({"texts": texts, "mode": mode}).encode()
    req = urllib.request.Request(GEMMA_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["vectors"]


def _yar_embed_one(text):
    """Lazy import YAR (torch) — len ked reálne treba lorentz vektor."""
    from embed_yar import embed_one
    return embed_one(text)


def _repair_append(op, mid, side, note=""):
    """Zapis nevybavenej strany do repair fronty (namiesto ticheho except:pass)."""
    os.makedirs(STATE, exist_ok=True)
    with open(REPAIR, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "op": op, "id": mid, "side": side, "note": note[:200]},
                           ensure_ascii=False) + "\n")


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def index_ids():
    return {r["id"] for r in _load_jsonl(IDX) if "id" in r}


def index_rows_by_id():
    d = {}
    for r in _load_jsonl(IDX):
        if "id" in r:
            d[r["id"]] = r
    return d


def trash_ids():
    ids = set()
    for r in _load_jsonl(TRASH):
        rm = r.get("removed", {})
        if isinstance(rm, dict) and "id" in rm:
            ids.add(rm["id"])
    return ids


def live_union(col, embedder, mode):
    """Reálne zive ID = union search cez bateriu dotazov (count z `list` klame)."""
    seen = set()
    for q in _QUERIES:
        try:
            vec = embedder(q) if col == LOR_COL else embedder([q], mode)[0]
            for r in (hs("search", col, 300, stdin=json.dumps({"vector": vec})) or []):
                seen.add(r.get("id"))
        except Exception as e:
            print(f"  ! union dotaz zlyhal ({col}): {q[:24]} -> {e}", file=sys.stderr)
    return seen


def confirm_present(col, mid, text, embedder, mode, topk=8):
    """DETERMINISTICKE per-ID overenie: embedni VLASTNY text zaznamu a pozri, ci sa
    dane ID vrati v top-K. Na rozdiel od live_union (nahodna bateria) je toto stabilne
    pre konkretne ID — takto chytime tombstone obete co bateria raz vrati, raz nie."""
    if not text:
        return True  # bez textu nevieme overit -> netvrdime ze chyba
    try:
        vec = embedder(text) if col == LOR_COL else embedder([text], mode)[0]
        ids = [r.get("id") for r in (hs("search", col, topk, stdin=json.dumps({"vector": vec})) or [])]
        return mid in ids
    except Exception:
        return True  # pri chybe embedu radsej netvrd ze chyba (fail-safe voci mazaniu)


def truly_missing(col, idx_by_id, union, embedder, mode):
    """Index ID co NIE su v union — potvrd kazde self-query (odfiltruj union nedeterminizmus)."""
    out = []
    for mid in sorted(set(idx_by_id) - union):
        if not confirm_present(col, mid, (idx_by_id[mid].get("text") or ""), embedder, mode):
            out.append(mid)
    return out


# ── CHOKEPOINT API — cez toto ide KAZDY zapis/mazanie ────────────────────────
def put(mid, text, meta, *, vec=None, gvec=None, append_index=True):
    """Vloz JEDEN zaznam do OBOCH kolekcii + (volitelne) index.

    vec  = hotovy lorentz 129D (ak None, embedne sa cez YAR)
    gvec = hotovy gemma 768D  (ak None, embedne sa cez daemon)
    meta = plne meta pre lorentz (kind, memory_type, layer, salience, ... _hs_*).
           Do gemmy ide odlahcene meta (kind, layer, text) — 3. lens nepotrebuje HMAC.

    Vracia dict {lorentz, gemma, gvec}. Ked strana zlyha -> zapise do repair fronty
    (NIE ticho). Lorentz je autorita: ak lorentz zlyha, je to tvrda chyba (raise).
    """
    if vec is None:
        vec = _yar_embed_one(text)
    # 1) LORENTZ (autorita) — musi prejst, inak zaznam neexistuje.
    # del-pred-insert prebije pripadny soft-delete tombstone (server bug).
    lrec = json.dumps({"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n"
    ok_l, err_l = hs_insert_clean(LOR_COL, mid, lrec)
    if not ok_l:
        raise RuntimeError(f"lorentz insert zlyhal id={mid}: {err_l}")

    # 2) GEMMA (3. lens) — ked padne, NEzhltnut: repair fronta to dobehne
    gem_ok = False
    if gvec is None:
        try:
            gvec = gemma_embed([text], "document")[0]
        except Exception as e:
            _repair_append("put", mid, GEM_COL, f"embed:{e}")
            gvec = None
    if gvec is not None:
        grec = json.dumps({"id": mid, "vector": gvec,
                           "meta": {"kind": meta.get("kind"), "layer": meta.get("layer"),
                                    "text": text[:300]}}, ensure_ascii=False) + "\n"
        ok, err = hs_insert_clean(GEM_COL, mid, grec)
        gem_ok = ok
        if not ok:
            _repair_append("put", mid, GEM_COL, f"insert:{err}")

    # 3) INDEX (BM25 + decay) — jediny enumerovatelny zdroj pravdy
    if append_index:
        os.makedirs(STATE, exist_ok=True)
        with open(IDX, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": mid, "col": LOR_COL,
                "kind": meta.get("kind"), "layer": meta.get("layer"),
                "salience": meta.get("salience"),
                "base_salience": round(float(meta.get("salience", 0.5) or 0.5), 3),
                "confidence": meta.get("confidence"),
                "source": meta.get("source"), "project": meta.get("project"),
                "certainty": meta.get("certainty", "explicit"),
                "premises": meta.get("premises", []),
                "ts": meta.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                "text": text[:300],
            }, ensure_ascii=False) + "\n")

    return {"lorentz": True, "gemma": gem_ok, "gvec": gvec}


def delete(mid, *, remove_index=True, trash_rec=None, reason="delete"):
    """Zmaz JEDEN zaznam z OBOCH kolekcii + (volitelne) indexu.

    Lorentz je autorita: ak lorentz del zlyha, do repair fronty (skusi sa znovu).
    Gemma del zlyhanie tiez do fronty (aby nezostal duch ako doteraz).
    trash_rec: ak dodany, zapise sa do dedup_trash.jsonl (recoverable stopa).
    Vracia dict {lorentz, gemma}.
    """
    ok_l, err_l = hs_try("del", LOR_COL, str(mid))
    lor_deleted = ok_l and isinstance(err_l, dict) and err_l.get("deleted") is True
    if not ok_l:
        _repair_append("del", mid, LOR_COL, str(err_l))

    ok_g, err_g = hs_try("del", GEM_COL, str(mid))
    gem_deleted = ok_g and isinstance(err_g, dict) and err_g.get("deleted") is True
    if not ok_g:
        _repair_append("del", mid, GEM_COL, str(err_g))

    if remove_index:
        rows = _load_jsonl(IDX)
        kept = [r for r in rows if r.get("id") != mid]
        if len(kept) != len(rows):
            with open(IDX, "w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        # FAIL-SAFE proti orphan hranam (2026-09-03): ked uzol zmizne z indexu
        # (jedina autorita o tom co ma zit), jeho hrany su z definicie orphany.
        # Volajuce cesty (dedup_dream, manual_dedup) robia reparent PRED delete,
        # ale reparent je fail-open ("hrany ostali") -> pri jeho zlyhani vznikal
        # duch v grafe co nafukoval communities()/cut_vertices. Invariant:
        # uzol nie je v indexe <=> nema hrany. Ak reparent uspel, toto je no-op.
        # Fail-open: graf NESMIE zhodit delete (autorita je DB+index, nie graf).
        try:
            import zol_graph
            g_edges = zol_graph._read(zol_graph.EDGES)
            g_keep = [e for e in g_edges
                      if e.get("from") != mid and e.get("to") != mid]
            if len(g_keep) != len(g_edges):
                zol_graph._rewrite_edges(g_keep)
        except Exception as e:
            _repair_append("edge_prune", mid, "graph", str(e))

    if trash_rec is not None:
        os.makedirs(STATE, exist_ok=True)
        with open(TRASH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "removed": trash_rec, "reason": reason},
                               ensure_ascii=False) + "\n")

    return {"lorentz": lor_deleted, "gemma": gem_deleted}


# ── SYNC — zosulad obe kolekcie s indexom (zdroj pravdy) ─────────────────────
def sync(dry=False):
    """Zosulad OBE kolekcie so zoznamom v indexe (zive ID).

    CIEL: lorentz aj gemma maju presne ID z indexu (nic navyse = ziadne soft-deleted
    duchy, nic naviac). Idempotentne, spustatelne opakovane.

    Kroky:
      1) GEMMA duchy: zmaz z gemmy vsetky trash_ids A vsetky zive-union ID co NIE su
         v indexe (to su duchy co gemma drzi navyse).
      2) GEMMA chyby: kazde index ID co NIE je v gemma-union -> re-embedni a vloz.
      3) LORENTZ duchy: zmaz z lorentz vsetky trash_ids (co su este zive).
      4) LORENTZ chyby: index ID mimo lorentz-union -> re-embedni (YAR) a vloz.
    """
    idx_by_id = index_rows_by_id()
    idx = set(idx_by_id)
    trash = trash_ids()

    print("[sync] zbieram zivu union (lorentz YAR)...", file=sys.stderr)
    lor = live_union(LOR_COL, _yar_embed_one, None)
    print("[sync] zbieram zivu union (gemma :8901)...", file=sys.stderr)
    gem = live_union(GEM_COL, gemma_embed, "query")

    plan = {
        "index": len(idx), "lorentz_union": len(lor), "gemma_union": len(gem),
        "trash": len(trash),
        # GHOST = v DB, a NIE v indexe. Index je JEDINA autorita.
        # Trash je len archiv, NIE mazaci prikaz — zaznam co je v indexe (zivy)
        # sa NIKDY nemaze, aj keby historicky presiel trashom (napr. 382/631:
        # zive identity/PROTECT fakty co boli aj v dedup_trash).
        "gemma_ghosts_to_del": sorted(gem - idx),
        "gemma_missing_to_add": truly_missing(GEM_COL, idx_by_id, gem, gemma_embed, "document"),
        "lorentz_ghosts_to_del": sorted(lor - idx),
        "lorentz_missing_to_add": truly_missing(LOR_COL, idx_by_id, lor, _yar_embed_one, None),
    }
    if dry:
        plan["mode"] = "dry-run"
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return plan

    done = {"gemma_del": 0, "gemma_add": 0, "lorentz_del": 0, "lorentz_add": 0, "fail": []}

    # 1) GEMMA duchy preč
    for mid in plan["gemma_ghosts_to_del"]:
        ok, err = hs_try("del", GEM_COL, str(mid))
        if ok:
            done["gemma_del"] += 1
        else:
            done["fail"].append({"op": "gem_del", "id": mid, "err": str(err)[:120]})

    # 2) GEMMA chyby dopln (batchovy embed z indexu)
    add_g = plan["gemma_missing_to_add"]
    if add_g:
        texts = [(idx_by_id[m].get("text") or "") for m in add_g]
        try:
            vecs = gemma_embed(texts, "document")
            lines = []
            for m, v in zip(add_g, vecs):
                r = idx_by_id[m]
                # prebi tombstone: del pred (batch) insertom, inak insert ticho prepadne
                hs_try("del", GEM_COL, str(m))
                lines.append(json.dumps({"id": m, "vector": v,
                                         "meta": {"kind": r.get("kind"), "layer": r.get("layer"),
                                                  "text": (r.get("text") or "")[:300]}},
                                        ensure_ascii=False))
            ok, err = hs_try("insert", GEM_COL, stdin="\n".join(lines) + "\n")
            if ok:
                done["gemma_add"] = len(lines)
            else:
                done["fail"].append({"op": "gem_add_batch", "err": str(err)[:160]})
        except Exception as e:
            done["fail"].append({"op": "gem_embed", "err": str(e)[:160]})

    # 3) LORENTZ duchy preč
    for mid in plan["lorentz_ghosts_to_del"]:
        ok, err = hs_try("del", LOR_COL, str(mid))
        if ok:
            done["lorentz_del"] += 1
        else:
            done["fail"].append({"op": "lor_del", "id": mid, "err": str(err)[:120]})

    # 4) LORENTZ chyby dopln (YAR embed po jednom — 129D)
    for mid in plan["lorentz_missing_to_add"]:
        r = idx_by_id[mid]
        text = r.get("text") or ""
        if not text:
            continue
        try:
            vec = _yar_embed_one(text)
            meta = {"kind": r.get("kind"), "memory_type": r.get("kind"),
                    "layer": r.get("layer"), "salience": r.get("salience"),
                    "confidence": r.get("confidence"), "ts": r.get("ts"),
                    "text": text[:300], "source": "sync_backfill"}
            rec = json.dumps({"id": mid, "vector": vec, "meta": meta}, ensure_ascii=False) + "\n"
            ok, err = hs_insert_clean(LOR_COL, mid, rec)
            if ok:
                done["lorentz_add"] += 1
            else:
                done["fail"].append({"op": "lor_add", "id": mid, "err": str(err)[:120]})
        except Exception as e:
            done["fail"].append({"op": "lor_embed", "id": mid, "err": str(e)[:120]})

    out = {"mode": "commit", "plan": plan, "done": done}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def repair():
    """Dobehni nevybavene strany z mem_repair.jsonl (put/del co predtym zlyhali)."""
    items = _load_jsonl(REPAIR)
    if not items:
        print(json.dumps({"repair": "prazdna fronta"}, ensure_ascii=False))
        return
    # najjednoduchsie a bezpecne: repair = spusti sync (idempotentny), potom vycisti frontu
    print(f"[repair] {len(items)} poloziek vo fronte -> spustam sync", file=sys.stderr)
    sync(dry=False)
    # archiv fronty (nezahadzuj, len odsun)
    os.replace(REPAIR, REPAIR + "." + time.strftime("%Y%m%dT%H%M%S") + ".done")
    print(json.dumps({"repair": "hotovo", "vybavene": len(items)}, ensure_ascii=False))


def status():
    idx_by_id = index_rows_by_id()
    idx = set(idx_by_id)
    print("[status] zbieram zivu union (lorentz)...", file=sys.stderr)
    lor = live_union(LOR_COL, _yar_embed_one, None)
    print("[status] zbieram zivu union (gemma)...", file=sys.stderr)
    gem = live_union(GEM_COL, gemma_embed, "query")
    tr = trash_ids()
    counts = {c["name"]: c.get("count") for c in (hs("list") or [])
              if c["name"] in (LOR_COL, GEM_COL)}
    rep = _load_jsonl(REPAIR)
    # DETERMINISTICKE potvrdenie chybajucich (odfiltruj union nedeterminizmus)
    gem_missing = truly_missing(GEM_COL, idx_by_id, gem, gemma_embed, "document")
    lor_missing = truly_missing(LOR_COL, idx_by_id, lor, _yar_embed_one, None)
    gem_extra = sorted(gem - idx)
    lor_extra = sorted(lor - idx)
    print(json.dumps({
        "count_z_list (klame)": counts,
        "index (zdroj pravdy)": len(idx),
        "lorentz_union (zive)": len(lor),
        "gemma_union (zive)": len(gem),
        "gemma navyse oproti indexu": gem_extra,
        "lorentz navyse oproti indexu": lor_extra,
        "index chyba v gemma (potvrdene)": gem_missing,
        "index chyba v lorentz (potvrdene)": lor_missing,
        "trash": len(tr),
        "repair fronta": len(rep),
        "SYNCED": not (gem_extra or lor_extra or gem_missing or lor_missing),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "sync":
        sync(dry="--dry" in sys.argv)
    elif cmd == "repair":
        repair()
    else:
        print(f"neznamy prikaz: {cmd} (status|sync|repair)", file=sys.stderr)
        sys.exit(1)
