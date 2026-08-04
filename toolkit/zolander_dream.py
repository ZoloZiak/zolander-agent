#!/usr/bin/env python3
"""zolander_dream.py — F4 nočný "sen" (one-shot, launchd raz denne ~3:00).

Fázy:
  1. DECAY      — prepočíta salience (volá zol_mem.py decay), dostane forget/promote návrhy
  2. KONSOLIDÁCIA — dnešné L0 epizódy -> gpt-mini destilát -> uloží ako nový L1 semantic
                    koncept (lokálne; MCP consolidate_memories je mŕtve = embed engine off)
  3. RANNÝ BRIEF — denniky/brief_<dátum>.md: čo sa dialo, nové L1, NÁVRHY forget

READ-ONLY voči DB: NIČ nemaže (P2/P3 — deštrukcia až po rannom audite od vedúcka).
Beží pod /usr/bin/python3 (palantir_client = stdlib urllib). zol_mem.py = subprocess.
"""
import os
import sys
import json
import time
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
DENNIKY = os.path.join(ROOT, "denniky")
LOGS = os.path.join(ROOT, "logs")
IDX = os.path.join(STATE, "mem_index.jsonl")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")
DREAMLOG = os.path.join(LOGS, "dream.log")
VPY = "/Users/__USER__/.local/share/uv/tools/vmlx/bin/python"

sys.path.insert(0, os.path.join(HOME, "zolo2.0", "toolkit"))  # TODO: point to your palantir_client.py dir


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(DREAMLOG, "a") as f:
        f.write(f"{now()} | {msg}\n")


def run_decay():
    """Zavola zol_mem.py decay, vrati dict {forget, promote, kept} alebo {}."""
    p = subprocess.run([sys.executable, ZOL_MEM, "decay"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"decay zlyhal: {p.stderr[-300:]}")
        return {}
    try:
        out = json.loads(p.stdout.strip())
        return out.get("suggestions", out)  # decay vracia bud suggestions alebo priamo
    except Exception:
        return {}


def load_index():
    if not os.path.exists(IDX):
        return []
    rows = []
    for line in open(IDX):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def todays_episodes(rows):
    today = datetime.date.today().isoformat()
    return [r for r in rows if r.get("layer") == "L0" and r.get("ts", "").startswith(today)]


def consolidate(episodes):
    """gpt-mini destilát dnešných epizód -> nový L1 semantic koncept. Vráti text alebo None."""
    if len(episodes) < 2:
        return None  # netreba konsolidovať jednu epizódu
    try:
        from palantir_client import chat
    except Exception as e:
        log(f"palantir_client import zlyhal: {e!r}")
        return None
    joined = "\n".join(f"- {e.get('text', '')}" for e in episodes)
    system = ("Si Zolander, pamäťový konsolidátor. Z epizód jedného dňa vydestiluj "
              "1-2 vety trvalého poznatku (semantic memory) po slovensky. Len fakt/"
              "vzorec, žiadny dátum, žiadna omáčka. Ak niet čo destilovať, napíš NIC.")
    prompt = f"Dnešné epizódy:\n{joined}\n\nDestilát (1-2 vety, alebo NIC):"
    try:
        txt = chat(prompt, model="gpt-mini", max_tokens=200, system=system).strip()
    except Exception as e:
        log(f"chat zlyhal: {e!r}")
        return None
    if not txt or txt.upper().startswith("NIC"):
        return None
    return txt


def remember_l1(text):
    """Uloží destilát ako L1 semantic cez zol_mem.py remember."""
    payload = json.dumps({"text": text, "kind": "semantic", "layer": "L1",
                          "salience": 0.75, "confidence": 0.8,
                          "source": "loop", "project": "zolander"})
    p = subprocess.run([VPY, ZOL_MEM, "remember"], input=payload,
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"remember L1 zlyhal: {p.stderr[-300:]}")
        return None
    try:
        return json.loads(p.stdout.strip()).get("remembered")
    except Exception:
        return None


def write_brief(decay_res, episodes, distilled, new_id):
    day = datetime.date.today().isoformat()
    path = os.path.join(DENNIKY, f"brief_{day}.md")
    os.makedirs(DENNIKY, exist_ok=True)
    forget = decay_res.get("forget", []) if isinstance(decay_res, dict) else []
    with open(path, "w") as f:
        f.write(f"# Ranný brief — {day}\n\n")
        f.write(f"*Sen: {now()}*\n\n")
        f.write(f"## Včerajšok\n- L0 epizód: {len(episodes)}\n")
        if distilled:
            f.write(f"\n## Nový L1 koncept (id={new_id})\n> {distilled}\n")
        else:
            f.write("\n## Konsolidácia\n- nič nové na destiláciu\n")
        f.write("\n## NÁVRHY na zabudnutie (rozhodni ty — nič som nezmazal)\n")
        if forget:
            for fid in forget:
                f.write(f"- [ ] id={fid} — nízka salience, zvážiť forget\n")
        else:
            f.write("- žiadne\n")
        f.write("\n---\n*Vedúcko, nič deštruktívne som sám nespravil. Čakám na tvoj audit.*\n")
    return path


def dream():
    decay_res = run_decay()
    rows = load_index()
    episodes = todays_episodes(rows)
    distilled = consolidate(episodes)
    new_id = remember_l1(distilled) if distilled else None
    brief = write_brief(decay_res, episodes, distilled, new_id)
    log(f"sen OK | epizod={len(episodes)} | novy_L1={new_id} | brief={os.path.basename(brief)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(dream())
    except Exception as e:
        log(f"DREAM EXCEPTION: {e!r}")
        sys.exit(1)
