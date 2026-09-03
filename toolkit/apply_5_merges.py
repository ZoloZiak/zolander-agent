#!/usr/bin/env python3
"""apply_5_merges.py — aplikuj PRESNE 5 schvalenych merge z dream dry-run.

NIE druhy dream beh (ten je nedeterministicky -> mohol by 494 skusit znova).
Deterministicky vezmi 5 parov co veducko schvalil, 494<-504 VYNECHAJ (pasca:
osobny fakt 'rodeny Slovak/praca' vs housing preferencia = NIE su duplikaty).

Kazdy removed: soft-delete z Lorentz zol_mem AJ z zol_mem_gemma (inak zombie!),
reparent hran na keepera, trash stopa, sync index. Presne vzor dedup_dream ale
s Gemma delete navyse (dedup_dream._del_point Gemmu NEmaze = jeho bug).
"""
import os, sys, json, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV

STATE = os.path.expanduser("~/projects/zolander/state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
MEM_COL = "zol_mem"
GEMMA_COL = "zol_mem_gemma"

# 5 schvalenych parov (kept <- removed). 494<-504 VYNECHANE (pasca).
MERGES = [
    {"kept": 474, "removed": 382, "reason": "macOS + osloveni vedúcko (474 ma navyse F11 feedback)"},
    {"kept": 572, "removed": 496, "reason": "zamknuty Mac bez admin prav"},
    {"kept": 600, "removed": 590, "reason": "zasada: overeny fakt rusi redundantnu obavu"},
    {"kept": 558, "removed": 571, "reason": "realita systemu = dolozitelna historia, nie povrch"},
    {"kept": 640, "removed": 631, "reason": "identita/pravda = verifikovatelny zaznam (oba ascend-semantic)"},
]
PROTECTED = {494, 504}  # NIKDY nemazat — osobny fakt + housing pref

DRY = "--dry-run" in sys.argv


def hs_del(col, pid):
    try:
        p = subprocess.run([NODE, HS, "del", col, str(pid)],
                           capture_output=True, text=True, env=NODE_ENV, timeout=30)
        return p.returncode == 0 and '"deleted":true' in p.stdout
    except subprocess.TimeoutExpired:
        return False


def main():
    rows = [json.loads(l) for l in open(IDX) if l.strip()]
    byid = {r["id"]: r for r in rows}

    # sanity: keeper aj removed musia byt v indexe, removed nesmie byt protected
    plan = []
    for m in MERGES:
        k, r = m["kept"], m["removed"]
        if r in PROTECTED:
            print(f"[SKIP] {r} je PROTECTED — nemazem"); continue
        if k not in byid:
            print(f"[WARN] keeper {k} nie je v indexe — preskakujem par"); continue
        if r not in byid:
            print(f"[skip] removed {r} uz nie je v indexe (mozno zmazany skor)"); continue
        plan.append(m)

    print(f"{'[DRY] ' if DRY else ''}plan: {len(plan)} merge, PROTECTED={sorted(PROTECTED)}")
    for m in plan:
        print(f"  {m['removed']} -> {m['kept']}  ({m['reason']})")
    if DRY:
        print("[dry-run] nic sa nezmazalo"); return

    import zol_graph
    removed_ok = set()
    del_fail = []
    for m in plan:
        k, r = m["kept"], m["removed"]
        lor = hs_del(MEM_COL, r)
        if not lor:
            print(f"[FAIL] Lorentz del {r} zlyhal — preskakujem (DB nedotknuta)")
            del_fail.append(r); continue
        gem = hs_del(GEMMA_COL, r)  # KLUCOVE: aj Gemma, inak zombie
        try:
            rp = zol_graph.reparent(r, k)
            print(f"  reparent {r}->{k}: migrated={rp['migrated']} selfloop={rp['dropped_selfloop']} dup={rp['dropped_dup']}")
        except Exception as e:
            print(f"  [warn] reparent {r}->{k} zlyhal (hrany ostali): {e!r}")
        with open(TRASH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "removed": byid[r], "reason": m["reason"],
                                "merged_into": k, "gemma_deleted": gem},
                               ensure_ascii=False) + "\n")
        removed_ok.add(r)
        print(f"  merge {r}->{k}: lorentz=OK gemma={'OK' if gem else 'FAIL/absent'}")

    # sync index — vyhod zmazane
    if removed_ok:
        import shutil
        shutil.copy(IDX, IDX + ".bak")
        kept = [r for r in rows if r["id"] not in removed_ok]
        with open(IDX, "w", encoding="utf-8") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"index: {len(rows)} -> {len(kept)} (backup .bak)")

    print(json.dumps({"merged": sorted(removed_ok), "del_fail": del_fail,
                      "protected": sorted(PROTECTED)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
