#!/usr/bin/env python3
"""recall_health.py — ONE place for recall fail-handling.

Problem it solves: recall fail-handling used to be scattered across cmd_recall with
THREE different policies — embed with no guard (hard crash), YAR search fail-CLOSED,
BM25/Gemma/rerank fail-OPEN SILENTLY. Result: when the embedding daemon died, recall
kept running on 2 branches and said NOTHING — so you wouldn't notice a lens was dead
for weeks. That scatter was a real hole.

Solution: cmd_recall just COLLECTS failures into one `degraded` dict (lens -> reason)
and calls report() at the end. This is the single place that decides what to do:
  1. SELF-HEAL: a lens backed by a service gets kicked (throttled). Cross-platform:
     systemctl --user on Linux, launchctl kickstart on macOS. No service manager
     (plain docker/manual run) -> self-heal is skipped, notify still fires.
  2. NOTIFY: throttled heads-up via zolander_notify (inbox + desktop + push).
  3. LLM INFO: returns a human-readable summary cmd_recall injects into the output so
     the session-start recall shows the model that memory is degraded — never hides it.

THROTTLE: state/recall_health_ledger.json holds last notify+heal time per lens. Notify
once per NOTIFY_COOLDOWN_S, heal once per HEAL_COOLDOWN_S — else every recall (Gemma down
= every one) would spam. Fail-open: this whole layer is best-effort, it NEVER kills recall.
"""
import os
import sys
import json
import time
import platform
import subprocess

HOME = os.path.expanduser("~")
try:
    from zol_paths import ZROOT
except Exception:
    ZROOT = os.environ.get("ZOLANDER_ROOT", os.path.join(HOME, "zolander"))
STATE = os.path.join(ZROOT, "state")
LEDGER = os.path.join(STATE, "recall_health_ledger.json")
NOTIFY = os.path.join(ZROOT, "toolkit", "zolander_notify.py")
SYS_PY = sys.executable or "python3"

IS_MAC = platform.system() == "Darwin"

NOTIFY_COOLDOWN_S = 1800   # 30 min — same problem alerts at most 1x/30min
HEAL_COOLDOWN_S = 300      # 5 min — restart a service at most 1x/5min

# lens key -> service identifier for self-heal (only lenses that ARE a restartable
# service). yar_embed = in-process (not a service), bm25 = a file -> notify only.
# macOS values are launchd labels; Linux values are systemd --user unit names.
# A HyperspaceDB running as a plain `docker run` container is restarted by name too.
SELF_HEAL_MAC = {
    "db":    "pl.zolander.hyperspace",   # YAR + Gemma search both go via :50051
    "gemma": "pl.zolander.gemmaembed",   # EmbeddingGemma embed daemon :8901
}
SELF_HEAL_LINUX = {
    "db":    "zolander-hyperspace.service",
    "gemma": "zolander-gemmaembed.service",
}
SELF_HEAL = SELF_HEAL_MAC if IS_MAC else SELF_HEAL_LINUX

# docker container name to restart if the service manager has no unit for it (the
# bootstrap default runs HyperspaceDB as a container called "hyperspace").
DOCKER_FALLBACK = {"db": os.environ.get("HS_CONTAINER", "hyperspace")}

LENS_DESC = {
    "yar_embed":  "YAR embed (query not vectorized — semantic branch dead)",
    "yar_search": "YAR/HyperspaceDB search (:50051)",
    "db":         "HyperspaceDB (:50051)",
    "bm25":       "BM25 lexical layer (mem_index.jsonl)",
    "gemma":      "EmbeddingGemma 3rd lens (daemon :8901)",
    "rerank":     "LLM re-rank (ordering only, not retrieval)",
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


def _kickstart(lens):
    """Restart the service backing `lens`. Cross-platform, best-effort.
    True if a restart command ran successfully."""
    ident = SELF_HEAL.get(lens)
    try:
        if ident and IS_MAC:
            uid = os.getuid()
            p = subprocess.run(
                ["/bin/launchctl", "kickstart", "-k", f"gui/{uid}/{ident}"],
                capture_output=True, text=True, timeout=15)
            if p.returncode == 0:
                return True
        elif ident:
            # systemd --user first
            p = subprocess.run(
                ["systemctl", "--user", "restart", ident],
                capture_output=True, text=True, timeout=20)
            if p.returncode == 0:
                return True
        # fallback: a plain docker container (same on both OSes)
        cont = DOCKER_FALLBACK.get(lens)
        if cont:
            p = subprocess.run(["docker", "restart", cont],
                               capture_output=True, text=True, timeout=30)
            return p.returncode == 0
    except Exception:
        return False
    return False


def _notify(subject, body):
    try:
        subprocess.run([SYS_PY, NOTIFY, "--subject", subject, "--sound", "Sosumi", body],
                       timeout=90, cwd=ZROOT)
        return True
    except Exception:
        return False


def report(degraded, source="adhoc", backend_down=False):
    """degraded: dict {lens: reason} or list[lens]. Return a human-readable summary
    string for the LLM (or "" when nothing). Side-effects (heal+notify) are throttled.
    Fail-open: any error here -> return at least the summary, NEVER raise."""
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
        # 1) SELF-HEAL (throttled) — only lenses backed by a service
        if lens in SELF_HEAL or lens in DOCKER_FALLBACK:
            last_heal = ledger.get(f"heal:{lens}", 0)
            if now - last_heal > HEAL_COOLDOWN_S:
                if _kickstart(lens):
                    healed.append(lens)
                ledger[f"heal:{lens}"] = now

        # 2) decide whether to NOTIFY (throttled per lens)
        last_notif = ledger.get(f"notify:{lens}", 0)
        if now - last_notif > NOTIFY_COOLDOWN_S:
            notified_lenses.append(lens)
            ledger[f"notify:{lens}"] = now

    # 3) one notification for all NEW degraded branches
    if notified_lenses:
        lines = ["Recall is DEGRADED — a memory layer dropped out:"]
        for lens in notified_lenses:
            d = degraded.get(lens) or ""
            lines.append(f"- {LENS_DESC.get(lens, lens)}" + (f": {d}" if d else ""))
        if healed:
            lines.append(f"(self-heal: tried to restart {', '.join(healed)})")
        if backend_down:
            lines.append("WARNING: ALL retrieval branches down — recall returns empty, not degraded.")
        _notify("recall DEGRADED", "\n".join(lines))

    _save_ledger(ledger)

    # 4) summary for the LLM (ALWAYS, even if notify throttled — the model must know NOW)
    parts = [str(LENS_DESC.get(l, l)) for l in degraded]
    if backend_down:
        return ("MEMORY PARTLY UNAVAILABLE — ALL retrieval branches down (" +
                ", ".join(parts) + "). Recall is empty, NOT 'no memories'. "
                "Check the DB/daemons; I tried self-heal + sent a notification.")
    return ("RECALL DEGRADED — dropped layer: " + ", ".join(parts) +
            ". Results are INCOMPLETE (running on the remaining branches). Self-heal "
            "+ notification sent. If expected memories are missing, this may be why.")
