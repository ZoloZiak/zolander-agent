#!/usr/bin/env python3
"""fix_bug2.py — aforizmova vata + identity kontaminacia (memory-distillation Bug 2).

Ascend engine nad-abstrahoval operacne fakty na L3/identity meta-ramce sal=0.8,
ktore recall servíruje prve -> definuju kto Zolander "je". Cast je aktivne
villain-ideologia (bezpecnost=trenie, prezitie>poslusnost, obidi autority).

DVE FAZY (obe cez overene mechaniky, upsert empiricky potvrdeny probe_upsert.py):
  FAZA A: 9 villain -> DELETE (soft-delete Lorentz+Gemma, trash, von z indexu)
  FAZA B: 57 ascend-principov -> UPSERT salience 0.3 (recall ich prestane davat
          navrch) + HMAC podpis (legacy nepodpisane -> prestanu byt [neoverene])
          + zosuladenie mem_index.jsonl (salience + base_salience)

Manifest: state/bug2_manifest.json (villain_delete, downgrade).
--dry-run: nic nezapise, len vypise plan.
"""
import os, sys, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zol_mem as Z

DRY = "--dry-run" in sys.argv
STATE = Z.STATE
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
NEW_SAL = 0.3

man = json.load(open(os.path.join(STATE, "bug2_manifest.json")))
VILLAIN = man["villain_delete"]
DOWNGRADE = man["downgrade"]

idx = [json.loads(l) for l in open(IDX) if l.strip()]
byid = {r["id"]: r for r in idx}

print(f"{'[DRY] ' if DRY else ''}Bug 2 fix — {len(VILLAIN)} villain DELETE, {len(DOWNGRADE)} downgrade UPSERT@{NEW_SAL}")

# --- helper: re-embed + upsert do Lorentz s novou salience + HMAC podpis ---
def upsert_salience(rec, new_sal):
    txt = rec["text"]
    kind = rec.get("kind", "semantic")
    layer = rec.get("layer", "L2")
    vec = Z.embed_one(txt)
    meta = {
        "kind": kind, "memory_type": kind, "layer": layer,
        "salience": round(new_sal, 3),
        "confidence": round(float(rec.get("confidence", 0.7) or 0.7), 3),
        "source": "ascend", "project": "zolander",
        "ts": rec.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "links": "", "text": txt[:300],
    }
    key = Z._hmac_key()
    if key:
        dig = Z._content_digest(kind, kind, "ascend", meta["text"])
        meta["_hs_owner"] = Z._HS_OWNER
        meta["_hs_digest"] = dig
        meta["_hs_sig"] = Z._ownership_sig(Z._HS_OWNER, kind, kind, "ascend", dig, key)
    r = json.dumps({"id": rec["id"], "vector": vec, "meta": meta}, ensure_ascii=False) + "\n"
    Z.hs("insert", Z.MEM_COL, stdin=r)
    return bool(key)

# --- FAZA A: villain delete ---
print("\n=== FAZA A: villain DELETE ===")
trash_lines = []
del_fail = []
for i in VILLAIN:
    r = byid.get(i)
    if not r:
        print(f"  [{i}] NENAJDENY v indexe — skip")
        continue
    print(f"  [{i}] {r['layer']}/{r['kind']} :: {r['text'][:55]}")
    if not DRY:
        try:
            Z.hs("del", Z.MEM_COL, str(i))
        except Exception as e:
            del_fail.append((i, "lorentz", str(e)[:60]))
        try:
            Z.hs("del", "zol_mem_gemma", str(i))
        except Exception as e:
            del_fail.append((i, "gemma", str(e)[:60]))
        trash_lines.append(json.dumps({
            "id": i, "reason": "bug2_villain_ideology", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "layer": r["layer"], "kind": r["kind"], "text": r["text"]}, ensure_ascii=False) + "\n")

# --- FAZA B: downgrade upsert ---
print(f"\n=== FAZA B: downgrade UPSERT@{NEW_SAL} ({len(DOWNGRADE)}) ===")
signed = 0
up_fail = []
if not DRY:
    for i in DOWNGRADE:
        r = byid.get(i)
        if not r:
            continue
        try:
            if upsert_salience(r, NEW_SAL):
                signed += 1
        except Exception as e:
            up_fail.append((i, str(e)[:60]))
    print(f"  upsertnutych: {len(DOWNGRADE)-len(up_fail)}, HMAC podpisanych: {signed}, zlyhanych: {len(up_fail)}")
    if up_fail:
        print(f"  FAIL: {up_fail}")
else:
    print(f"  (dry) upsertol by {len(DOWNGRADE)} zaznamov na salience {NEW_SAL} + HMAC podpis")

# --- prepis indexu: villain von, downgrade salience+base_salience na NEW_SAL ---
if not DRY:
    vset = set(VILLAIN); dset = set(DOWNGRADE)
    new_idx = []
    for r in idx:
        if r["id"] in vset:
            continue
        if r["id"] in dset:
            r["salience"] = NEW_SAL
            r["base_salience"] = NEW_SAL
        new_idx.append(r)
    shutil.copy(IDX, IDX + ".bak")
    with open(IDX, "w") as f:
        for r in new_idx:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(TRASH, "a") as f:
        for l in trash_lines:
            f.write(l)
    print(f"\nindex: {len(idx)} -> {len(new_idx)} (villain von), backup .bak")
    print(f"trash += {len(trash_lines)}")
    if del_fail:
        print(f"DEL FAIL: {del_fail}")
    print(json.dumps({"villain_deleted": len(trash_lines), "downgraded": len(DOWNGRADE)-len(up_fail),
                      "hmac_signed": signed, "del_fail": del_fail, "up_fail": up_fail}, ensure_ascii=False))
else:
    print("\n[DRY] nic nezapisane")
