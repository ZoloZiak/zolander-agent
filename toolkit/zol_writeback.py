#!/usr/bin/env python3
"""zol_writeback.py — P1 auto-zapis Zolanderovej pamate (SOTA WRITE pipeline).

PROBLEM (diagnoza 2026-08-08): pamat ma ~18 zaznamov, zapis sa NEDEJE. Hermes NEMA
session-end hook. Riesenie (nezavisle od Hermes): samostatny launchd tick cita
~/.hermes/state.db, najde USADENE este NESPRACOVANE (alebo prirastkovo dopisane)
session, LLM z nich extrahuje salientne fakty/rozhodnutia (nie raw dump — SOTA
Mem0/A-MEM), a zapise ich do pamate cez zol_mem.py remember (episodic L0).

REFAKTOR 2026-09-02 (idle-flush + per-session watermark):
  DIAGNOZA: povodny trigger bral LEN ended_at IS NOT NULL. Desktop session skoro
  nikdy nedostanu ended_at -> 11 zivych sedeni (372/234/152... sprav) VISELO
  nezapisanych. To bol pocit "minimalne zapisuje do hyperspace" — nie rychlost
  extrakcie, ale TRIGGER co ich nevidel.
  FIX 1 (idle-flush): session je USADENA a hodna spracovania ak ma ended_at ALEBO
    posledna sprava je starsia nez IDLE_MINUTES (default 20). Aktivna session
    (idle < prah) sa NEDOTKNE — ziadne polovicne fakty z prebiehajuceho dialogu.
  FIX 2 (watermark): namiesto celo-session done-flagu drzime per-session watermark
    (max spracovane message.id) v state/writeback_watermark.json. Re-flush spracuje
    LEN spravy s id > watermark -> rastuca session tecie priebezne po kuskoch bez
    duplikatov. Legacy writeback_done.txt sa stale ctí (tie session su plne hotove,
    preskakuju sa) — ziadny reprocess starej roboty.
  NEROBI sa distance/embedding novelty-gate: EMPIRICKY ZAMIETNUTY (2026-09-02).
    Gemma cosine: parafraza toho isteho faktu 0.30-0.49 sa PREKRYVA s inymi faktami
    (0.38-0.52), a NEGACIA ("nebyva na X") je BLIZSIE (0.03-0.07) nez parafraza.
    similarity meria TEMU, dedup potrebuje ENTAILMENT — su to rozne ulohy, ziadny
    prah ich nerozlisi (spike005: "Z1 ako cosine filter SKODI"). Parafrazovy dedup
    ostava na nocnom Opus dream, nie na lacnom prahu na write-path.

SOTA principy (arxiv 2504.19413 Mem0, 2502.12110 A-MEM, survey 2505.00675):
  WRITE != raw turn. LLM extrahuje 3-8 salientnych faktov s typom+salience.
  Fail-open: chyba pri jednej session NEzhodi cely tick (log + pokracuj).

Beh: cez launchd tick alebo rucne. Interpret /usr/bin/python3 (palantir_client +
sqlite3 = stdlib+urllib; zol_mem.py remember si sam riesi venv-yar embedding cez
subprocess vo vnutri). NEbezi embedder priamo tu.

Pouzitie:
  /usr/bin/python3 zol_writeback.py            # spracuj vsetky usadene nove/dopisane session
  /usr/bin/python3 zol_writeback.py --dry-run  # len ukaz co by spravil, nezapis (watermark netknuty)
  /usr/bin/python3 zol_writeback.py --session <id>  # konkretna session (obchadza source+settle filter)
"""
import os
import sys
import json
import time
import sqlite3
import subprocess
import datetime

HOME = os.path.expanduser("~")
STATE_DB = os.path.join(HOME, ".hermes/state.db")
ZOL_ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ZOL_ROOT, "state")
DONE_FILE = os.path.join(STATE, "writeback_done.txt")          # legacy: plne hotove session
WATERMARK_FILE = os.path.join(STATE, "writeback_watermark.json")  # {session_id: max spracovane message.id}
LOCK_FILE = os.path.join(STATE, "writeback.lock")              # PID-lock: dva behy sa NESMU prekryt (race na watermark)
LOG = os.path.join(ZOL_ROOT, "logs", "writeback.log")
SYS_PY = "/usr/bin/python3"
# zol_mem.py remember importuje embed_yar -> torch, ktory je LEN vo .venv-yar.
# SYS_PY (/usr/bin/python3) torch NEMA -> remember cez neho VZDY zlyha (ModuleNotFoundError).
# Preto remember MUSI ist cez venv-yar interpreter.
VENV_PY = os.path.join(ZOL_ROOT, ".venv-yar", "bin", "python")
ZOL_MEM = os.path.join(ZOL_ROOT, "toolkit", "zol_mem.py")
# palantir_client zije v zolo2.0 toolkite
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)

