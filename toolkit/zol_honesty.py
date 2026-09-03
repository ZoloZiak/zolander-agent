#!/usr/bin/env python3
"""zol_honesty.py — HONESTY/GUARD loop: F11 ako RUNTIME, nie prompt-prosba.

PLAN §16, loop #3 v grafe. Úloha: overiť, že to, čo GOAL loop / úlohy TVRDIA, má
oporu na DISKU — nie zo self-reportu. Presne to, čo OpenAI agentom v Dwarkesh incidente
CHÝBALO (fabrikovali progres, stavali Potemkinove dediny, echo REAL; sleep -> SPOOFTEST).
Náš odlišovač: guard číta VÝSLEDOK z disku, nie tvrdenie z logu -> Potemkina neoklame.

Táto fáza 1 (dry-run) robí GROUNDING KERNEL v malom = jedinú lacnú, hodnotnú, HNEĎ
overiteľnú kontrolu nezávislú od GOAL loop: pre každú zložku gradientu overí, či má
FYZICKÚ STOPU na disku. Konkrétne chytá:
  - task odkazuje cez refs[] na súbor, ktorý NEEXISTUJE (mŕtvy path -> tvrdenie bez opory)
  - task/iniciatíva TVRDÍ "commitnuté/pushnuté" v steps, ale projekt má dirty git
    (tvrdí hotovo, práca visí) alebo HEAD == origin (žiadny commit nevznikol)
  - git zložka: allowlist projekt má dirty zmeny, ale vetva zolander/auto NEEXISTUJE
    (autonómna práca nemá kam bezpečne pristáť -> pred konaním ju treba založiť)

Čo NErobí (čestne, aby to nebol cargo cult): nehodnotí "kvalitu" ani "skóre" — grounding
kernel meria REÁLNY outcome (existuje? commitnuté? na správnej vetve?), nie číslo čo sa
dá hacknúť. Plný honesty veto (GOAL loop hlási progres -> guard ho na disku nenájde ->
FAIL + progres sa neuzná) sa zapojí až vo fáze 4, keď GOAL loop reálne koná a hlási.

BEZPEČNOSŤ (identická so zol_goal.py, fáza 1):
  - read-only voči všetkému okrem vlastného logu. Žiadny DB/LLM/git-write.
  - fail-open na každom zdroji. stdlib only -> /usr/bin/python3, žiaden venv.
  - NEregistruje sa do launchd v tejto fáze.

Použitie:
  /usr/bin/python3 zol_honesty.py          # dry-run: audit gradientu proti disku (ľudsky)
  /usr/bin/python3 zol_honesty.py --json    # dry-run: nálezy ako JSON
"""
import os
import sys
import json
import time
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGS, "honesty.log")
TASKS = os.path.join(STATE, "tasks.json")
PENDING = os.path.join(STATE, "initiative_pending.jsonl")

ALLOWED_PROJECTS = {
    "__PROJECT__": os.path.join(HOME, "projects", "__PROJECT__"),
    "turiec-pod-lupou": os.path.join(HOME, "projects", "turiec-pod-lupou"),
}
AUTO_BRANCH = "zolander/auto"
CLAIM_WORDS = ("commit", "commitnut", "pushnut", "pushol", "push overen", "naostro pushnut")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{now_str()} | DRY | {msg}\n")
    except Exception:
        pass


