#!/usr/bin/env python3
"""Kontrolny test: robi hs del realne nieco? Zmeraj count -> del jeden -> zmeraj count.
Aj vypis surovy navrat del (returncode + stdout + stderr)."""
import sys, os, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zol_paths import NODE, HS, NODE_ENV

def run(*args):
    p = subprocess.run([NODE, HS, *args], capture_output=True, text=True, env=NODE_ENV)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

def count(col):
    rc, out, err = run("list")
    if rc != 0:
        return None
    for c in json.loads(out):
        if c.get("name") == col:
            return c.get("count")
    return None

before = count("zol_mem")
print("zol_mem count PRED del:", before)

rc, out, err = run("del", "zol_mem", "641")
print(f"del 641 -> rc={rc} stdout={out!r} stderr={err!r}")

after = count("zol_mem")
print("zol_mem count PO del:", after)
print("DELTA:", (after - before) if (before is not None and after is not None) else "N/A")