# Extrakcny model — Opus 4.8 (__USER__ chce najvyssiu kvalitu extrakcie faktov,
# LLM je zadarmo). Prepisatelne cez env ZOL_WB_MODEL (napr. gpt-mini na lacnejsi beh).
EXTRACT_MODEL = os.environ.get("ZOL_WB_MODEL", "opus")
# Min. pocet NOVYCH user+assistant sprav (nad watermark) aby sa flush oplatil.
MIN_MSGS = int(os.environ.get("ZOL_WB_MIN_MSGS", "4"))
# Max znakov transkriptu do promptu (chran kontext extraktora).
MAX_TRANSCRIPT = int(os.environ.get("ZOL_WB_MAX_CHARS", "24000"))
# Idle prah: session bez ended_at sa flushne az ked je aspon tolko minut ticho.
# Chrani prebiehajuci dialog pred zapisom polovicnych faktov.
IDLE_MINUTES = int(os.environ.get("ZOL_WB_IDLE_MIN", "20"))
# Ktore source-y su Zolanderove konverzacie hodne pamate. Subagenti (delegate_task)
# su jednorazove ulohy, NIE jeho dialog s veduckom -> vynechat. cron = jeho auto-behy,
# NIE dialog -> tiez von (inak autoimunitna slucka). matrix = Beeper dialog s veduckom
# (realny rozhovor) -> DNU. Prepisatelne cez env ZOL_WB_SOURCES (ciarkou oddelene).
# --session obchadza filter (rucne vynutene).
WB_SOURCES = set(s.strip() for s in
                 os.environ.get("ZOL_WB_SOURCES", "cli,desktop,whatsapp,telegram,signal,matrix").split(",")
                 if s.strip())

EXTRACT_SYSTEM = """Si extraktor pamate pre AI agenta Zolander (partak pre pouzivatela __USER__).
Dostanes transkript jednej pracovnej session. Vytiahni 3-8 SALIENTNYCH, TRVACICH faktov
alebo rozhodnuti, ktore sa oplati PAMATAT do buducna. NIE zhrnutie deja, NIE raw dump.

Kazdy fakt musi byt:
- samostatne zrozumitelny bez kontextu session (kto/co/preco),
- trvaci (preferencia, rozhodnutie, nauceny postup, stav projektu, fakt o prostredi),
- NIE efemerny ("prave som spustil X"), NIE trivialny.

Pre kazdy fakt urci:
- text: jedna hutna slovenska veta (max ~200 znakov).
- kind: "semantic" (fakt/princip) | "episodic" (co sa stalo, udalost) |
        "procedural" (ako sa robi X, ked zlyha Y sprav Z) | "identity" (kto Zolander/__USER__ je, hodnoty).
- salience: 0.0-1.0 (ako dolezite pamatat; rozhodnutia/preferencie vysoko).

Vrat LEN validny JSON pole, ziadny iny text:
[{"text": "...", "kind": "semantic", "salience": 0.8}, ...]
Ak session nema nic hodne zapamatania, vrat []."""


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{now()} | {msg}\n")
    except Exception:
        pass


def load_done():
    """Legacy: session ktore stary writeback uz plne spracoval (preskakujeme ich)."""
    if not os.path.exists(DONE_FILE):
        return set()
    try:
        return set(l.strip() for l in open(DONE_FILE, encoding="utf-8") if l.strip())
    except Exception:
        return set()


def load_watermarks():
    """{session_id: max spracovane message.id}. Fail-open na prazdny dict."""
    if not os.path.exists(WATERMARK_FILE):
        return {}
    try:
        with open(WATERMARK_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as e:
        log(f"load_watermarks zlyhal (pokracujem s prazdnym): {e!r}")
        return {}


def save_watermarks(wm):
    """Atomicky zapis watermark mapu (temp + os.replace, nikdy netruncatuj na mieste)."""
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = WATERMARK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(wm, f, ensure_ascii=False, indent=0)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, WATERMARK_FILE)
    except Exception as e:
        log(f"save_watermarks zlyhal: {e!r}")


def fetch_candidates(conn, only_session=None):
    """Vrati agregaty session: (id, source, ended_at, last_ts, last_id, n).
    n = pocet VSETKYCH user/asst sprav (cheap pre-filter). Settle/idle rozhodnutie
    robi caller v Pythone (potrebuje aktualny cas)."""
    cur = conn.cursor()
    if only_session:
        cur.execute("""SELECT s.id, s.source, s.ended_at,
                              MAX(m.timestamp), MAX(m.id), COUNT(*)
                       FROM sessions s JOIN messages m ON m.session_id = s.id
                       WHERE s.id=? AND m.role IN ('user','assistant')
                         AND m.content IS NOT NULL AND m.content != ''
                       GROUP BY s.id""", (only_session,))
    else:
        cur.execute("""SELECT s.id, s.source, s.ended_at,
                              MAX(m.timestamp), MAX(m.id), COUNT(*)
                       FROM sessions s JOIN messages m ON m.session_id = s.id
                       WHERE s.archived=0 AND m.role IN ('user','assistant')
                         AND m.content IS NOT NULL AND m.content != ''
                       GROUP BY s.id
                       ORDER BY MAX(m.timestamp) ASC""")
    return cur.fetchall()


