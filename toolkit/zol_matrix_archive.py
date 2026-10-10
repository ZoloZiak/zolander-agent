#!/usr/bin/env python3
"""zol_matrix_archive.py — lokálny inkrementálny archív dešifrovaných správ miestnosti.

Matrix server JE archív, ale ťahať 900+ šifrovaných eventov každý beh je zbytočné.
Tento modul stiahne timeline RAZ, dešifruje megolm, uloží do JSONL a pri ďalšom
behu dofetchne LEN nové správy (od poslednej uloženej ts). Z tohto archívu potom
stavia digest (rolling súhrny) aj hook (živý doslovný tail).

Beží pod ~/.hermes/hermes-agent/venv (olm). crypto.db read-only (WAL => súbežné).

CLI:  python zol_matrix_archive.py sync <room_id>
Modul: from zol_matrix_archive import sync_room, load_archive, room_hash
"""
import os
import sys
import json
import sqlite3
import hashlib
import urllib.parse
import urllib.request
import ssl

HOME = os.path.expanduser("~/.hermes")
ENV_PATH = os.path.join(HOME, ".env")
CRYPTO_DB = os.path.join(HOME, "platforms", "matrix", "store", "crypto.db")
ARCHIVE_DIR = os.path.expanduser("~/projects/zolander/state/matrix_archive")

if os.path.exists(CA):

MAX_PAGES = 80  # strop pri prvotnom stiahnutí (80*200 = 16k eventov)


def room_hash(room_id: str) -> str:
    return hashlib.sha1(room_id.encode("utf-8")).hexdigest()[:16]


def _archive_path(room_id: str) -> str:
    return os.path.join(ARCHIVE_DIR, room_hash(room_id) + ".jsonl")


def _meta_path(room_id: str) -> str:
    return os.path.join(ARCHIVE_DIR, room_hash(room_id) + ".meta.json")


def _load_env():
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    for ln in open(ENV_PATH, encoding="utf-8", errors="replace"):
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
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


class _Decryptor:
    def __init__(self, account_id):
        self.account_id = account_id
        uri = f"file:{CRYPTO_DB}?mode=ro"
        self.con = sqlite3.connect(uri, uri=True, timeout=5)
        row = self.con.execute(
            "SELECT device_id FROM crypto_account WHERE account_id=?",
            (account_id,)).fetchone()
        self.device_id = row[0] if row else None
        self.pickle_key = f"{account_id}:{self.device_id}" if self.device_id else None
        self.cache = {}

    def _session(self, sid):
        if sid in self.cache:
            return self.cache[sid]
        from olm import InboundGroupSession
        row = self.con.execute(
            "SELECT session FROM crypto_megolm_inbound_session "
            "WHERE account_id=? AND session_id=?",
            (self.account_id, sid)).fetchone()
        s = None
        if row and row[0] is not None:
            blob = row[0].encode("utf-8") if isinstance(row[0], str) else row[0]
            try:
                s = InboundGroupSession.from_pickle(blob, self.pickle_key)
            except Exception:
                s = None
        self.cache[sid] = s
        return s

    def body_of(self, ev):
        t = ev.get("type")
        if t == "m.room.message":
            return (ev.get("content") or {}).get("body")
        if t == "m.room.encrypted":
            c = ev.get("content") or {}
            sid = c.get("session_id")
            ct = c.get("ciphertext")
            if not (sid and ct):
                return None
            s = self._session(sid)
            if s is None:
                return None
            try:
                pt, _ = s.decrypt(ct)
                return (json.loads(pt).get("content") or {}).get("body")
            except Exception:
                return None
        return None

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass


def load_archive(room_id: str):
    """Vráti list {ts, sender, who, body} chronologicky (najstaršie prvé)."""
    p = _archive_path(room_id)
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    out.sort(key=lambda r: r.get("ts", 0))
    return out


def sync_room(room_id: str) -> int:
    """Dofetchne nové správy do archívu. Vráti počet PRIDANÝCH."""
    env = _load_env()
    hs = env.get("MATRIX_HOMESERVER")
    tok = env.get("MATRIX_ACCESS_TOKEN")
    acct = env.get("MATRIX_USER_ID")
    if not (hs and tok and acct):
        return 0

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    existing = load_archive(room_id)
    known_ts = existing[-1]["ts"] if existing else 0
    seen_ids = {r.get("eid") for r in existing if r.get("eid")}

    dec = _Decryptor(acct)
    if not dec.device_id:
        dec.close()
        return 0

    rid = urllib.parse.quote(room_id, safe="")
    from_tok = None
    new_rows = []
    pages = 0
    stop = False
    while pages < MAX_PAGES and not stop:
        url = f"{hs}/_matrix/client/v3/rooms/{rid}/messages?dir=b&limit=200"
        if from_tok:
            url += f"&from={urllib.parse.quote(from_tok)}"
        data = _http_get(url, tok)
        chunk = data.get("chunk", [])
        if not chunk:
            break
        for ev in chunk:
            ts = ev.get("origin_server_ts") or 0
            eid = ev.get("event_id")
            # inkrementálny stop: dorazili sme k už známym správam
            if known_ts and ts <= known_ts and eid in seen_ids:
                stop = True
                break
            if eid in seen_ids:
                continue
            body = dec.body_of(ev)
            if not body:
                continue
            sender = ev.get("sender", "")
            new_rows.append({
                "ts": ts,
                "eid": eid,
                "sender": sender,
                "who": "self" if sender == acct else "contact",
                "body": " ".join(str(body).split()),
            })
        pages += 1
        from_tok = data.get("end")
        if not from_tok:
            break
    dec.close()

    if not new_rows:
        return 0

    # zluč, dedupe podľa eid, zapíš celý archív (chronologicky)
    all_rows = existing + new_rows
    dedup = {}
    for r in all_rows:
        dedup[r.get("eid") or f"{r['ts']}:{r['body'][:20]}"] = r
    merged = sorted(dedup.values(), key=lambda r: r.get("ts", 0))

    p = _archive_path(room_id)
    with open(p, "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {"room_id": room_id, "count": len(merged),
            "last_ts": merged[-1]["ts"] if merged else 0}
    with open(_meta_path(room_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    return len(new_rows)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "sync":
        print("usage: zol_matrix_archive.py sync <room_id>", file=sys.stderr)
        sys.exit(2)
    n = sync_room(sys.argv[2])
    total = len(load_archive(sys.argv[2]))
    print(f"synced +{n} new, total={total}")
