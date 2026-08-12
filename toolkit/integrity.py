#!/usr/bin/env python3
"""Zolander F1 — integrity manifest identity suborov.
Rezimy:
  write  -> spocita SHA-256 chranenych suborov, zapise identity/integrity.sha256
  check  -> porovna aktualne hashe s manifestom, exit 0 OK / exit 1 MISMATCH
Chranene: LEN kryptograficka identita — pubkey + fingerprint. SKILL.md sa UZ
NEchranI: vlastni ho Hermes a sam si ho prepisuje (normalizacia frontmatteru,
curator, `hermes update`), takze hash chranI subor ktory legitimne meni niekto
iny -> vecne false-faily bez realnej ochrany (utocnik co prepise skill prepise aj
manifest). Identitu drzi Ed25519 kluc, nie hash markdownu. Private kluc sa
NEhashuje (meni sa chmod/pristupy), ale kontroluje sa jeho existencia.
"""
import os
import sys
import hashlib

HOME = os.path.expanduser("~")
FILES = {
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


def _load_manifest():
    if not os.path.exists(PRIV):
        print("CHYBA: chyba privatny kluc", PRIV)
        return None
    if not os.path.exists(MANIFEST):
        print("CHYBA: chyba manifest", MANIFEST)
        return None
    saved = {}
    for line in open(MANIFEST):
        parts = line.split()
        if len(parts) >= 2:
            saved[parts[1]] = parts[0]
    return saved


def do_check(only=None):
    """Porovna hashe. `only` = mnozina nazvov na kontrolu (None = vsetky).
    Vrati 0 ak vsetky kontrolovane sedia, inak 1."""
    saved = _load_manifest()
    if saved is None:
        return 1
    ok = True
    for name, path in FILES.items():
        if only is not None and name not in only:
            continue
        cur = sha(path)
        exp = saved.get(name)
        if exp != cur:
            print(f"MISMATCH {name}: cakane {exp} != {cur}  ({path})")
            ok = False
        else:
            print(f"OK {name}")
    return 0 if ok else 1


# nazvy suborov ktore predstavuju SKUTOCNU kryptograficku identitu (nie skill).
# mismatch na tychto = realny utok -> fail-closed. Skill vlastni Hermes a moze
# ho sam prepisat (normalizacia frontmatteru, curator, `hermes update`).
KEY_FILES = {"pub", "fingerprint"}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "write":
        do_write()
    elif mode == "check-keys":
        # kontroluje LEN kryptograficku identitu (pub + fingerprint)
        sys.exit(do_check(only=KEY_FILES))
    else:
        sys.exit(do_check())