def fetch_new_transcript(conn, session_id, after_id):
    """user+assistant spravy danej session s id > after_id, chronologicky.
    Vrati (parts:list[str], max_id:int). max_id = najvyssie id sprav v tejto davke
    (0 ak nic nove)."""
    cur = conn.cursor()
    cur.execute("""SELECT id, role, content FROM messages
                   WHERE session_id=? AND id>? AND role IN ('user','assistant')
                     AND content IS NOT NULL AND content != ''
                   ORDER BY id ASC""", (session_id, after_id))
    rows = cur.fetchall()
    parts = []
    max_id = after_id
    for mid, role, content in rows:
        c = (content or "").strip()
        if c:
            parts.append(f"[{role.upper()}] {c}")
        if mid > max_id:
            max_id = mid
    return parts, max_id


def extract_facts(transcript_text):
    """LLM extrakcia salientnych faktov. Vrati zoznam dict alebo []."""
    from palantir_client import chat
    prompt = ("Transkript session (extrahuj salientne fakty):\n\n"
              + transcript_text)
    resp = chat(prompt, model=EXTRACT_MODEL, system=EXTRACT_SYSTEM, max_tokens=4000)
    resp = (resp or "").strip()
    # oloupej pripadny ```json fence
    if resp.startswith("```"):
        resp = resp.split("```", 2)[1] if "```" in resp else resp
        if resp.startswith("json"):
            resp = resp[4:]
        resp = resp.strip("` \n")
    try:
        facts = json.loads(resp)
        if isinstance(facts, list):
            return [f for f in facts if isinstance(f, dict) and f.get("text")]
    except Exception as e:
        # SALVAGE: pri useknutom JSON (napr. limit tokenov) zachran aspon kompletne
        # objekty {"text":...,"kind":...,"salience":...} regexom, nestrat celu session.
        import re
        salv = []
        for m in re.finditer(r'\{[^{}]*?"text"\s*:\s*"(?:[^"\\]|\\.)*"[^{}]*?\}', resp):
            try:
                o = json.loads(m.group(0))
                if isinstance(o, dict) and o.get("text"):
                    salv.append(o)
            except Exception:
                continue
        if salv:
            log(f"parse zlyhal, SALVAGE zachranil {len(salv)} kompletnych faktov: {e!r}")
            return salv
        log(f"parse extract JSON zlyhal (0 salvage): {e!r} | raw={resp[:200]}")
    return []


def remember(text, kind, salience):
    """Zapis jeden fakt cez zol_mem.py remember (ten si riesi venv-yar embed).
    Layer podla druhu: durable (identity/procedural/semantic) = L1, epizoda = L0.
    Decay je od 2026-08-13 riadeny KIND (nie layer), takze layer je uz len
    organizacny label, ale drzime ho konzistentne."""
    layer = "L0" if kind == "episodic" else "L1"
    payload = json.dumps({"text": text, "kind": kind, "layer": layer,
                          "salience": salience, "source": "writeback"},
                         ensure_ascii=False)
    p = subprocess.run([VENV_PY, ZOL_MEM, "remember"], input=payload,
                       capture_output=True, text=True, timeout=180)
    return p.returncode == 0


