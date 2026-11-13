#!/usr/bin/env python3
"""reconcile_guard.py — detektor TICHÉHO driftu pamäte (Bug 1 prevencia).

Pamäť žije v 3 skladoch na ten istý fakt:
  - DB zol_mem        (Lorentz 129D)  — count z `list` je nafúknutý (soft-delete+diery)
  - DB zol_mem_gemma  (cosine 768D)   — 3. lens
  - state/mem_index.jsonl              — BM25 lane + decay (JEDINÝ enumerovateľný, zdroj pravdy)

Keď sa rozídu, časť recall lanes oslepne. Tento guard to CHYTÍ skôr, než sa to udeje ticho.

DETEKCIA (default, read-only):
  - reálny počet živých v DB = UNION viacerých `search` dotazov (NIE count!),
  - ORPHAN = živý v DB, chýba v indexe → slepý pre BM25/decay,
  - IDX-ONLY = v indexe, DB search nevrátil (môže byť len hlbšie v ranku, over),
  - ZOMBIE = živý v Gemma, ale nie v Lorentz (zle zmazaný),
  - exit code: 0 ak čisté, 2 ak drift (pre cron/dream alert).

FIX (--fix): dopíše ŽIVÝCH orphanov do mem_index.jsonl z DB meta (BM25-viditeľné,
  BEZ nových ID, append). NErobí Gemma/HMAC — tie orphany, čo sú aj mimo Gemma,
  reportuje zvlášť ako "ručne cez rescue". Konzervatívne: junk sa nebackfilluje
  automaticky (rozhoduje človek), preto --fix len dopĺňa, nikdy nemaže.
"""
import os, sys, json, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT
from embed_yar import embed_one

