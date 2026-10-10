#!/usr/bin/env python3
"""zol_matrix_timeline.py — dešifrovaný chvost miestnosti pre Zolander kontext.

PROBLÉM: Hermes gateway spúšťa na KAŽDÚ prichádzajúcu Matrix správu session,
ktorá vidí len telo tej jednej správy (source.body). Nevidí:
  (a) históriu konverzácie s kontaktom,
  (b) správy, ktoré napísal veducko SÁM z Beeper appky (tie idú z @zoloziak =
      účet bota, gateway ich považuje za vlastné odchádzajúce a do session ich
      nedá).
Jediné miesto, kde existujú VŠETKY správy (kontakt + bot + veducko) je timeline
miestnosti — šifrovaný megolm. Tento modul ho dešifruje a vráti posledných N
správ ako čitateľný prepis, aby ho pre_llm_call hook injektol do kontextu.

Beží pod ~/.hermes/hermes-agent/venv (má python-olm + mautrix). Read-only:
crypto.db otvára v RO móde (WAL => súbežné s bežiacim gatewayom, žiadny zámok).

Použitie:
    python zol_matrix_timeline.py <room_id> [limit]
Vypíše na stdout čitateľný prepis (alebo prázdno pri chybe/žiadnych správach).
"""
import os
import sys
import json
import sqlite3
import urllib.parse
import urllib.request
import ssl

HOME = os.path.expanduser("~/.hermes")
ENV_PATH = os.path.join(HOME, ".env")
CRYPTO_DB = os.path.join(HOME, "platforms", "matrix", "store", "crypto.db")

# custom CA cert — bez toho HTTPS na beeper padne
if os.path.exists(CA):


def _load_env():
    """Vytiahne MATRIX_* z ~/.hermes/.env (KEY=VALUE riadky)."""
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    for ln in open(ENV_PATH, encoding="utf-8", errors="replace"):
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _ssl_ctx():
    ctx = ssl.create_default_context()
    if os.path.exists(CA):
        try:
            ctx.load_verify_locations(CA)
        except Exception:
            pass
    return ctx


def _http_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx()) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_messages(homeserver, token, room_id, limit):
    """Posledných `limit` timeline eventov (newest-first dir=b)."""
    rid = urllib.parse.quote(room_id, safe="")
    url = (f"{homeserver}/_matrix/client/v3/rooms/{rid}/messages"
           f"?dir=b&limit={limit}")
    data = _http_get(url, token)
    return data.get("chunk", []) or []


def _load_crypto(account_id):
    """RO pripojenie na crypto.db + device_id (na pickle_key)."""
    uri = f"file:{CRYPTO_DB}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT device_id FROM crypto_account WHERE account_id=?",
        (account_id,)).fetchone()
    device_id = row["device_id"] if row else None
    return con, device_id


def _get_session(con, account_id, pickle_key, session_id):
    """Nájdi + odpickluj megolm inbound session podľa session_id."""
    from olm import InboundGroupSession
    row = con.execute(
        "SELECT session FROM crypto_megolm_inbound_session "
        "WHERE account_id=? AND session_id=?",
        (account_id, session_id)).fetchone()
    if not row or row["session"] is None:
        return None
    blob = row["session"]
    if isinstance(blob, str):
        blob = blob.encode("utf-8")
    try:
        return InboundGroupSession.from_pickle(blob, pickle_key)
    except Exception:
        return None


def _decrypt_event(con, account_id, pickle_key, ev, cache):
    """Dešifruj jeden m.room.encrypted event -> (body, msgtype) alebo None."""
    content = ev.get("content") or {}
    if content.get("algorithm") != "m.megolm.v1.aes-sha2":
        return None
    sid = content.get("session_id")
    ciphertext = content.get("ciphertext")
    if not sid or not ciphertext:
        return None
    sess = cache.get(sid, "MISS")
    if sess == "MISS":
        sess = _get_session(con, account_id, pickle_key, sid)
        cache[sid] = sess
    if sess is None:
        return None
    try:
        plaintext, _idx = sess.decrypt(ciphertext)
    except Exception:
        return None
    try:
        payload = json.loads(plaintext)
    except Exception:
        return None
    inner = payload.get("content") or {}
    body = inner.get("body")
    msgtype = inner.get("msgtype") or payload.get("type")
    if not body:
        # nie textová správa (reakcia, receipt, media bez body...)
        return None
    return body, msgtype


def build_transcript(room_id, limit=12):
    env = _load_env()
    homeserver = env.get("MATRIX_HOMESERVER")
    token = env.get("MATRIX_ACCESS_TOKEN")
    account_id = env.get("MATRIX_USER_ID")
    if not (homeserver and token and account_id):
        return ""

    events = _fetch_messages(homeserver, token, room_id, limit * 3)  # rezerva na nedešifrovateľné
    if not events:
        return ""

    con, device_id = _load_crypto(account_id)
    if not device_id:
        con.close()
        return ""
    pickle_key = f"{account_id}:{device_id}"

    cache = {}
    lines = []
    # events sú newest-first (dir=b) -> obrátime na chronologické
    for ev in reversed(events):
        etype = ev.get("type")
        sender = ev.get("sender", "")
        body = None
        if etype == "m.room.encrypted":
            dec = _decrypt_event(con, account_id, pickle_key, ev, cache)
            if dec:
                body = dec[0]
        elif etype == "m.room.message":
            body = (ev.get("content") or {}).get("body")
        if not body:
            continue
        who = "VEDUCKO/BOT (ja @zoloziak)" if sender == account_id else "KONTAKT"
        # jednoriadkovo, orež extrémne dlhé
        b = " ".join(str(body).split())
        if len(b) > 400:
            b = b[:400] + "…"
        lines.append(f"{who}: {b}")
    con.close()

    if not lines:
        return ""
    # posledných `limit` reálne dešifrovaných
    lines = lines[-limit:]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: zol_matrix_timeline.py <room_id> [limit]", file=sys.stderr)
        sys.exit(2)
    room = sys.argv[1]
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    try:
        print(build_transcript(room, lim))
    except Exception as exc:
        print(f"[timeline error: {exc}]", file=sys.stderr)
        sys.exit(1)