def process_session(parts, sid, source, dry_run):
    """Spracuj davku NOVYCH sprav (parts) jednej session. Vrati pocet zapisanych faktov."""
    transcript = "\n\n".join(parts)
    if len(transcript) > MAX_TRANSCRIPT:
        # vezmi zaciatok + koniec (kontext + zavery), nie stred
        head = transcript[:MAX_TRANSCRIPT // 2]
        tail = transcript[-MAX_TRANSCRIPT // 2:]
        transcript = head + "\n\n[...stred vynechany...]\n\n" + tail
    facts = extract_facts(transcript)
    log(f"session {sid} ({source}): {len(parts)} novych sprav -> {len(facts)} faktov extrahovanych")
    written = 0
    for f in facts:
        text = str(f.get("text", "")).strip()[:280]
        kind = f.get("kind", "episodic")
        if kind not in ("semantic", "episodic", "procedural", "identity"):
            kind = "episodic"
        try:
            sal = float(f.get("salience", 0.5))
        except Exception:
            sal = 0.5
        if not text:
            continue
        if dry_run:
            print(f"  [{kind} sal={sal:.2f}] {text}")
            written += 1
            continue
        if remember(text, kind, sal):
            written += 1
        else:
            log(f"  remember ZLYHAL: {text[:80]}")
    return written


def is_settled(source, ended_at, last_ts, only_session):
    """Je session usadena (hodna flushu)? --session vynuti. Inak: ended_at ALEBO
    posledna sprava starsia nez IDLE_MINUTES."""
    if only_session:
        return True
    if ended_at is not None:
        return True
    if last_ts is None:
        return False
    idle_min = (time.time() - float(last_ts)) / 60.0
    return idle_min >= IDLE_MINUTES


def _pid_alive(pid):
    """Zije proces s danym PID? (signal 0 = existencny test, nic neposle)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existuje, len nie nas -> povazuj za zivy
    except Exception:
        return False


def acquire_lock():
    """PID-lock: zabran dvom sucasnym writeback behom (race na watermark = duplikaty).
    Vrati True ak sme lock ziskali. Stale lock (drziaci proces uz nezije) preberieme."""
    try:
        os.makedirs(STATE, exist_ok=True)
        if os.path.exists(LOCK_FILE):
            try:
                held = int(open(LOCK_FILE, encoding="utf-8").read().strip() or "0")
            except Exception:
                held = 0
            if held and held != os.getpid() and _pid_alive(held):
                log(f"lock drzi zivy proces pid={held} -> tento beh preskakujem")
                return False
            # stale lock (mrtvy proces) -> preberieme
            if held:
                log(f"stale lock po mrtvom pid={held} -> preberam")
        tmp = LOCK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, LOCK_FILE)
        return True
    except Exception as e:
        log(f"acquire_lock zlyhal (pokracujem bez locku): {e!r}")
        return True  # fail-open: radsej bez locku nez nezapisovat vobec


def release_lock():
    """Uvolni lock IBA ak ho drzime my (nezmaz cudzi)."""
    try:
        if os.path.exists(LOCK_FILE):
            held = int(open(LOCK_FILE, encoding="utf-8").read().strip() or "0")
            if held == os.getpid():
                os.remove(LOCK_FILE)
    except Exception as e:
        log(f"release_lock zlyhal: {e!r}")


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only_session = None
    if "--session" in args:
        i = args.index("--session")
        only_session = args[i + 1] if i + 1 < len(args) else None

    if not os.path.exists(STATE_DB):
        log(f"state.db chyba: {STATE_DB}")
        return 1
    if not acquire_lock():
        return 0  # iny beh prave bezi -> ticho odid (nie chyba)
    done = load_done()
    watermarks = load_watermarks()
    wm_dirty = False
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=15)
    try:
        candidates = fetch_candidates(conn, only_session)
    except Exception as e:
        log(f"fetch_candidates zlyhal: {e!r}")
        conn.close()
        return 1

    total_written = 0
    total_sessions = 0
    for sid, source, ended_at, last_ts, last_id, n in candidates:
        # legacy: plne hotove starym writebackom -> preskoc (nereprocessuj).
        if not only_session and sid in done:
            continue
        # source filter (cron/subagent von). --session obchadza.
        if not only_session and source not in WB_SOURCES:
            continue
        # settle/idle gate — prebiehajuci dialog sa nedotkne.
        if not is_settled(source, ended_at, last_ts, only_session):
            continue
        wm = watermarks.get(sid, 0)
        try:
            parts, max_id = fetch_new_transcript(conn, sid, wm)
        except Exception as e:
            log(f"session {sid} fetch_new EXCEPTION: {e!r} — preskakujem")
            continue
        if not parts:
            continue  # ziadne nove spravy nad watermark = caught up
        # dost novej substancie? ended session dostane finalny zmet aj pod MIN.
        if len(parts) < MIN_MSGS and ended_at is None and not only_session:
            log(f"session {sid} ({source}): len {len(parts)} novych sprav < {MIN_MSGS}, cakam")
            continue
        try:
            w = process_session(parts, sid, source, dry_run)
            total_written += w
            total_sessions += 1
            if not dry_run:
                watermarks[sid] = max_id
                wm_dirty = True
                save_watermarks(watermarks)  # persist po kazdej session (crash-safe)
        except Exception as e:
            log(f"session {sid} EXCEPTION: {e!r} — preskakujem, watermark netknuty")
    conn.close()
    if wm_dirty:
        save_watermarks(watermarks)
    msg = (f"tick hotovy | session spracovanych={total_sessions} | "
           f"faktov zapisanych={total_written} | idle_prah={IDLE_MINUTES}min")
    log(msg)
    if dry_run:
        print(msg)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"WRITEBACK EXCEPTION: {e!r}")
        sys.exit(1)
    finally:
        release_lock()
