#!/usr/bin/env python3
"""zolander_notify.py — jednotna oznamovacia vrstva Zolandera -> __USER__.

Pouzitie:
    zolander_notify.py "text spravy"
    echo "text" | zolander_notify.py
    zolander_notify.py --subject "hotovo" "kapitola D_L4 dokoncena"

Logika (fail-open, nikdy nezhodi volajuci daemon):
  1. VZDY zapise spravu do state/inbox.md (append, timestamp) — trvaly zaznam
     ktory privitaci hook precita pri starte Hermesu (funguje aj bez WhatsAppu).
  2. Ak je nakonfigurovana messaging platforma (WhatsApp/Signal/Telegram...),
     skusi `hermes send` — realny push na mobil. Kanal sa detekuje dynamicky:
     ak `hermes send --list` nic nevrati, push sa TICHO preskoci (len inbox).
  3. Vysledok (sent/inbox-only) zaloguje do logs/notify.log.

Bezi pod /usr/bin/python3 (stdlib only). `hermes` sa hlada v PATH aj na
zvycajnych miestach (launchd ma orezany PATH -> preto explicitne cesty).
"""
import os
import sys
import json
import shutil
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
INBOX = os.path.join(STATE, "inbox.md")
NOTIFYLOG = os.path.join(LOGS, "notify.log")

# platforma pre push (prepisatelne cez env ZOL_NOTIFY_TARGET). Prazdne = auto:
# vezmi prvu dostupnu z `hermes send --list`.
TARGET = os.environ.get("ZOL_NOTIFY_TARGET", "").strip()

# launchd ma orezany PATH -> hladaj hermes explicitne
HERMES_CANDIDATES = [
    shutil.which("hermes"),
    os.path.join(HOME, ".local", "bin", "hermes"),
    "/usr/local/bin/hermes",
    "/opt/homebrew/bin/hermes",
]
SEND_TIMEOUT = 60  # s


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(NOTIFYLOG, "a", encoding="utf-8") as f:
            f.write(f"{now()} | {msg}\n")
    except Exception:
        pass


def find_hermes():
    for c in HERMES_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def write_inbox(subject, body):
    """VZDY — trvaly zaznam na disk, aj ked push zlyha/chyba kanal."""
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(INBOX, "a", encoding="utf-8") as f:
            f.write(f"\n## {now()}")
            if subject:
                f.write(f" — {subject}")
            f.write(f"\n{body}\n")
        return True
    except Exception as exc:
        log(f"INBOX ZAPIS ZLYHAL: {exc!r}")
        return False


def detect_target(hermes):
    """Ak TARGET nie je zadany, vezmi prvu platformu z `hermes send --list`.
    Vrati string targetu alebo None ak ziadna platforma."""
    if TARGET:
        return TARGET
    try:
        p = subprocess.run([hermes, "send", "--list", "--json"],
                           capture_output=True, text=True, timeout=20)
        data = json.loads(p.stdout or "{}")
        # tolerancia roznych tvarov: hladaj zoznam platform/targets
        cands = []
        if isinstance(data, dict):
            for key in ("targets", "platforms", "channels"):
                v = data.get(key)
                if isinstance(v, list):
                    cands = v
                    break
        elif isinstance(data, list):
            cands = data
        for c in cands:
            if isinstance(c, str) and c.strip():
                return c.strip()
            if isinstance(c, dict):
                t = c.get("target") or c.get("platform") or c.get("name")
                if t:
                    return str(t).strip()
    except Exception as exc:
        log(f"detect_target zlyhal (ziadny push kanal): {exc!r}")
    return None


def try_push(hermes, target, subject, body):
    cmd = [hermes, "send", "--to", target, "--quiet"]
    if subject:
        cmd += ["--subject", subject]
    cmd += [body]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=SEND_TIMEOUT)
        if p.returncode == 0:
            log(f"PUSH ok -> {target}")
            return True
        log(f"PUSH zlyhal rc={p.returncode} -> {target}: {(p.stderr or '').strip()[:200]}")
    except Exception as exc:
        log(f"PUSH exception -> {target}: {exc!r}")
    return False


def main():
    args = sys.argv[1:]
    subject = ""
    if "--subject" in args:
        i = args.index("--subject")
        try:
            subject = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            pass
    body = " ".join(args).strip()
    if not body:
        body = sys.stdin.read().strip()
    if not body:
        log("prazdna sprava — preskocene")
        return 0

    # 1) VZDY inbox
    write_inbox(subject, body)

    # 2) skus push (best-effort)
    hermes = find_hermes()
    if not hermes:
        log("hermes CLI nenajdene -> len inbox")
        return 0
    target = detect_target(hermes)
    if not target:
        # Fallback: channel discovery (`hermes send --list`) bezi len cez gateway,
        # ktory na tomto DLP Macu nechceme 24/7. Ale `hermes send --to whatsapp`
        # funguje priamo cez home channel v config.yaml (WHATSAPP_HOME_CHANNEL).
        # Preto skus fixny default kanal ZOL_NOTIFY_FALLBACK (default 'whatsapp').
        target = os.environ.get("ZOL_NOTIFY_FALLBACK", "whatsapp").strip()
        if not target:
            log("ziadny push kanal a prazdny fallback -> len inbox")
            return 0
        log(f"detect_target prazdny -> skusam fixny fallback '{target}'")
    try_push(hermes, target, subject, body)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"NOTIFY EXCEPTION: {exc!r}")
        sys.exit(0)  # nikdy nezhod volajuci daemon
