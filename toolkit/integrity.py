#!/usr/bin/env python3
"""Zolander F1 — integrity manifest identity suborov.
Rezimy:
  write  -> spocita SHA-256 chranenych suborov, zapise identity/integrity.sha256
  check  -> porovna aktualne hashe s manifestom, exit 0 OK / exit 1 MISMATCH
Chranene: SKILL.md (Hermes skill), pubkey, fingerprint. Private kluc sa NEhashuje
do manifestu (meni sa chmod/pristupy netreba), ale kontroluje sa jeho existencia.
"""
import os
import sys
import hashlib

HOME = os.path.expanduser("~")
FILES = {
    "skill": os.path.join(HOME, ".hermes/skills/note-taking/zolander/SKILL.md"),
    "pub": os.path.join(HOME, "zolander/identity/zolander_ed25519.pub"),
    "fingerprint": os.path.join(HOME, "zolander/identity/fingerprint.txt"),
}
MANIFEST = os.path.join(HOME, "zolander/identity/integrity.sha256")
PRIV = os.path.join(HOME, "zolander/identity/zolander_ed25519.key")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def do_write():
    lines = []
    for name, path in FILES.items():
        lines.append(f"{sha(path)}  {name}  {path}")
    with open(MANIFEST, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("MANIFEST zapisany:", MANIFEST)
    for l in lines:
        print(" ", l)


def do_check():
    if not os.path.exists(PRIV):
        print("CHYBA: chyba privatny kluc", PRIV)
        return 1
    if not os.path.exists(MANIFEST):
        print("CHYBA: chyba manifest", MANIFEST)
        return 1
    ok = True
    saved = {}
    for line in open(MANIFEST):
        parts = line.split()
        if len(parts) >= 2:
            saved[parts[1]] = parts[0]
    for name, path in FILES.items():
        cur = sha(path)
        exp = saved.get(name)
        if exp != cur:
            print(f"MISMATCH {name}: cakane {exp} != {cur}  ({path})")
            ok = False
        else:
            print(f"OK {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "write":
        do_write()
    else:
        sys.exit(do_check())
