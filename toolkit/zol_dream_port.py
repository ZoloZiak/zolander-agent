#!/usr/bin/env python3
"""zol_dream_port.py — nočný "sen" port (jeden beh, denne raz).

Port hermes F4 na Windows — poctivo REDUKOVANY (bez LLM):
  1. DECAY       — salience * 0.95 na vsetkych A zaznamoch (jsonl rewrite)
  2. KONSOLIDÁCIA — dnesne A zaznamy zlucine do JEDNEho L1 semantic konceptu
                   (rule-based destilát, nie LLM) + dual zapis s A2A podpisom
  3. BRIEF       — denniky/brief_<datum>.md (statistika, forget-návrhy)

READ-ONLY voči mazaniu: nič NEmaže, len navrhuje (destrukcia az po audit).
Vstup deká im ide do state/dream_last.json. Honesty: konsolidácia NIE je
LLM destilát (hermes-ý baš sag); napise se v brief.
"""
import datetime
import json
import os
import subprocess
import sys
import time

ROOT = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
DENNIKY = os.path.join(ROOT, "denniky")
DECAY = 0.95
FORGET_THRESHOLD = 0.25


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "dream.log"), "a", encoding="utf-8") as f:
        f.write(f"{now()} | {msg}\n")


def dual_remember(text, kind, layer, conf):
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "toolkit", "zol_remember_dual.py")],
        input=json.dumps({"text": text, "kind": kind, "layer": layer,
                          "confidence": conf, "source": "dream"}, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
        cwd=ROOT, timeout=120,
    )
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": (p.stderr or p.stdout)[-200:]}


def decay_a():
    path = os.path.join(STATE, "zol_memory.jsonl")
    if not os.path.exists(path):
        return {"count": 0, "changed": 0, "forget_navrhy": []}
    records = []
    changed = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        old = float(r.get("salience", 0.4))
        r["salience"] = round(old * DECAY, 4)
        if abs(r["salience"] - old) > 1e-9:
            changed += 1
        records.append(r)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    forget = [r["ts"] for r in records if float(r.get("salience", 0.4)) < FORGET_THRESHOLD]
    log(f"decay: {len(records)} zaznamov, zmenenych {changed}, forget-navrhy {len(forget)}")
    return {"count": len(records), "changed": changed, "forget_navrhy": forget}


def consolidate_today():
    path = os.path.join(STATE, "zol_memory.jsonl")
    if not os.path.exists(path):
        return None
    today = datetime.date.today().isoformat()
    eps = []
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(r.get("ts", "")).startswith(today) and r.get("kind") == "episodic" and r.get("layer") == "L0":
            eps.append(str(r.get("text", "")))
    if not eps:
        return None
    head = eps[0][:400]
    concept = (f"[rule-based konsolidacia {today}] dnesnych L0 episodic: {len(eps)}. "
               f"Prvy zapis: {head}")
    out = dual_remember(concept, kind="semantic", layer="L1", confidence=0.7)
    log(f"konsolidacia: {len(eps)} epizod -> L1 (dual ok={out.get('ok')})")
    return out


def write_brief(decay_info, consol_info):
    os.makedirs(DENNIKY, exist_ok=True)
    today = datetime.date.today().isoformat()
    brief_path = os.path.join(DENNIKY, f"brief_{today}.md")
    plan_tail = ""
    planp = os.path.join(STATE, "PLAN.md")
    if os.path.exists(planp):
        plan_tail = open(planp, encoding="utf-8", errors="replace").read()[-1500:]
    lines = [
        f"# Brief {today}",
        "",
        f"- A pamat: **{decay_info.get('count', 0)}** záznamov, decay dotkol {decay_info.get('changed', 0)}",
        f"- Forget-návrhy (salience < {FORGET_THRESHOLD}): **{len(decay_info.get('forget_navrhy', []))}** — NIČ neuene, az po audit",
        f"- Konsolidácia (rule-based, NIE LLM): {'hotova (L1 zapisany)' if consol_info and consol_info.get('ok') else 'dnes žiadne episodic L0'}",
        "",
        "## PLAN chvost",
        "",
        plan_tail,
    ]
    with open(brief_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"brief: {brief_path}")
    return brief_path


def decay_b(factor=0.95):
    """Decay salience aj v B (lorentz) pamati — zol_decay_b.py subprocess."""
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "toolkit", "zol_decay_b.py"),
         f"--factor={factor}"],
        capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
        cwd=ROOT, timeout=300,
    )
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": (p.stderr or p.stdout)[-200:]}


def main():
    os.makedirs(STATE, exist_ok=True)
    decay_info = decay_a()
    decayb_info = decay_b()
    consol_info = consolidate_today() or {"ok": False, "note": "dnes ziadne episodic"}
    brief = write_brief(decay_info, consol_info)
    with open(os.path.join(STATE, "dream_last.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"ts": now(), "decay": decay_info, "decay_b": {
                "ok": bool(decayb_info.get("ok")), "changed": len(decayb_info.get("changed", []))},
             "konsolidacia": {
                "ok": bool(consol_info.get("ok")), "engine": consol_info.get("A_engine"),
            }, "brief": brief},
            f, ensure_ascii=False, indent=2,
        )
    print(json.dumps({"ok": True, "decay": decay_info,
                      "decay_b": {"ok": bool(decayb_info.get("ok")), "changed": len(decayb_info.get("changed", []))},
                      "brief": brief}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
