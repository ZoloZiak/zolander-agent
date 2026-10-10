#!/usr/bin/env python3
"""hook_matrix_timeline.py — per-turn injekcia VRSTVENEJ pamäte konverzácie.

Zapája sa na Hermes `pre_llm_call`. Pre KAŽDÝ turn v Matrix session vloží do
USER message časovo odstupňovanú pamäť konverzácie:
    ZA ROKY / MESIACE / TÝŽDNE / DNI   (predpočítaný digest z cache — LLM-free tu)
    + POSLEDNÉ SPRÁVY doslovne          (živý tail z archívu)
Tým Zolander vidí celú históriu vzťahu s kontaktom (vrátane toho, čo veducko
napísal SÁM z appky — tie sú v archíve, do gateway session sa nedostanú) a
zároveň presné posledné repliky.

Výkon: hook pri turne NEVOLÁ LLM. Digest je predpočítaný (zol_matrix_digest
build, cron/manuál). Hook len (1) inkrementálne dosyncuje archív (rýchle, HTTP),
(2) prečíta digest cache, (3) dolepí doslovný tail. Digest sa reálne prepočíta
len keď pribudli nové správy — to rob mimo hot-path (cron), nie v hooku.

Fail-safe: hook NIKDY nezhodí agenta ani nepredstiera kontext — pri chybe tichý
no-op alebo úprimná hláška.

Beží pod /usr/bin/python3 (stdlib). Ťažkú prácu (olm/LLM) deleguje na venv worker.
"""
import sys
import os
import json
import subprocess
import datetime

STATE_DB = os.path.expanduser("~/.hermes/state.db")
VENV_PY = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python")
TOOLKIT = os.path.expanduser("~/projects/zolander/toolkit")
ARCHIVE_DIR = os.path.expanduser("~/projects/zolander/state/matrix_archive")

TAIL_N = 15               # posledných správ doslovne
SYNC_TIMEOUT = 20         # inkrementálny fetch archívu
import hashlib


def _is_matrix(payload) -> bool:
    if str(payload.get("platform") or "").lower() == "matrix":
        return True
    return ":matrix:" in str(payload.get("session_id") or "")


def _room_id_for_session(session_id: str):
    if not session_id or not os.path.exists(STATE_DB):
        return None
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)
        rows = con.execute(
            "SELECT entry_json FROM gateway_routing "
            "WHERE session_key LIKE '%matrix%'").fetchall()
        con.close()
    except Exception:
        return None
    for (ej,) in rows:
        try:
            entry = json.loads(ej)
        except Exception:
            continue
        if entry.get("session_id") == session_id:
            cid = (entry.get("origin") or {}).get("chat_id")
            if cid:
                return cid
    return None


def _room_hash(room_id):
    return hashlib.sha1(room_id.encode("utf-8")).hexdigest()[:16]


def _sync_archive(room_id):
    """Inkrementálne dosyncuje archív (venv worker). Bez pádu."""
    worker = os.path.join(TOOLKIT, "zol_matrix_archive.py")
    if not (os.path.exists(VENV_PY) and os.path.exists(worker)):
        return
    try:
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("PYTHONPATH", "PYTHONHOME")}
        subprocess.run([VENV_PY, worker, "sync", room_id],
                       capture_output=True, text=True,
                       timeout=SYNC_TIMEOUT, env=clean)
    except Exception:
        pass  # sync zlyhal -> použijeme čo máme v archíve/cache


def _read_digest(room_id):
    """Predpočítaný vrstvený súhrn (roky/mesiace/týždne/dni) z cache."""
    path = os.path.join(ARCHIVE_DIR, _room_hash(room_id) + ".digest.json")
    if not os.path.exists(path):
        return ""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return ""
    layers = d.get("layers", {})
    parts = []
    for name, label in [("years", "ZA ROKY"), ("months", "ZA MESIACE"),
                        ("weeks", "ZA TÝŽDNE"), ("days", "ZA DNI")]:
        block = layers.get(name, {})
        lines = []
        for key in sorted(block):
            s = (block[key].get("summary") or "").strip()
            if s and not s.startswith("[digest:"):
                lines.append(f"  • {key}: {s}")
        if lines:
            parts.append(label + ":\n" + "\n".join(lines))
    return "\n".join(parts)


def _read_tail(room_id, n):
    """Posledných n správ doslovne priamo z archívu JSONL (stdlib)."""
    path = os.path.join(ARCHIVE_DIR, _room_hash(room_id) + ".jsonl")
    if not os.path.exists(path):
        return ""
    rows = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    rows.sort(key=lambda r: r.get("ts", 0))
    rows = rows[-n:]
    out = []
    for r in rows:
        who = "VEDUCKO/BOT (ja @zoloziak)" if r.get("who") == "self" else "KONTAKT"
        b = r.get("body", "")
        if len(b) > 400:
            b = b[:400] + "…"
        out.append(f"{who}: {b}")
    return "\n".join(out)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return

    if not _is_matrix(payload):
        return

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return
    room_id = _room_id_for_session(session_id)
    if not room_id:
        return

    _sync_archive(room_id)               # čerstvé nové správy do archívu
    digest = _read_digest(room_id)       # dlhá pamäť (predpočítaná)
    tail = _read_tail(room_id, TAIL_N)   # posledné doslovne

    if not (digest or tail):
        return

    blocks = ["[Zolander — PAMÄŤ tejto konverzácie (dešifrovaná z miestnosti). "
              "TOTO JE KONTEXT na ktorý nadväzuj, NIE nová úloha. Riadky "
              "'VEDUCKO/BOT (ja @zoloziak)' sú z tvojho účtu: časť napísal "
              "Zolander (ty), časť sám veducko z appky — ber to ako povedané, "
              "NEopakuj a neprotireč. 'KONTAKT' je druhá strana. Aktuálna správa "
              "nižšie je POKRAČOVANIE tejto nite.]"]
    if digest:
        blocks.append("═══ SÚHRN HISTÓRIE (staršie → novšie) ═══\n" + digest)
    if tail:
        blocks.append(f"═══ POSLEDNÝCH {TAIL_N} SPRÁV (doslovne) ═══\n" + tail)

    print(json.dumps({"context": "\n\n".join(blocks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
