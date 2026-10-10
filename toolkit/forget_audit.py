#!/usr/bin/env python3
"""forget_audit.py — Zolanderov PRACOVNY LLM-tick agent (prva realna uloha).

PROBLEM: cmd_decay (zol_mem.py) je MECHANICKY — hodi do forget fronty kazdy
episodic zaznam starsi nez prah a pod salience prahom, BEZ posudenia obsahu.
Fronta len rastie (201->318 za tyzden) a nikto ju necita. Vysledok: "implementoval
gradient oblohu" (efemerny commit) lezi v tej istej kope ako "__USER__ potrebuje
ritual startu" (trvaly insight) a "osobná poznámka X" (súkromné).

RIESENIE: tento agent je LLM vrstva NAD mechanickym vystupom. Pre kazdeho kandidata
(forget_state in dormant/retired_candidate) da Opus verdikt:
  - forget  : efemerny detail / jednorazova udalost / zastarany stav -> moze zmiznut
  - keep    : stale operacne relevantne -> vrat do active (obnov salience)
  - promote : TRVALY fakt o veduckovi (zdravie, preferencie, vztahy, financie),
              proceduralne pravidlo, alebo dolezity insight -> povys na durable kind
              (semantic/procedural/identity), nech sa prestane rozpadat decayom

BEZPECNOST (design): agent NEMAZE a NEMENI pamat. LEN pise verdikty na schvalenie
do work/forget_audit/verdicts.jsonl. Aplikacia (forget/promote/keep) je za "zrob N"
approvalom cez `forget_audit.py apply`. Cita mem_index.jsonl READ-ONLY.

DURABLE vzor (durable-unattended-batch-jobs):
  - progress.json = zdroj pravdy (done_ids), idempotentny resume (STRUKTURALNY check:
    id uz ma verdikt), fresh proces per tick.
  - atomicky zapis (tmp + os.replace), nikdy half-written subor.
  - retry kaskada per batch: cely batch -> polovice -> per-item. Nikdy nefabrikovat
    verdikt; chybajuce id -> zaloguj FAIL, dalsi tik doberie.
  - LLM dostane {id, text}, vracia LEN {id, verdikt, dovod, promote_kind} — text sa
    NEEnevhodneE (model kazi diakritiku); parujeme cez id.

Pouzitie:
  /usr/bin/python3 forget_audit.py --once           # jeden chunk (launchd tik)
  /usr/bin/python3 forget_audit.py --all            # cela fronta naraz (manualny/prvy beh)
  /usr/bin/python3 forget_audit.py --once --chunk 8 # mensi chunk (test/dokaz)
  /usr/bin/python3 forget_audit.py verify           # ranny audit z disku (co je hotove)
  /usr/bin/python3 forget_audit.py report           # kratky text report pre notify
"""
import os
import sys
import json
import time
import tempfile

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
WORK = os.path.join(ROOT, "work", "forget_audit")
IDX = os.path.join(STATE, "mem_index.jsonl")
PROGRESS = os.path.join(WORK, "progress.json")
VERDICTS = os.path.join(WORK, "verdicts.jsonl")
AUDIT_LOG = os.path.join(WORK, "audit.log")

sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))  # palantir_client (legacy)
sys.path.insert(0, os.path.join(HOME, "projects", "common"))  # palantir_client (reorg 2026-09)
sys.path.insert(0, os.path.join(ROOT, "toolkit"))

MODEL = os.environ.get("ZOL_FA_MODEL", "opus")
CHUNK = int(os.environ.get("ZOL_FA_CHUNK", "40"))       # kandidatov za tik
BATCH = int(os.environ.get("ZOL_FA_BATCH", "8"))        # kandidatov na 1 LLM volanie
LLM_TIMEOUT = int(os.environ.get("ZOL_FA_LLM_TIMEOUT", "180"))
CAND_STATES = {"dormant", "retired_candidate"}
VALID_VERDICTS = {"forget", "keep", "promote"}
VALID_KINDS = {"semantic", "procedural", "identity"}

