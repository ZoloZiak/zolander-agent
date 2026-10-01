#!/usr/bin/env python3
"""Audit straty informacie z historickych dedup-merge (2026-09-02).
Otazka: zmazal niektory HISTORICKY nocny merge fakt, ktoreho informacia NIE JE
v ziadnom aktualne zijucom zazname? = reálna strata na obnovu.

Metoda: Opus dostane VSETKY podozrive removed texty naraz + CELY zijuci index ako
referenciu. Pre kazdy removed posudi SEMANTICKY (nie char-level), ci je jeho info
plne pokryta aspon jednym zijucim zaznamom. Vrati len NEPOKRYTE (kandidati na obnovu).
Fail-closed: co Opus oznaci coverage=false ide na rucnu revziu, NIC sa automaticky
neobnovuje (obnova = samostatny krok po tvojom pohlade).
"""
import json, os, sys, signal

ROOT = os.path.expanduser("~/projects/zolander")
IDX = os.path.join(ROOT, "state/mem_index.jsonl")
TRASH = os.path.join(ROOT, "state/dedup_trash.jsonl")
OUT = os.path.join(ROOT, "state/dedup_loss_audit.json")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
sys.path.insert(0, os.path.expanduser("~/projects/zolo2.0/toolkit"))
from palantir_client import chat  # noqa: E402

# --- nacitaj zijuci index ---
idx = {}
for l in open(IDX, encoding="utf-8"):
    l = l.strip()
    if l:
        o = json.loads(l)
        idx[o["id"]] = o.get("text", "")

# --- nacitaj trash, vyber merge zaznamy s neprazdnym removed textom ---
cand = {}  # removed_id -> removed_text
for l in open(TRASH, encoding="utf-8"):
    l = l.strip()
    if not l:
        continue
    r = json.loads(l)
    rem = r.get("removed")
    if isinstance(rem, dict) and rem.get("text", "").strip():
        rid = rem.get("id")
        if rid is not None:
            cand[rid] = rem["text"].strip()

print(f"zijuci index: {len(idx)} | kandidati na audit (removed s textom): {len(cand)}")

# --- referencny listing zijuceho indexu (raz, do kazdeho volania) ---
living = "\n".join(f"[{i}] {t}" for i, t in sorted(idx.items()))

SYS = (
    "Si prisny pamatovy audit strat. Dostanes REFERENCIU (zoznam vsetkych AKTUALNE "
    "zijucich faktov v pamati) a DAVKU zmazanych faktov. Pre KAZDY zmazany fakt posud "
    "SEMANTICKY (nie doslovne), ci je vsetka jeho konkretna informacia (fakty, cisla, "
    "mena, adresy, citacie, nuansy) pokryta aspon jednym zijucim faktom v referencii.\n"
    "Vrat CISTY JSON zoznam LEN pre NEPOKRYTE (kde sa realne stratila informacia): "
    '[{"id": <removed_id>, "missing": "<co konkretne chyba v zijucich>"}]. '
    "Ak je vsetko pokryte, vrat []. Ziadny text okolo JSON."
)


def ask(batch):
    listing = "\n".join(f"[{i}] {t}" for i, t in batch)
    prompt = (f"REFERENCIA (zijuce fakty):\n{living}\n\n"
              f"DAVKA zmazanych faktov na posudenie:\n{listing}\n\n"
              "Ktore zmazane fakty NIE su pokryte? JSON:")

    class _T(Exception):
        pass

    def _al(s, f):
        raise _T()
    signal.signal(signal.SIGALRM, _al)
    signal.alarm(300)
    try:
        resp = chat(prompt, model="opus", system=SYS, max_tokens=4000, max_retries=3).strip()
    finally:
        signal.alarm(0)
    if resp.startswith("```"):
        resp = resp.split("```")[1]
        if resp.startswith("json"):
            resp = resp[4:]
    try:
        return json.loads(resp.strip())
    except Exception as e:
        print(f"  PARSE FAIL: {e!r} | resp[:200]={resp[:200]}")
        return None


items = sorted(cand.items())
BATCH = 35
losses = []
parse_fail = 0
for i in range(0, len(items), BATCH):
    b = items[i:i + BATCH]
    print(f"davka @{i}: {len(b)} zmazanych faktov -> opus...")
    r = ask(b)
    if r is None:
        parse_fail += 1
        continue
    for e in r:
        rid = e.get("id")
        losses.append({"id": rid, "missing": e.get("missing", ""),
                       "removed_text": cand.get(rid, "")})
    print(f"  -> nepokrytych v tejto davke: {len(r)}")

json.dump({"candidates": len(cand), "living": len(idx),
           "losses": losses, "parse_fail": parse_fail},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\nHOTOVO. kandidatov={len(cand)} | REALNE STRATY (nepokryte)={len(losses)} "
      f"| parse_fail_davky={parse_fail}")
print(f"vysledok -> {OUT}")
for x in losses:
    print(f"  [{x['id']}] chyba: {x['missing'][:80]}")