STATE = os.path.join(ZROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
MEM_COL = "zol_mem"
FIX = "--fix" in sys.argv

# batéria dotazov naprieč témami — cieľ je pokryť celú pamäť (union živých ID)
QUERIES = [
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


def hs(cmd, *args, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd}: {p.stderr[-200:]}")
    out = p.stdout.strip()
    return json.loads(out) if out else None


def gemma_embed(q):
    """Gemma 768D cez daemon :8901 (query mode). Gemma kolekcia NIE je YAR 129D!"""
    import urllib.request
    port = os.environ.get("GEMMA_EMBED_PORT", "8901")
    body = json.dumps({"texts": [q], "mode": "query"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["vectors"][0]


def db_live_union(col, embedder):
    """Reálne živé ID = union search dotazov (count klame cez soft-delete).
    POZOR: embedder MUSÍ sedieť dimenziou kolekcie — YAR 129D pre zol_mem,
    Gemma 768D pre zol_mem_gemma. Zlá dimenzia => search vráti prázdno (tichý
    fail) a zombie-detekcia oslepne."""
    seen = {}
    for q in QUERIES:
        try:
            vec = embedder(q)
            for r in (hs("search", col, 300, stdin=json.dumps({"vector": vec})) or []):
                seen[r.get("id")] = r
        except Exception as e:
            print(f"  ! dotaz zlyhal ({col}): {q[:24]} -> {e}", file=sys.stderr)
    return seen


# --- zdroje ---
idx_rows = []
with open(IDX, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            idx_rows.append(json.loads(line))
idx_ids = {r["id"] for r in idx_rows}

trash_ids = set()
if os.path.exists(TRASH):
    for line in open(TRASH, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line).get("removed", {})
        if isinstance(r, dict) and "id" in r:
            trash_ids.add(r["id"])

counts = {c["name"]: c.get("count") for c in (hs("list") or [])}

print("[reconcile] zbieram DB-live union (Lorentz, YAR 129D)...", file=sys.stderr)
lor = db_live_union(MEM_COL, embed_one)
lor_ids = set(lor)
print("[reconcile] zbieram DB-live union (Gemma, 768D cez :8901)...", file=sys.stderr)
try:
    gem = db_live_union("zol_mem_gemma", gemma_embed)
except Exception as e:
    print(f"  ! Gemma union zlyhal cely: {e}", file=sys.stderr)
    gem = {}
gem_ids = set(gem)
gemma_ok = len(gem_ids) > 0  # ak 0, daemon padol -> zombie-detekcia NEspolahliva

orphans = (lor_ids - idx_ids) - trash_ids          # živé v Lorentz, chýbajú v indexe
idx_only = idx_ids - lor_ids                        # v indexe, Lorentz search nevrátil
# ZOMBIE = živé v Gemma, mŕtve v Lorentz A ZAROVEN NIE v indexe. Podmienka `- idx_ids`
# je KRITICKA (2026-08-30 fix): index je zdroj pravdy o tom co MA zit. Ak je zaznam
# v indexe AJ v Gemma, je to ZIVY zaznam a "chyba v Lorentz union" je len false-positive
# neuplneho nedeterministickeho searchu (YAR slaby na parafrazu ~52%, kod r.391). Bez
# tejto podmienky guard falosne krical "zombie" na zive L1/L3 principy pri KAZDOM behu.
zombie_cand = (gem_ids - lor_ids) - trash_ids - idx_ids
orphan_no_gemma = orphans - gem_ids                 # orphan aj mimo Gemma = plná slepota

# POZOR: Lorentz union je NEÚPLNÝ (search nedeterministický ~513/611). "Nie je v union"
# != "zmazaný". Preto KAŽDÉHO zombie-kandidáta CIELENE over: embedni jeho vlastný text
# a pozri či sa vráti v top-5. Ak áno -> živý (false-positive union). Inak -> reálny zombie.
def _text_of(cid):
    r = gem.get(cid) or lor.get(cid) or {}
    return (r.get("meta", {}) or {}).get("text", "")

zombies = []
for cid in sorted(zombie_cand):
    t = _text_of(cid)
    if not t:
        zombies.append(cid)  # bez textu neoverím -> konzervatívne nahlás
        continue
    try:
        res = hs("search", MEM_COL, 5, stdin=json.dumps({"vector": embed_one(t)})) or []
        if cid not in [r.get("id") for r in res]:
            zombies.append(cid)  # ani na vlastný text sa nevrátil = reálne preč z Lorentz
    except Exception:
        zombies.append(cid)

drift = bool(orphans or zombies)

report = {
    "counts_z_list (nafuknute)": {k: counts.get(k) for k in ("zol_mem", "zol_mem_gemma")},
    "index_pocet": len(idx_ids),
    "db_live_lorentz (union)": len(lor_ids),
    "db_live_gemma (union)": len(gem_ids),
    "gemma_daemon_ok": gemma_ok,
    "trash_pocet": len(trash_ids),
    "ORPHANS (zive v DB, nie v indexe)": sorted(orphans),
    "  z toho aj mimo Gemma (plna slepota)": sorted(orphan_no_gemma),
    "ZOMBIES (zive v Gemma, mrtve v Lorentz)": sorted(zombies),
    "idx_only (v indexe, Lorentz search nevratil)": len(idx_only),
    "DRIFT": drift,
}
if not gemma_ok:
    report["POZOR"] = ("Gemma union=0 -> daemon :8901 nebezi? "
                       "ZOMBIE detekcia NESPOLAHLIVA (spusti gemma daemon a znovu).")

# --- FIX: dopíš živých orphanov do indexu z DB meta ---
fixed = []
if FIX and orphans:
    with open(IDX, "a", encoding="utf-8") as f:
        for oid in sorted(orphans):
            m = (lor.get(oid) or {}).get("meta", {}) or {}
            text = m.get("text") or ""
            if not text:
                continue  # bez textu nemá zmysel dopísať do BM25
            row = {
                "id": oid, "col": MEM_COL,
                "kind": m.get("kind", "semantic"),
                "layer": m.get("layer", "L0"),
                "salience": float(m.get("salience", 0.5) or 0.5),
                "base_salience": round(float(m.get("salience", 0.5) or 0.5), 3),
                "confidence": float(m.get("confidence", 0.7) or 0.7),
                "ts": m.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                "text": text[:300],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            fixed.append(oid)
    report["FIXED (dopisane do indexu)"] = fixed
    if orphan_no_gemma:
        report["POZOR rucne (orphan mimo Gemma -> chyba 3. lens)"] = sorted(orphan_no_gemma)

print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(2 if (drift and not FIX) else 0)