SYSTEM = """Si Zolander — perzistentny AI partak/mentor pre pouzivatela 'veducko' (__USER__).
Toto je AUDIT PAMATE. Mechanicky decay oznacil tieto spomienky na ZABUDNUTIE len preto,
ze su stare episodicke zaznamy s nizkou salienciou — OBSAH nikto neposudil. Tvoja uloha:
precitaj kazdu a rozhodni, ci ma naozaj zmiznut, alebo je to nieco co treba UDRZAT.

Pre KAZDU spomienku vrat verdikt:
- "forget"  = efemerny implementacny detail (konkretny commit, docasny stav, jednorazovy
              technicky krok), zastarana informacia, alebo udalost bez trvalej hodnoty.
              Toto moze pokojne zmiznut.
- "keep"    = stale operacne relevantne, vrat do aktivnej pamate (este sa hodi, ale nie je
              to trvaly fakt na povysenie).
- "promote" = TRVALY fakt hodny durable pamate: fakt o veduckovi (zdravie, lieky,
              preferencie, vztahy, financie, rodina, pravne veci), proceduralne pravidlo
              ("takto sa robi X"), alebo hlboky insight o jeho povahe/vzorcoch. Toto sa
              NESMIE stratit — povys to nech sa prestane rozpadat.
              Ak promote, urci promote_kind: "semantic" (fakt/znalost), "procedural"
              (pravidlo/postup), alebo "identity" (jadrovy fakt o veduckovi/o tebe).

Bud PRISNY na forget u cisto technickych efemernych detailov, a OPATRNY (radsej keep/promote)
u cohokolvek o veduckovom zdravi, financiach, vztahoch, pravnych veciach alebo jeho povahe —
tam je strata draha. Pri pochybnosti medzi forget a keep -> keep.

Dostanes JSON pole spomienok [{id, text}]. Vrat LEN validny JSON pole, jeden objekt na kazde
poslane id, v tvare:
[{"id": <int>, "verdikt": "forget|keep|promote", "promote_kind": "semantic|procedural|identity|null", "dovod": "1 kratka veta preco"}]
Ziadny text okrem toho JSON pola. Kazde poslane id MUSI mat prave jeden objekt."""


def log(msg):
    os.makedirs(WORK, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}"
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def _atomic_write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_progress():
    if os.path.exists(PROGRESS):
        try:
            return json.load(open(PROGRESS, encoding="utf-8"))
        except Exception:
            pass
    return {"done_ids": [], "counts": {"forget": 0, "keep": 0, "promote": 0},
            "started": None, "updated": None, "total_candidates": 0}


def save_progress(p):
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_write(PROGRESS, json.dumps(p, ensure_ascii=False, indent=2))


