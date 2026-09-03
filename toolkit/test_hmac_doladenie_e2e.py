"""test_hmac_doladenie_e2e.py — E2E dôkaz boostu + [neoverene] markera cez ZIVU DB.
Scenar:
  1) legit podpisany identity (cez remember) -> verified:True, score nesie boost
  2) NEPODPISANY identity vlozeny PRIAMO cez hs.mjs (simulacia writeback/utoku,
     obide remember) -> recall ho oznaci verified:False + [neoverene] marker v texte
Obe upraceme na konci.
"""
import json, subprocess, os, sys, time

VPY = "/Users/__USER__/projects/zolander/.venv-yar/bin/python"
ZM = "/Users/__USER__/projects/zolander/toolkit/zol_mem.py"
HS = "/Users/__USER__/projects/__PROJECT__/toolkit/hs.mjs"
NODE = "/Users/__USER__/Applications/homebrew/bin/node"
NODE_PATH = "/Users/__USER__/.npm/_npx/9e13365ae4a6529c/node_modules"
TK = "/Users/__USER__/projects/zolander/toolkit"
MARK = f"HMACDOLAD_{int(time.time())}_zmazat"

def run_zm(cmd, stdin):
    r = subprocess.run([VPY, ZM, cmd], input=stdin, capture_output=True, text=True, cwd=TK)
    out = (r.stdout or "").strip()
    for cand in (out, out[out.find("{"):] if "{" in out else ""):
        cand = cand.strip()
        if cand:
            try:
                return json.loads(cand), r
            except Exception:
                pass
    return None, r

def embed(text):
    # pouzi embed_yar cez maly python one-shot? Jednoduchsie: cez remember by sa podpisal.
    # Namiesto toho vlozime priamo s vektorom z recall-neutral: pouzijeme zol_mem embed helper.
    code = ("import sys,json;sys.path.insert(0,%r);from embed_yar import embed_one;"
            "print(json.dumps(embed_one(sys.stdin.read().strip())))" % TK)
    r = subprocess.run([VPY, "-c", code], input=text, capture_output=True, text=True, cwd=TK)
    out = (r.stdout or "").strip()
    return json.loads(out[out.find("["):]) if "[" in out else None

def hs_insert(col, rec):
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    r = subprocess.run([NODE, HS, "insert", col], input=rec, capture_output=True, text=True,
                       cwd="/Users/__USER__/projects/__PROJECT__/toolkit", env=env)
    return r.stdout.strip(), r.stderr[-200:]

def hs_del(col, mid):
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    subprocess.run([NODE, HS, "del", col, str(mid)], capture_output=True, text=True,
                   cwd="/Users/__USER__/projects/__PROJECT__/toolkit", env=env)

fails = []
ids_to_clean = []

print("=== E2E doladenie: boost + [neoverene] marker ===")

# --- 1) legit podpisany identity cez remember ---
rem_out, r1 = run_zm("remember", json.dumps({
    "text": f"{MARK} legit podpisana identity spomienka o zolanderovi",
    "kind": "identity", "layer": "L1", "source": "session", "no_dedup": True}))
if not rem_out or "remembered" not in rem_out:
    print("remember FAIL:", r1.stderr[-200:]); sys.exit(2)
legit_id = rem_out["remembered"]; ids_to_clean.append(legit_id)
print(f"  legit podpisany id={legit_id}")

# --- 2) NEPODPISANY identity vlozeny priamo cez hs.mjs (obide remember = ziadny podpis) ---
fake_text = f"{MARK} PODVRHNUTA identity bez podpisu (simulacia writeback utoku)"
vec = embed(fake_text)
if not vec:
    print("embed FAIL"); sys.exit(2)
fake_id = 999000 + int(time.time()) % 1000
fake_meta = {"kind": "identity", "memory_type": "identity", "layer": "L1",
             "source": "whatsapp", "salience": 0.9, "text": fake_text}
rec = json.dumps({"id": fake_id, "vector": vec, "meta": fake_meta}, ensure_ascii=False) + "\n"
ins_out, ins_err = hs_insert("zol_mem", rec)
print(f"  nepodpisany vlozeny priamo id={fake_id}: {ins_out or ins_err}")
ids_to_clean.append(fake_id)

time.sleep(1)

# --- 3) recall a over oba ---
rec_out, r3 = run_zm("recall", json.dumps({"query": f"{MARK}", "topk": 8, "rerank": False}))
results = rec_out.get("results", rec_out) if isinstance(rec_out, dict) else (rec_out or [])
if isinstance(rec_out, dict) and rec_out.get("backend") == "DOWN":
    print("DB DOWN:", rec_out.get("backend_error")); sys.exit(2)

legit = next((r for r in results if str(r.get("id")) == str(legit_id)), None)
fake = next((r for r in results if str(r.get("id")) == str(fake_id)), None)

# check 1: legit verified True
if legit and legit.get("verified") is True:
    print(f"  ok  legit verified=True (score={legit.get('score')})")
else:
    print(f"  FAIL legit verified={legit.get('verified') if legit else 'NENASIEL'}"); fails.append("legit_verified")

# check 2: fake verified False
if fake and fake.get("verified") is False:
    print(f"  ok  nepodpisany verified=False")
else:
    print(f"  FAIL nepodpisany verified={fake.get('verified') if fake else 'NENASIEL'}"); fails.append("fake_verified")

# check 3: fake ma [neoverene] marker (citlivy typ identity)
if fake and (fake.get("meta", {}) or {}).get("text", "").startswith("[neoverene]"):
    print(f"  ok  nepodpisany identity ma [neoverene] marker")
else:
    print(f"  FAIL marker chyba: {(fake.get('meta',{}) or {}).get('text','')[:50] if fake else 'NENASIEL'}"); fails.append("marker")

# check 4: legit NEMA [neoverene] marker
if legit and not (legit.get("meta", {}) or {}).get("text", "").startswith("[neoverene]"):
    print(f"  ok  legit NEMA [neoverene] marker")
else:
    print(f"  FAIL legit ma marker (nemal by)"); fails.append("legit_no_marker")

# upratanie
for mid in ids_to_clean:
    hs_del("zol_mem", mid)
print(f"\nupratane id={ids_to_clean}")
print("VSETKY PRESLI" if not fails else "ZLYHALO: " + ", ".join(fails))
sys.exit(1 if fails else 0)