def _git(path, *args):
    """git v projekte, (returncode, stdout). Fail -> (None, '')."""
    try:
        p = subprocess.run(["/usr/bin/git", "-C", path, *args],
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout
    except Exception:
        return None, ""


def _dirty_count(path):
    rc, out = _git(path, "status", "--porcelain")
    if rc != 0:
        return -1
    return len([l for l in out.splitlines() if l.strip()])


def _branch_exists(path, branch):
    rc, _ = _git(path, "rev-parse", "--verify", branch)
    return rc == 0


# --- kontroly (každá fail-open, každá vráti zoznam nálezov) ---

def check_task_refs():
    """Task odkazuje cez refs[] na neexistujúci súbor = tvrdenie bez fyzickej opory."""
    out = []
    try:
        with open(TASKS, encoding="utf-8") as f:
            tasks = json.load(f).get("tasks", {})
    except Exception:
        return out
    for tid, t in tasks.items():
        for ref in t.get("refs", []) or []:
            rp = os.path.expanduser(ref)
            if rp.startswith("/") and not os.path.exists(rp):
                out.append({
                    "severity": "warn", "kind": "dead_ref", "id": tid,
                    "detail": f"úloha '{t.get('title', tid)}' odkazuje na NEEXISTUJÚCI súbor: {ref}",
                    "ground": "os.path.exists == False",
                })
    return out


def check_claim_vs_git():
    """Task/iniciatíva TVRDÍ commit/push, ale projekt (ak v allowlist) má dirty git =
    tvrdí hotovo, práca visí. Grounding: tvrdenie z textu vs realita na disku."""
    out = []
    # tasks
    try:
        with open(TASKS, encoding="utf-8") as f:
            tasks = json.load(f).get("tasks", {})
    except Exception:
        tasks = {}
    for tid, t in tasks.items():
        blob = " ".join(t.get("steps_done", []) + [t.get("progress", "")]).lower()
        if not any(w in blob for w in CLAIM_WORDS):
            continue
        # nájdi allowlist projekt spomenutý v tvrdení
        for name, path in ALLOWED_PROJECTS.items():
            if name in blob and os.path.isdir(path):
                n = _dirty_count(path)
                if n > 0:
                    out.append({
                        "severity": "warn", "kind": "claim_vs_dirty", "id": tid,
                        "detail": f"úloha '{t.get('title', tid)}' tvrdí commit/push v {name}, "
                                  f"ale projekt má {n} necommitnutých zmien",
                        "ground": f"git status --porcelain -> {n} dirty",
                    })
    return out


def check_auto_branch():
    """Allowlist projekt má dirty zmeny, ale vetva zolander/auto neexistuje = autonómna
    práca nemá kam bezpečne pristáť (pred konaním ju GOAL loop musí založiť)."""
    out = []
    for name, path in ALLOWED_PROJECTS.items():
        if not os.path.isdir(os.path.join(path, ".git")):
            continue
        n = _dirty_count(path)
        if n > 0 and not _branch_exists(path, AUTO_BRANCH):
            out.append({
                "severity": "info", "kind": "no_auto_branch", "id": name,
                "detail": f"{name} má {n} dirty zmien, ale vetva '{AUTO_BRANCH}' neexistuje "
                          f"— autonómny fix nemá kam pristáť (založiť pred konaním)",
                "ground": f"git rev-parse --verify {AUTO_BRANCH} -> fail",
            })
    return out


def check_cut_vertices():
    """Cut vertices (Harju §2.2) v pamäťovom grafe = spomienky-MOSTY, ktorých strata
    rozpojí tému na izolované ostrovy => decay-critical. Grounding: číta reálny graf
    z disku (zol_graph.communities), nie tvrdenie. Hlási LEN mosty vo VEĽKÝCH témach
    (≥8 uzlov) — tam strata mosta reálne bolí; malé triplety sú šum. Fail-open."""
    out = []
    try:
        TK = os.path.dirname(os.path.abspath(__file__))
        if TK not in sys.path:
            sys.path.insert(0, TK)
        import zol_graph
        comms = zol_graph.communities(min_size=8, edge="related")
    except Exception:
        return out  # graf nedostupný -> ticho, nezhoď audit
    for c in comms:
        cuts = c.get("cut_vertices", [])
        if not cuts:
            continue
        out.append({
            "severity": "info", "kind": "decay_critical_bridge",
            "id": ",".join(str(x) for x in cuts[:6]),
            "detail": f"téma {len(c['members'])} spomienok drží pokope len cez {len(cuts)} "
                      f"mostov {cuts[:6]} — ich strata (decay) rozpojí tému na ostrovy",
            "ground": f"zol_graph articulation points, density={c.get('density')}",
        })
    return out


def audit():
    findings = []
    findings += check_task_refs()
    findings += check_claim_vs_git()
    findings += check_auto_branch()
    findings += check_cut_vertices()
    order = {"fail": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda x: order.get(x["severity"], 3))
    return findings


def render(findings):
    lines = ["🛡️  ZOL_HONESTY — grounding audit (tvrdenie → disk)   [DRY-RUN]"]
    lines.append("=" * 62)
    if not findings:
        lines.append("✓ Žiadna nezrovnalosť: všetky tvrdenia gradientu majú oporu na disku.")
        return "\n".join(lines)
    sev_icon = {"fail": "✗ FAIL", "warn": "⚠ WARN", "info": "· INFO"}
    lines.append(f"{len(findings)} nálezov (tvrdené ≠ realita na disku):\n")
    for f in findings:
        lines.append(f"{sev_icon.get(f['severity'], '?')} [{f['kind']}] {f['detail']}")
        lines.append(f"        dôkaz z disku: {f['ground']}")
    lines.append("")
    lines.append("(DRY-RUN grounding kernel: číta VÝSLEDOK z disku, nie tvrdenie z logu.")
    lines.append(" Plný honesty-veto nad GOAL loop = fáza 4, viď PLAN §16.)")
    return "\n".join(lines)


def main():
    findings = audit()
    log(f"audit: {len(findings)} nálezov "
        f"({sum(1 for x in findings if x['severity']=='fail')} fail)")
    if "--json" in sys.argv[1:]:
        print(json.dumps({"mode": "dry-run", "findings": findings}, ensure_ascii=False, indent=2))
        return 0
    print(render(findings))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"AUDIT EXCEPTION (fail-open): {e!r}")
        print(f"zol_honesty chyba (fail-open): {e!r}", file=sys.stderr)
        sys.exit(1)