def append_verdicts(records):
    os.makedirs(WORK, exist_ok=True)
    with open(VERDICTS, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_candidates():
    """READ-ONLY: nacitaj kandidatov na audit z mem_index.jsonl."""
    if not os.path.exists(IDX):
        return []
    out = []
    for l in open(IDX, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("forget_state") in CAND_STATES:
            out.append(r)
    return out


def _call_llm(items):
    """Zavolaj LLM na batch [{id,text}], vrat dict id->verdikt objekt. Fail => {}."""
    import signal
    from palantir_client import chat

    class _T(Exception):
        pass

    def _to(s, f):
        raise _T()

    payload = json.dumps([{"id": it["id"], "text": it["text"]} for it in items], ensure_ascii=False)
    old = signal.signal(signal.SIGALRM, _to)
    signal.alarm(LLM_TIMEOUT)
    try:
        resp = chat(payload, model=MODEL, system=SYSTEM, max_tokens=1600, max_retries=2).strip()
    except Exception as e:
        log(f"LLM chyba/timeout (batch {len(items)}): {e!r}")
        return {}
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    if resp.startswith("```"):
        resp = resp.split("\n", 1)[-1] if "\n" in resp else resp
        resp = resp.strip("` \n")
        if resp.lower().startswith("json"):
            resp = resp[4:].strip()
    try:
        arr = json.loads(resp[resp.find("["):resp.rfind("]") + 1])
    except Exception as e:
        log(f"LLM parse chyba: {e!r} | raw={resp[:160]}")
        return {}
    got = {}
    for o in arr:
        try:
            i = int(o["id"])
            v = o.get("verdikt", "").strip()
            if v not in VALID_VERDICTS:
                continue
            pk = o.get("promote_kind")
            if v != "promote" or pk not in VALID_KINDS:
                pk = None
            got[i] = {"verdikt": v, "promote_kind": pk, "dovod": (o.get("dovod") or "")[:200]}
        except Exception:
            continue
    return got


def audit_batch(items):
    """Retry kaskada: cely batch -> polovice -> per-item. Vrat dict id->verdikt."""
    if not items:
        return {}
    got = _call_llm(items)
    missing = [it for it in items if it["id"] not in got]
    if not missing:
        return got
    if len(items) > 1:
        # rozdel na polovice a skus znova len chybajuce
        mid = len(missing) // 2 or 1
        for half in (missing[:mid], missing[mid:]):
            if half:
                got.update(audit_batch(half))
        return got
    # jedno id a stale chyba -> jeden posledny per-item pokus, potom FAIL (nefabrikuj)
    solo = _call_llm(items)
    got.update(solo)
    for it in items:
        if it["id"] not in got:
            log(f"FAIL: id={it['id']} sa neda posudit (dalsi tik doberie)")
    return got


def run(all_at_once=False, chunk=None):
    chunk = chunk or CHUNK
    cands = load_candidates()
    p = load_progress()
    p["total_candidates"] = len(cands)
    if p["started"] is None:
        p["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
    done = set(p["done_ids"])
    todo = [c for c in cands if c["id"] not in done]
    if not todo:
        log(f"HOTOVO: vsetkych {len(cands)} kandidatov spracovanych, fronta prazdna.")
        save_progress(p)
        return 0
    if not all_at_once:
        todo = todo[:chunk]
    log(f"START: {len(todo)} kandidatov tento beh (spolu fronta {len(cands)}, hotovo {len(done)}), model={MODEL}")

    processed = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        items = [{"id": c["id"], "text": (c.get("text") or "")[:600]} for c in batch]
        got = audit_batch(items)
        recs = []
        # inject verbatim text LOKALNE (nie z LLM) — parujeme cez id
        by_id = {c["id"]: c for c in batch}
        for cid, verd in got.items():
            c = by_id.get(cid, {})
            recs.append({
                "id": cid,
                "verdikt": verd["verdikt"],
                "promote_kind": verd["promote_kind"],
                "dovod": verd["dovod"],
                "text_preview": (c.get("text") or "")[:120],
                "kind": c.get("kind"),
                "salience": c.get("salience"),
                "ts_mem": c.get("ts"),
                "model": MODEL,
                "audited_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            p["counts"][verd["verdikt"]] += 1
            p["done_ids"].append(cid)
            processed += 1
        if recs:
            append_verdicts(recs)
            save_progress(p)  # progress po KAZDOM batchi (crash-safe)
    log(f"BEH KONIEC: spracovanych {processed}, counts={p['counts']}, "
        f"zostava {len(cands) - len(p['done_ids'])}")
    return 0


def cmd_verify():
    """Ranny audit Z DISKU — nie zo self-reportu. Over integritu verdicts vs progress."""
    p = load_progress()
    cands = load_candidates()
    vids, dups, bad = set(), 0, 0
    counts = {"forget": 0, "keep": 0, "promote": 0}
    if os.path.exists(VERDICTS):
        for l in open(VERDICTS, encoding="utf-8"):
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except Exception:
                bad += 1
                continue
            if r["id"] in vids:
                dups += 1
            vids.add(r["id"])
            if r.get("verdikt") in counts:
                counts[r["verdikt"]] += 1
    print(json.dumps({
        "kandidatov_v_fronte": len(cands),
        "verdiktov_na_disku": len(vids),
        "duplicit": dups,
        "poskodenych_riadkov": bad,
        "counts": counts,
        "progress_done": len(p.get("done_ids", [])),
        "progress_vs_verdicts_sedi": len(p.get("done_ids", [])) == len(vids),
        "zostava": len(cands) - len(vids),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_report():
    """Kratky text report pre notify/WhatsApp."""
    p = load_progress()
    cands = load_candidates()
    done = len(p.get("done_ids", []))
    c = p.get("counts", {})
    promote_n = c.get("promote", 0)
    zostava = len(cands) - done
    lines = [
        f"🧠 Forget-audit: prešiel som {done}/{len(cands)} spomienok z fronty na zabudnutie.",
        f"   • zabudnúť: {c.get('forget',0)}  • nechať: {c.get('keep',0)}  • POVÝŠIŤ (trvalé o tebe): {promote_n}",
    ]
    if promote_n:
        # ukaz par najdolezitejsich promote navrhov
        prom = []
        if os.path.exists(VERDICTS):
            for l in open(VERDICTS, encoding="utf-8"):
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                if r.get("verdikt") == "promote":
                    prom.append(r)
        for r in prom[:4]:
            lines.append(f"   ↑ #{r['id']} ({r.get('promote_kind')}): {r.get('text_preview','')}")
        if len(prom) > 4:
            lines.append(f"   … a ďalších {len(prom)-4} na povýšenie")
    if zostava > 0:
        lines.append(f"   zostáva {zostava}, dobehnem ďalším tickom.")
    else:
        lines.append("   Fronta hotová. Schváľ verdikty cez 'zrob forget-apply' (najprv ti ich ukážem).")
    print("\n".join(lines))
    return 0


def _push_notify():
    """Po behu posli report cez zolander_notify.py (fail-open, nezhodi agenta)."""
    import subprocess
    notify = os.path.join(ROOT, "toolkit", "zolander_notify.py")
    if not os.path.exists(notify):
        return
    # vygeneruj report do stringu (rovnaka logika ako cmd_report, ale vratime text)
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            cmd_report()
        body = buf.getvalue().strip()
    except Exception as e:
        log(f"notify: report zlyhal (fail-open): {e!r}")
        return
    if not body:
        return
    try:
        subprocess.run(["/usr/bin/python3", notify, "--subject", "forget-audit", body],
                       timeout=90)
    except Exception as e:
        log(f"notify: push zlyhal (fail-open): {e!r}")


def _push_text(body):
    """Posli lubovolny text cez zolander_notify.py (fail-open, nezhodi agenta)."""
    import subprocess
    notify = os.path.join(ROOT, "toolkit", "zolander_notify.py")
    if not os.path.exists(notify) or not body:
        return
    try:
        subprocess.run(["/usr/bin/python3", notify, "--subject", "forget-audit", body],
                       timeout=90)
    except Exception as e:
        log(f"push_text zlyhal (fail-open): {e!r}")


def _load_verdicts():
    """Nacitaj verdikty z disku (posledny verdikt na id vyhrava). Vrat dict id->rec."""
    out = {}
    if not os.path.exists(VERDICTS):
        return out
    for l in open(VERDICTS, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            r = json.loads(l)
            out[int(r["id"])] = r
        except Exception:
            continue
    return out


# durable kind -> base salience (zrkadli KIND_BASE v zol_mem.py). Ked ich decay uz
# nezhodi (identity decay=0.0, semantic/procedural takmer 0), staci realna base.
_PROMOTE_BASE = {"identity": 0.9, "procedural": 0.8, "semantic": 0.7}
# keep: vrat episodic nad forget prah nech ho decay HNED zas nezhodi
_KEEP_SALIENCE = 0.3


IDENTITY_PENDING = os.path.join(WORK, "identity_pending.jsonl")


def _write_index_atomic(rows, changed_rows):
    """Zaloha + atomicky zapis mem_index.jsonl. Vrat cestu k zalohe."""
    backup = IDX + ".pre_forget_apply." + time.strftime("%Y%m%d_%H%M%S")
    import shutil
    shutil.copy2(IDX, backup)
    tmp = IDX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, IDX)
    log(f"APPLY OSTRY: {changed_rows} zmien zapisanych, zaloha={os.path.basename(backup)}")
    return backup


def cmd_apply(do_write=False, include_identity=False):
    """Aplikuj verdikty forget-auditu na mem_index.jsonl. RISK-TRIAGE.

    AUTO-SAFE (aplikuje sa sam, aj pri do_write z launchd):
      - forget -> forget_state=retired (MAKKE: nemaze z DB, len von z recall, reverzibilne)
      - keep   -> forget_state=active, salience nad prah
      - promote -> semantic/procedural (len povysi durabilitu, obsah nemeni)
    GATED (caka na explicitne 'zrob identity' = include_identity=True):
      - promote -> IDENTITY (jadro 'kto veducko je' + Opus tam prestreluje nalepku)
        Ulozi sa do identity_pending.jsonl a posle sa JEDNA WhatsApp sprava.

    Zdroj pravdy = mem_index.jsonl. ZIADNY DB zapis / re-embed. Ostry zapis LEN pri
    do_write=True; vtedy ZALOHA indexu. Fronta sa NIKDY nezasekne (auto-safe ide vzdy).
    """
    verds = _load_verdicts()
    if not verds:
        print("Ziadne verdikty na disku — najprv spusti audit (--all).")
        return 1
    if not os.path.exists(IDX):
        print("Chyba mem_index.jsonl.")
        return 1
    rows = [json.loads(l) for l in open(IDX, encoding="utf-8") if l.strip()]
    plan = {"promote": [], "forget": [], "keep": [], "identity": [], "noop": 0}
    changed_rows = 0

    def _do_promote(r, before, pk):
        base = _PROMOTE_BASE[pk]
        after = {"kind": pk, "forget_state": "active", "salience": base}
        if before == after:
            plan["noop"] += 1
            return False
        r["kind"] = pk
        r["memory_type"] = pk
        r["base_salience"] = base
        r["salience"] = base
        r["forget_state"] = "active"
        r["promoted_by"] = "forget_audit"
        r["promoted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return True

    for r in rows:
        rid = r.get("id")
        v = verds.get(rid)
        if not v:
            continue
        verd = v.get("verdikt")
        before = {"kind": r.get("kind"), "forget_state": r.get("forget_state"),
                  "salience": r.get("salience")}
        if verd == "promote":
            pk = v.get("promote_kind")
            if pk not in _PROMOTE_BASE:
                pk = "semantic"  # fallback: promote bez platneho kind -> semantic
            if pk == "identity" and not include_identity:
                # GATE: identita caka na ludske slovo — do fronty, NEaplikuj teraz
                if r.get("kind") != "identity":
                    plan["identity"].append((rid, before,
                                             {"kind": "identity", "salience": 0.9},
                                             v.get("text_preview", "")))
                else:
                    plan["noop"] += 1
                continue
            after = {"kind": pk, "forget_state": "active", "salience": _PROMOTE_BASE[pk]}
            if _do_promote(r, before, pk):
                plan["promote"].append((rid, before, after, v.get("text_preview", "")))
                changed_rows += 1
        elif verd == "forget":
            if r.get("forget_state") != "retired":
                plan["forget"].append((rid, before, {"forget_state": "retired"},
                                       v.get("text_preview", "")))
                r["forget_state"] = "retired"
                r["retired_by"] = "forget_audit"
                r["retired_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                changed_rows += 1
            else:
                plan["noop"] += 1
        elif verd == "keep":
            new_sal = max(float(r.get("salience", 0.0)), _KEEP_SALIENCE)
            after = {"forget_state": "active", "salience": new_sal}
            if before.get("forget_state") != "active" or before.get("salience") != new_sal:
                plan["keep"].append((rid, before, after, v.get("text_preview", "")))
                r["forget_state"] = "active"
                r["salience"] = new_sal
                changed_rows += 1
            else:
                plan["noop"] += 1

    # --- DIFF vypis (vzdy) ---
    def _show(label, items, limit):
        print(f"\n=== {label}: {len(items)} ===")
        for rid, b, a, txt in items[:limit]:
            print(f"  #{rid}: {b} -> {a}")
            if txt:
                print(f"        \"{txt}\"")
        if len(items) > limit:
            print(f"  … a dalsich {len(items) - limit}")

    _show("AUTO PROMOTE (semantic/procedural)", plan["promote"], 40)
    _show("AUTO FORGET (-> retired, reverzibilne)", plan["forget"], 12)
    _show("AUTO KEEP (salience bump)", plan["keep"], 6)
    _show("GATED PROMOTE -> IDENTITY (caka na 'zrob identity')", plan["identity"], 40)
    lbl = "vratane identity" if include_identity else "auto-safe"
    print(f"\nSPOLU auto zmien: {changed_rows} riadkov ({lbl}) | "
          f"identity vo fronte: {len(plan['identity'])} | no-op: {plan['noop']}")

    if not do_write:
        print("\n[DRY-RUN] Nic sa NEzapisalo. Ostry beh: forget_audit.py apply --apply"
              "  |  identity: forget_audit.py apply --apply --identity")
        return 0

    # --- OSTRY ZAPIS auto-safe zmien ---
    if changed_rows:
        backup = _write_index_atomic(rows, changed_rows)
        print(f"\n✅ ZAPISANE (auto-safe): {changed_rows} zmien. Zaloha: {backup}")
    else:
        print("\n(ziadne auto-safe zmeny na zapis)")

    # --- IDENTITY GATE: uloz frontu + posli JEDNU spravu (len ked NEboli aplikovane) ---
    if plan["identity"] and not include_identity:
        new_ids = sorted(rid for rid, _b, _a, _t in plan["identity"])
        # anti-spam: posli len ked sa fronta ZMENILA oproti tomu co uz caka na disku
        old_ids = []
        if os.path.exists(IDENTITY_PENDING):
            for l in open(IDENTITY_PENDING, encoding="utf-8"):
                l = l.strip()
                if not l:
                    continue
                try:
                    old_ids.append(int(json.loads(l)["id"]))
                except Exception:
                    pass
        os.makedirs(WORK, exist_ok=True)
        with open(IDENTITY_PENDING, "w", encoding="utf-8") as f:
            for rid, _b, _a, txt in plan["identity"]:
                f.write(json.dumps({"id": rid, "text_preview": txt}, ensure_ascii=False) + "\n")
        n = len(plan["identity"])
        if sorted(old_ids) == new_ids:
            print(f"\n(identity fronta {n} nezmenena — WhatsApp preskoceny, nespamujem)")
        else:
            preview = "\n".join(f"  #{rid} {txt[:70]}"
                                for rid, _b, _a, txt in plan["identity"][:5])
            msg = (f"🧠 Pamäť: {n} návrhov na povýšenie na IDENTITU čaká na tvoje slovo "
                   f"(ostatné {changed_rows} som spravil sám).\n{preview}"
                   + (f"\n  … +{n-5} ďalších" if n > 5 else "")
                   + "\nSchváliť všetky: napíš „zrob identity“ (alebo pozri "
                     "work/forget_audit/identity_pending.jsonl).")
            _push_text(msg)
            print(f"\n📤 Identity gate: {n} návrhov do fronty + WhatsApp správa odoslaná.")
    elif include_identity:
        print("\n(identity promócie aplikované rovno — gate preskočený)")
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        args = ["--once"]
    if args[0] == "verify":
        return cmd_verify()
    if args[0] == "report":
        return cmd_report()
    if args[0] == "apply":
        return cmd_apply(do_write="--apply" in args,
                         include_identity="--identity" in args)
    if args[0] == "--cycle":
        # DENNY CYKLUS (launchd): audit celej fronty -> auto-apply safe zmien -> identity gate.
        # Toto je to, co robi loop realne uzitocnym: nie len navrhne, ale aj VYKONA
        # (bezpecne veci sam, identitu posle na schvalenie). Fronta sa nikdy nezasekne.
        rc = run(all_at_once=True, chunk=None)
        cmd_apply(do_write=True, include_identity=False)
        return rc
    all_at_once = "--all" in args
    chunk = None
    if "--chunk" in args:
        try:
            chunk = int(args[args.index("--chunk") + 1])
        except Exception:
            pass
    rc = run(all_at_once=all_at_once, chunk=chunk)
    if "--notify" in args:
        _push_notify()
    return rc


if __name__ == "__main__":
    sys.exit(main())
