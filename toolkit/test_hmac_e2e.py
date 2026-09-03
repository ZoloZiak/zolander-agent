"""test_hmac_e2e.py — E2E cez ZIVU DB: remember podpise -> recall overi verified:True.
Pouziva unikatny marker (upratatelny). Vyzaduje beziacu HyperspaceDB + ZOL_MEM_HMAC_KEY.
"""
import json, subprocess, os, sys, time

VPY = "/Users/__USER__/projects/zolander/.venv-yar/bin/python"
ZM = "/Users/__USER__/projects/zolander/toolkit/zol_mem.py"
MARKER = f"HMAC_E2E_TEST_{int(time.time())}_zmazat"

def run(cmd, stdin):
    r = subprocess.run([VPY, ZM, cmd], input=stdin, capture_output=True,
                       text=True, cwd="/Users/__USER__/projects/zolander/toolkit")
    # embed_yar tlaci progress na STDERR (oddelene). stdout = cisty JSON, ale moze byt
    # viacriadkovy (indent). Skus: (1) cely stdout, (2) od prveho '{' po koniec.
    out = (r.stdout or "").strip()
    for cand in (out, out[out.find("{"):] if "{" in out else ""):
        cand = cand.strip()
        if not cand:
            continue
        try:
            return json.loads(cand), r
        except Exception:
            continue
    return None, r

print("=== E2E HMAC cez zivu DB ===")

# 1) remember podpisany zaznam (identity - najcitlivejsi typ)
rem_in = json.dumps({"text": f"{MARKER} toto je legit podpisana identity spomienka",
                     "kind": "identity", "layer": "L1", "source": "session",
                     "no_dedup": True})
rem_out, r1 = run("remember", rem_in)
print("remember:", rem_out if rem_out else f"(no json) stderr={r1.stderr[-200:]}")

time.sleep(1)

# 2) recall -> najdi nas zaznam, over verified:True
rec_in = json.dumps({"query": f"{MARKER} legit podpisana identity spomienka", "topk": 5})
rec_out, r2 = run("recall", rec_in)
if not rec_out:
    print(f"recall FAIL (no json) stderr={r2.stderr[-300:]}")
    sys.exit(2)

results = rec_out.get("results", rec_out) if isinstance(rec_out, dict) else rec_out
if isinstance(rec_out, dict) and rec_out.get("backend") == "DOWN":
    print("DB DOWN:", rec_out.get("backend_error")); sys.exit(2)

found = None
for r in (results or []):
    txt = (r.get("meta", {}) or {}).get("text", "")
    if MARKER in txt:
        found = r
        break

if not found:
    print(f"NENASIEL nas zaznam v top5 (recall vratil {len(results or [])} vysledkov)")
    print("prvé texty:", [(r.get("meta",{}) or {}).get("text","")[:40] for r in (results or [])[:3]])
    sys.exit(1)

verified = found.get("verified")
print(f"nas zaznam najdeny, verified={verified}")
print(f"  id={found.get('id')} score={found.get('score')}")
ok = verified is True
print("\n" + ("E2E OK — podpisany zaznam round-trip verified:True" if ok
             else f"E2E FAIL — verified={verified} (cakal True)"))
print(f"\nUPRATANIE: node hs.mjs del zol_mem {found.get('id')}  (marker: {MARKER})")
sys.exit(0 if ok else 1)
