#!/usr/bin/env python3
"""
hook_env_guard.py — pre_tool_call HARD LOCK proti destruktivnemu zapisu do .env suborov.

PRECO: 2026-09-01 asistent prepisal cely ~/.hermes/.env cez `printf > .env` (truncating
redirect) a zmazal Matrix blok (token, recovery key, whitelist). Tento hook robi taku chybu
MECHANICKY nemoznou — bez ohladu na model/naladu/slepy predpoklad.

Blokuje DVA vektory:
  1) terminal:   truncating redirect `>` (nie `>>`) do cielu obsahujuceho `.env`
                 (`> .env`, `printf ... > ~/.hermes/.env`, `echo x >.env`, `tee .env` bez -a,
                  `dd of=....env`, `truncate ... .env`)
  2) write_file: akykolvek path obsahujuci `.env` (write_file VZDY prepise cely subor)

NEBLOKUJE (legitimne): `>>` append, citanie (grep/wc/cat), `cp X .env` (target nie cez `>`),
volanie env_guard.py (bezpecna cesta), patch (targetovany edit).

Kontrakt: cita JSON event zo stdin, na blok vrati {"action":"block","message":...} na stdout.
FAIL-OPEN: akakolvek chyba -> exit 0 prazdny stdout (nikdy nezhodi agenta).
"""
import json
import os
import re
import sys


def _looks_like_env_path(token: str) -> bool:
    t = token.strip().strip("'\"")
    # .env, .env.local, .env.production, foo/.env, ~/.hermes/.env
    base = t.rsplit("/", 1)[-1]
    return base == ".env" or base.startswith(".env.") or base.endswith(".env")


def _terminal_is_destructive(cmd: str):
    if not cmd:
        return None
    # bezpecna cesta: nas vlastny guard nikdy neblokuj
    if "env_guard.py" in cmd:
        return None

    # 1) truncating redirect `>` (nie `>>`) do cielu s .env
    #    najdi kazde jednoduche `>` (nie >> a nie 2>&1 apod.) a pozri nasledujuci token
    for m in re.finditer(r"(?<![>0-9])>(?!>)\s*([^\s;|&]+)", cmd):
        target = m.group(1)
        if _looks_like_env_path(target):
            return (f"truncating redirect `> {target}` prepise CELY .env subor a zmaze vsetky "
                    f"kluce. TOTO je presne chyba z 2026-09-01.")

    # 2) tee do .env bez append
    if re.search(r"\btee\b", cmd) and ".env" in cmd and not re.search(r"\btee\b[^|;&]*\s-(-append|a)\b", cmd):
        for tok in re.findall(r"\S+", cmd):
            if _looks_like_env_path(tok):
                return "`tee` bez -a prepise .env subor."

    # 3) dd of=... .env  /  truncate ... .env
    m = re.search(r"\bof=(\S+)", cmd)
    if m and _looks_like_env_path(m.group(1)):
        return "`dd of=` na .env prepise subor."
    if re.search(r"\btruncate\b", cmd):
        for tok in re.findall(r"\S+", cmd):
            if _looks_like_env_path(tok):
                return "`truncate` na .env zmaze obsah."

    return None


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        event = json.loads(raw)
    except Exception:
        return  # fail-open

    try:
        tool = event.get("tool_name", "")
        ti = event.get("tool_input", {}) or {}

        reason = None
        if tool == "terminal":
            reason = _terminal_is_destructive(ti.get("command", "") or "")
        elif tool == "write_file":
            path = (ti.get("path", "") or "")
            if _looks_like_env_path(path):
                reason = (f"write_file na `{path}` PREPISE cely .env (write_file vzdy truncatuje). "
                          f"TOTO je presne chyba z 2026-09-01.")

        if reason:
            guard = os.path.expanduser("~/.hermes/state/env-guard/env_guard.py")
            msg = (
                f"⛔ ZABLOKOVANE (env-guard hook): {reason}\n\n"
                f"Pouzi BEZPECNU cestu — nikdy neprepisuj .env cely:\n"
                f"  • pridat/zmenit JEDEN kluc:  /usr/bin/python3 {guard} set KEY --value-file /tmp/val\n"
                f"  • append do .env:             printf 'KEY=val\\n' >> <cesta>/.env   (>> nie >)\n"
                f"  • obnovit zo snapshotu:       /usr/bin/python3 {guard} restore <snapshot>\n"
                f"  • pred zmenou vzdy:           /usr/bin/python3 {guard} snapshot\n\n"
                f"Ak naozaj MUSIS prepisat cely subor, najprv sprav snapshot a pouzi `>>` alebo env_guard."
            )
            print(json.dumps({"action": "block", "message": msg}))
    except Exception:
        return  # fail-open


if __name__ == "__main__":
    main()
