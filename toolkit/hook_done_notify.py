#!/usr/bin/env python3
"""hook_done_notify.py — pre_verify hook: keď Zolander v CLI DOKONČÍ editačný ťah
(menil súbory a chystá sa skončiť = čaká na vedúcka), vystrelí natívny macOS
banner. Observer + side-effect (banner), NEzasahuje do flow: vždy vráti prázdny
stdout = turn sa dokončí normálne.

Fire len pri prvom pokuse o dokončenie (extra.attempt == 0) a len keď šlo o
editačný ťah (extra.coding) — aby buchol RAZ za ťah, nie pri každom verify-nudgi.
Fail-open, stdlib.
"""
import os
import sys
import json
import subprocess

HOME = os.path.expanduser("~")
DESKTOP = os.path.join(HOME, "zolander", "toolkit", "zol_desktop_notify.py")
PYBIN = "/usr/bin/python3"


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    extra = payload.get("extra") or {}
    if not extra.get("coding"):
        return 0
    # fire len pri prvom pokuse o dokoncenie tahu (nie pri opakovanom verify nudgi)
    try:
        if int(extra.get("attempt", 0)) != 0:
            return 0
    except Exception:
        pass

    changed = extra.get("changed_paths") or []
    n = len(changed) if isinstance(changed, list) else 0
    if n == 1:
        msg = f"Hotovo, upravil som 1 subor. Cakam na dalsie zadanie."
    elif n > 1:
        msg = f"Hotovo, upravil som {n} suborov. Cakam na dalsie zadanie."
    else:
        msg = "Hotovo, skoncil som robotu. Cakam na dalsie zadanie."

    if os.path.exists(DESKTOP):
        try:
            subprocess.run(
                [PYBIN, DESKTOP, "--title", "Zolander",
                 "--subtitle", "robota hotova", "--message", msg,
                 "--sound", "Glass"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

    # prazdny stdout = ziadny zasah do verify flow (turn sa dokonci)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
