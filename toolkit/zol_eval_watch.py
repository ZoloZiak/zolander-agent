#!/usr/bin/env python3
"""zol_eval_watch.py — periodicka INICIATIVNA kontrola kvality recallu.

Beh (launchd, tyzdenne): spusti mem_eval.py na existujucom gold-sete, porovnaj MRR
s poslednym behom + pozri o kolko narastol korpus. TICHO ked je vsetko OK; posle
navrh na WhatsApp LEN ked:
  (a) MRR kleslo o >= EVAL_DROP (default 0.05) oproti poslednemu behu = REGRESIA, alebo
  (b) korpus narastol o >= EVAL_GROWTH zaznamov (default 60) od posl. gold-setu =
      gold-set uz nereprezentuje pamat, treba re-meranie.
Stav v state/eval_history.jsonl (append kazdy beh). Fail-open (nikdy nezhodi launchd).

Preco nie cron/agent: rovnaky vzor ako ostatne durable daemony (loop/dream/brief) —
launchd, /usr/bin/python3 volajuci .venv-yar podproces pre embed. Bez LLM okrem re-ranku
(ten sa v tejto kontrole NEmeria — drahy; meria sa hybrid W=1.3, co je lacne).
"""
import os
import re
import sys
import json
import time
import subprocess
import datetime

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, "zolander", "state")
TOOLKIT = os.path.join(HOME, "zolander", "toolkit")
VPY = os.path.join(HOME, "zolander", ".venv-yar", "bin", "python")
IDX = os.path.join(STATE, "mem_index.jsonl")
GOLD = os.path.join(STATE, "mem_eval_gold.json")
HIST = os.path.join(STATE, "eval_history.jsonl")
NOTIFY = os.path.join(TOOLKIT, "zolander_notify.py")
LOG = os.path.join(HOME, "zolander", "logs", "eval_watch.log")

EVAL_DROP = float(os.environ.get("EVAL_DROP", "0.05"))
EVAL_GROWTH = int(os.environ.get("EVAL_GROWTH", "60"))
CA = os.path.join(HOME, ".config/certs/corp-ca-bundle.pem")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {msg}\n")
    except Exception:
        pass


def corpus_size():
    try:
        return sum(1 for l in open(IDX, encoding="utf-8") if l.strip())
    except Exception:
        return 0


def last_run():
    try:
        rows = [json.loads(l) for l in open(HIST) if l.strip()]
        return rows[-1] if rows else None
    except Exception:
        return None


def run_eval():
    """Spusti mem_eval.py, vytiahni MRR hybrid W=1.3 z vystupu. None ak zlyha."""
    env = dict(os.environ)
    if os.path.exists(CA):
        env.setdefault("SSL_CERT_FILE", CA)
    try:
        p = subprocess.run([VPY, os.path.join(TOOLKIT, "mem_eval.py")],
                           capture_output=True, text=True, timeout=600, env=env)
    except Exception as e:
        log(f"mem_eval ZLYHAL: {e!r}")
        return None
    out = p.stdout or ""
    m = re.search(r"hybrid W=1\.3\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", out)
    if not m:
        log(f"MRR sa nenaslo vo vystupe (rc={p.returncode})")
        return None
    return float(m.group(1))


def notify(subject, body):
    if not os.path.exists(NOTIFY):
        log(f"notify chyba: {subject}")
        return
    try:
        subprocess.run(["/usr/bin/python3", NOTIFY, "--subject", subject, body],
                       capture_output=True, text=True, timeout=90)
    except Exception as e:
        log(f"notify zlyhal: {e!r}")


def main():
    if not os.path.exists(GOLD):
        log("gold-set chyba — preskocene (spusti mem_eval_goldset.py raz)")
        return 0
    size = corpus_size()
    prev = last_run()
    mrr = run_eval()
    if mrr is None:
        return 0  # fail-open

    entry = {"ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             "mrr": round(mrr, 3), "corpus": size}
    try:
        with open(HIST, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # rozhodni ci navrhnut (INICIATIVA) — inak ticho
    reasons = []
    if prev:
        drop = prev.get("mrr", 1.0) - mrr
        if drop >= EVAL_DROP:
            reasons.append(f"MRR kleslo {prev['mrr']:.3f} -> {mrr:.3f} (regresia kvality "
                           f"pamate) — over co sa zmenilo (embedder/vahy/korpus).")
        grown = size - prev.get("corpus", size)
        if grown >= EVAL_GROWTH:
            reasons.append(f"korpus narastol o {grown} zaznamov ({prev.get('corpus')}"
                           f" -> {size}) od posl. merania — gold-set uz nemusi "
                           f"reprezentovat pamat, oplati sa regenerovat + premeriat.")
    log(f"MRR={mrr:.3f} corpus={size} navrhy={len(reasons)}")
    if reasons:
        body = ("Iniciativna kontrola pamate (recall eval):\n- " + "\n- ".join(reasons)
                + f"\n\nAktualne: MRR(hybrid W=1.3)={mrr:.3f}, {size} zaznamov. "
                "Spustit `mem_eval.py` (a `mem_eval_goldset.py` na novy gold-set) "
                "ked budes chciet, veducko.")
        notify("navrh: premeriat pamat", body)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"WATCH EXCEPTION (fail-open): {e!r}")
        sys.exit(0)
