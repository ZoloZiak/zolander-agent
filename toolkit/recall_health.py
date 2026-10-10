#!/usr/bin/env python3
"""recall_health.py — JEDNO miesto pre fail-handling recallu.

PROBLEM ktory riesi (veducko, 2026-10-01): fail-handling bol rozsypany na 5 miestach
v cmd_recall s TROMI roznymi politikami — embed_one BEZ ochrany (tvrdy crash), YAR search
fail-CLOSED, BM25/Gemma/rerank fail-OPEN TICHO. Dosledok: ked Gemma daemon spadol, recall
bezal dalej na 2 vetvach a NIKDE ani slovo — presne preto sme tyzdne nevedeli ze Gemma
kolekcia je rozbita. Tato rozsypanost bola skutocna diera.

RIESENIE: cmd_recall uz len ZBIERA zlyhania do jedneho `degraded` zoznamu (lens -> dovod)
a NA KONCI zavola report(). Tu je JEDINE miesto kde sa rozhoduje co s degradaciou:
  1. SELF-HEAL: daemon ktory ma launchd label sa skusi kickstartnut (throttled).
  2. NOTIFY: throttled upozornenie cez zolander_notify (inbox + desktop + push).
  3. LLM INFORMOVANIE: vrati human-readable summary, ktory cmd_recall vlozi do vystupu
     (dict wrapper) nech ho session-start recall ukaze modelu — NEtaji degradaciu.

THROTTLE: state/recall_health_ledger.json drzi posledny notify+heal cas per lens. Notify
raz za NOTIFY_COOLDOWN_S, heal raz za HEAL_COOLDOWN_S — inak by kazdy recall (Gemma dole =
kazdy) spamoval banner a bil launchd. Fail-open: cela tato vrstva je best-effort, NIKDY
nezhodi recall (chyba v healtli nesmie zabit pamat).
"""
import os
import json
import time
import subprocess

HOME = os.path.expanduser("~")
try:
    from zol_paths import ZROOT
except Exception:
    ZROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ZROOT, "state")
LEDGER = os.path.join(STATE, "recall_health_ledger.json")
NOTIFY = os.path.join(ZROOT, "toolkit", "zolander_notify.py")
SYS_PY = "/usr/bin/python3"

NOTIFY_COOLDOWN_S = 1800   # 30 min — ten isty problem upozorni max 1x/30min
HEAL_COOLDOWN_S = 300      # 5 min — kickstart daemona max 1x/5min (nebi launchd)

# lens kluc -> launchd label (len tie co SU daemon a daju sa restartnut).
# yar_embed = v procese (nie daemon), bm25 = subor -> self-heal sa nedа, len notify.
SELF_HEAL = {
    "db": "pl.zolander.hyperspace",       # YAR search + Gemma search obe idu cez :50051
    "gemma": "pl.zolander.gemmaembed",    # EmbeddingGemma embed daemon :8901
}

# human-citatelny popis kazdej vetvy pre LLM summary
LENS_DESC = {
    "yar_embed": "YAR embed (query sa nevektorizoval — semantic vetva mrtva)",
    "yar_search": "YAR/HyperspaceDB search (:50051)",
    "db": "HyperspaceDB (:50051)",
    "bm25": "BM25 lexikalna vrstva (mem_index.jsonl)",
    "gemma": "EmbeddingGemma 3. lens (daemon :8901)",
    "rerank": "Opus re-rank (len poradie, nie retrieval)",
}


def _load_ledger():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ledger(d):
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = LEDGER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, LEDGER)
    except Exception:
        pass


def _kickstart(label):
    """launchctl kickstart -k gui/<uid>/<label>. True ak prikaz zbehol (rc 0)."""
    try:
        uid = os.getuid()
        p = subprocess.run(
            ["/bin/launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
            capture_output=True, text=True, timeout=15,
        )
        return p.returncode == 0
    except Exception:
        return False


def _notify(subject, body):
    try:
        subprocess.run([SYS_PY, NOTIFY, "--subject", subject, "--sound", "Sosumi", body],
                       timeout=90, cwd=ZROOT)
        return True
    except Exception:
        return False


def report(degraded, source="adhoc", backend_down=False):
    """degraded: dict {lens: dovod} alebo list[lens]. Vrat human-readable summary
    string pre LLM (alebo "" ked nic). Side-effecty (heal+notify) su throttled.
    Fail-open: akakolvek chyba tu -> vrat aspon summary, NIKDY neraise."""
    if not degraded:
        return ""
    if isinstance(degraded, (list, tuple, set)):
        degraded = {k: "" for k in degraded}

    now = time.time()
    try:
        ledger = _load_ledger()
    except Exception:
        ledger = {}

    healed, notified_lenses = [], []
    for lens in degraded:
        # 1) SELF-HEAL (throttled) — len daemony s labelom
        label = SELF_HEAL.get(lens)
        if label:
            last_heal = ledger.get(f"heal:{lens}", 0)
            if now - last_heal > HEAL_COOLDOWN_S:
                if _kickstart(label):
                    healed.append(lens)
                ledger[f"heal:{lens}"] = now

        # 2) rozhodni ci NOTIFY (throttled per lens)
        last_notif = ledger.get(f"notify:{lens}", 0)
        if now - last_notif > NOTIFY_COOLDOWN_S:
            notified_lenses.append(lens)
            ledger[f"notify:{lens}"] = now

    # 3) jedna notifikacia za vsetky NOVE degradovane vetvy (dedup cez throttle)
    if notified_lenses:
        lines = ["Recall je DEGRADOVANY — vypadla vrstva pamate:"]
        for lens in notified_lenses:
            d = degraded.get(lens) or ""
            lines.append(f"- {LENS_DESC.get(lens, lens)}" + (f": {d}" if d else ""))
        if healed:
            lines.append(f"(self-heal: skusil som restartnut {', '.join(healed)})")
        if backend_down:
            lines.append("POZOR: VSETKY retrieval vetvy dole — recall vracia prazdno, nie degradovane.")
        _notify("recall DEGRADED", "\n".join(lines))

    _save_ledger(ledger)

    # 4) summary pre LLM (VZDY, aj ked notify throttled — model ma vediet TERAZ)
    parts = [str(LENS_DESC.get(l, l)) for l in degraded]
    if backend_down:
        return ("PAMAT CASTOCNE NEDOSTUPNA — VSETKY retrieval vetvy dole (" +
                ", ".join(parts) + "). Recall je prazdny, NIE 'ziadne spomienky'. "
                "Over DB/daemony; ja som skusil self-heal + poslal notifikaciu.")
    return ("RECALL DEGRADOVANY — vypadla vrstva: " + ", ".join(parts) +
            ". Vysledky su NEUPLNE (bezim na zvysnych vetvach). Self-heal + notifikacia "
            "odoslane. Ak chybaju ocakavane spomienky, moze to byt tym.")
