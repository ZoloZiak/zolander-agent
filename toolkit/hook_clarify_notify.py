#!/usr/bin/env python3
"""hook_clarify_notify.py — pre_tool_call hook: keď Zolander v CLI zavolá
nástroj `clarify` (pýta sa vedúcka / čaká na odpoveď), vystrelí natívny macOS
banner, aby vedúcko vedel aj keď nesedí pri termináli.

NEBLOKUJE nástroj — vždy vráti prázdny stdout (= proceed). Je to observer +
side-effect (banner), nie guard.

Registrácia (config.yaml, pre_tool_call, matcher: clarify) je zámerne NEAKTÍVNA
kým ju vedúcko nezapne — viď koniec súboru / skill. Fail-open, stdlib.
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
    if payload.get("tool_name") != "clarify":
        return 0

    # vytiahni otazku z tool_input (best-effort, roznymi tvarmi)
    ti = payload.get("tool_input") or {}
    question = ""
    if isinstance(ti, dict):
        question = str(ti.get("question", "")).strip()
    msg = question[:180] if question else "Zolander sa ta na nieco pyta v CLI"

    if not os.path.exists(DESKTOP):
        return 0
    try:
        subprocess.run(
            [PYBIN, DESKTOP, "--title", "Zolander",
             "--subtitle", "caka na tvoju odpoved", "--message", msg,
             "--sound", "Ping"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass
    return 0  # prazdny stdout = tool prejde


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
