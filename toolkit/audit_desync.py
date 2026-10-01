#!/usr/bin/env python3
"""audit_desync.py — Bug 1 diagnostika: zisti presne ktore ID su kde.

Zdroje:
  - mem_index.jsonl (BM25 lane, enumerovatelny)
  - DB zol_mem (Lorentz) — nevie sa enumerovat (getPoints halucinuje), ale search
    s velkym topK vrati vsetky ZIVE body (soft-deleted sa nevracaju).
  - zol_mem_gemma (cosine) — to iste, cez Gemma daemon.
  - dedup_trash.jsonl (soft-deleted duchovia)

Cielom je najst ZIVE DB-only ID (v DB search vratene, ale chybaju v indexe) =
realna slepota BM25. Tie treba zachranit PRED akymkolvek rebuildom.

Bez torch pre Gemma; YAR embed cez tento venv. Batéria neutralnych dotazov +
vysoke topK, zozbieraj vsetky vratene ID (union).
"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV, ZROOT
from embed_yar import embed_one

STATE = os.path.join(ZROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")

def hs(cmd, *args, stdin=None):
    p = subprocess.run([NODE, HS, cmd, *[str(a) for a in args]],
                       input=stdin, capture_output=True, text=True, env=NODE_ENV)
    if p.returncode != 0:
        raise RuntimeError(f"hs {cmd}: {p.stderr[-300:]}")
    out = p.stdout.strip()
    return json.loads(out) if out else None

# index ID
idx_ids = set()
with open(IDX) as f:
    for line in f:
        line = line.strip()
        if line:
            idx_ids.add(json.loads(line)["id"])

# trash ID (soft-deleted duchovia)
trash_ids = set()
if os.path.exists(TRASH):
    for line in open(TRASH):
        line = line.strip()
        if not line: continue
        r = json.loads(line).get("removed", {})
        if isinstance(r, dict) and "id" in r:
            trash_ids.add(r["id"])

# batéria dotazov napriec temami — zozbieraj VSETKY zive ID z DB search
QUERIES = [
    "identita Zolander veducko humor mentor",
    "pamat recall YAR BM25 Gemma embedding vektor",
    "zdravie lekar vysetrenie poistovna",
    "byvanie example district prenajom izba",
    "sandbox zamknuty Mac MDM shell prikaz bezpecnost",
    "HyperspaceDB kolekcia lorentz cosine port container",
    "Palantir LLM proxy token Opus Sonnet GPT Gemini",
    "geometria hyperbolicka cone strom hierarchia klaster",
    "gateway WhatsApp Beeper Matrix fallback Groq",
    "git push repo sanitizacia commit skill",
    "dedup dream loop konsolidacia decay salience",
    "zolo2.0 kniha atom klasifikacia pipeline",
    "anti halucinacia sycophancy zrkadlo verifikacia",
    "cron watchdog notifikacia iniciativa daemon",
    "peer A2A Ed25519 podpis peer",
    "python subprocess launchd venv toolkit cesta",
    "reasoning lens gate abstrakcia ascend pattern",
    "fikcia postava kontaminacia",
]
seen = {}
for q in QUERIES:
    try:
        vec = embed_one(q)
        res = hs("search", "zol_mem", 300, stdin=json.dumps({"vector": vec})) or []
        for r in res:
            seen[r.get("id")] = r
    except Exception as e:
        print(f"  ! dotaz zlyhal: {q[:30]} -> {e}", file=sys.stderr)

db_ids = set(seen.keys())
db_only = db_ids - idx_ids            # v DB vratene, chybaju v indexe
idx_only = idx_ids - db_ids           # v indexe, DB search ich nevratil (mozno hlbsie)
db_only_live = db_only - trash_ids    # DB-only a NIE su medzi zmazanymi = realni kandidati na stratu

print(json.dumps({
    "index_pocet": len(idx_ids),
    "trash_pocet": len(trash_ids),
    "db_search_unikatnych_ID": len(db_ids),
    "db_only (v DB, nie v indexe)": len(db_only),
    "  z toho v trash (ocakavane)": len(db_only & trash_ids),
    "  z toho ZIVE (strata?!)": sorted(db_only_live),
    "idx_only (v indexe, DB search nevratil)": len(idx_only),
    "idx_only vzorka": sorted(idx_only)[:30],
}, ensure_ascii=False, indent=2))

# vypis texty zivych DB-only (co by rebuild z indexu zahodil)
if db_only_live:
    print("\n=== ZIVE DB-only zaznamy (kandidati na zachranu) ===")
    for i in sorted(db_only_live):
        m = seen[i].get("meta", {}) or {}
        print(f"[{i}] kind={m.get('kind')} layer={m.get('layer')} :: {(m.get('text') or '')[:120]}")
