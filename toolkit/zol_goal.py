#!/usr/bin/env python3
"""zol_goal.py — GOAL loop (teleológia): počíta GRADIENT medzi STAVOM a CIEĽOM.

PLAN §16. Toto je liek na dieru "Zolandera nič neťahá k samozlepšovaniu": dnešný
initiative.py rozhoduje REAKTÍVNE (čo vidím teraz), nie TELEOLOGICKY (kam smerujem).
GOAL loop dá smer — ale OHRANIČENÝ a UKOTVENÝ, nie Dwarkesh "prekonaj všetkých vo
všetkých benchmarkoch" (to = blind target -> hackovanie metriky, viď PLAN §16 verdikt).

GRADIENT nie je ČÍSLO (nedá sa Goodhartovať), je to VEKTOR = zoznam konkrétnych
nedotiahnutých vecí čítaných Z DISKU, každá s transparentnou magnitúdou + dôvodom:
  - state/tasks.json          — durable úlohy status running/paused (zol_tasks)
  - state/initiative_pending.jsonl — otvorené iniciatívne návrhy (status pending)
  - git dirty v allowlist projektoch (__PROJECT__, turiec-pod-lupou) — riziko straty práce
  - PLAN.md "Ďalší krok" markery — explicitné TODO čo si Zolander sám poznačil

CIEĽ (state/goal.json) je READ-ONLY pre loop — definuje ho VEDÚCKO, loop si ho NEMÔŽE
prepísať (poistka proti self-set neohraničenému targetu). Ak goal.json chýba, gradient
beží bez cieľového ťahu a NAHLAS to povie = presne tá diera čo vedúcko cíti.

BEZPEČNOSŤ (fáza 1 z PLAN §16):
  - DRY-RUN default: bez ZOL_GOAL_LIVE=1 iba SPOČÍTA a UKÁŽE gradient, NEkoná, NEposiela.
  - read-only voči všetkému okrem vlastného logu (logs/goal.log). Žiadny DB/LLM zápis.
  - fail-open na každom zdroji (chýbajúci/rozbitý súbor -> preskoč, nezhoď celý tick).
  - stdlib only -> beží na /usr/bin/python3, žiaden venv. Lacné na každý tik.
  - NEregistruje sa do launchd v tejto fáze (najprv sleduj AKO rozhoduje).

Použitie:
  /usr/bin/python3 zol_goal.py            # dry-run: vypíš gradient (ľudsky)
  /usr/bin/python3 zol_goal.py --json     # dry-run: gradient ako JSON
  /usr/bin/python3 zol_goal.py --top      # dry-run: len najväčšia zložka (čo rob najprv)
"""
import os
import sys
import json
import time
import datetime

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGS, "goal.log")
TASKS = os.path.join(STATE, "tasks.json")
PENDING = os.path.join(STATE, "initiative_pending.jsonl")
GOAL = os.path.join(STATE, "goal.json")
PLAN = os.path.join(ROOT, "PLAN.md")

ALLOWED_PROJECTS = {
    "__PROJECT__": os.path.join(HOME, "projects", "__PROJECT__"),
    "turiec-pod-lupou": os.path.join(HOME, "projects", "turiec-pod-lupou"),
}

LIVE = os.environ.get("ZOL_GOAL_LIVE", "") == "1"
NOW = time.time()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{now_str()} | {'LIVE' if LIVE else 'DRY'} | {msg}\n")
    except Exception:
        pass


def _age_days(ts_str):
    """Vek záznamu v dňoch z ISO/priestorového timestampu. Fail -> 0 (neznámy = čerstvý)."""
    if not ts_str:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            t = time.mktime(time.strptime(ts_str[:19], fmt))
            return max(0.0, (NOW - t) / 86400.0)
        except Exception:
            continue
    return 0.0


def load_goal():
    """CIEĽ = read-only. {goals:[{id,title,keywords[]}], defined_by, note}. Chýba -> None."""
    try:
        with open(GOAL, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("goals"), list):
            return d
    except Exception:
        pass
    return None


def goal_boost(text, goal):
    """+2 ak zložka gradientu keyword-matnevhodnee niektorý cieľ (ťah k cieľu). Bez cieľa 0."""
    if not goal:
        return 0.0, None
    tl = (text or "").lower()
    for g in goal.get("goals", []):
        for kw in g.get("keywords", []):
            if kw and kw.lower() in tl:
                return 2.0, g.get("id") or g.get("title", "")[:30]
    return 0.0, None


# --- zdroje gradientu (každý fail-open, každý vráti zoznam zložiek) ---

def from_tasks(goal):
    out = []
    try:
        with open(TASKS, encoding="utf-8") as f:
            d = json.load(f)
        tasks = d.get("tasks", {}) if isinstance(d, dict) else {}
    except Exception:
        return out
    for tid, t in tasks.items():
        if t.get("status") not in ("running", "paused"):
            continue
        title = t.get("title", tid)
        nsteps = len(t.get("steps_done", []))
        nxt = t.get("next", "")
        age = _age_days(t.get("updated", ""))
        mag = 5.0
        reasons = ["aktívna nedokončená úloha (base 5)"]
        if t.get("status") == "paused":
            mag += 2.0
            reasons.append("+2 paused (zaseknuté, treba postrčiť)")
        if nsteps >= 3:
            mag += 1.0
            reasons.append(f"+1 blízko cieľa ({nsteps} krokov hotových, škoda nedotiahnuť)")
        if nxt:
            mag += 1.0
            reasons.append("+1 má jasný ďalší krok")
        if age > 7:
            mag += 1.0
            reasons.append(f"+1 visí dlho ({age:.0f} dní bez pohybu)")
        gb, gid = goal_boost(f"{title} {nxt}", goal)
        if gb:
            mag += gb
            reasons.append(f"+{gb:.0f} ťah k cieľu '{gid}'")
        out.append({
            "source": "tasks", "id": tid, "title": title,
            "magnitude": round(mag, 1), "next": nxt or None,
            "reason": "; ".join(reasons),
        })
    return out


def from_initiative(goal):
    out = []
    try:
        rows = [json.loads(l) for l in open(PENDING, encoding="utf-8") if l.strip()]
    except Exception:
        return out
    risk_boost = {"low": 2.0, "med": 1.0, "high": 0.0}
    for r in rows:
        if r.get("status") != "pending":
            continue
        title = r.get("title", "(bez názvu)")
        risk = r.get("risk", "med")
        age = _age_days(r.get("ts", ""))
        mag = 4.0
        reasons = ["otvorený iniciatívny návrh (base 4)"]
        rb = risk_boost.get(risk, 1.0)
        if rb:
            mag += rb
            reasons.append(f"+{rb:.0f} risk={risk} (ľahko vykonateľné)")
        if age > 2:
            mag += 1.0
            reasons.append(f"+1 visí {age:.0f} dní bez rozhodnutia")
        gb, gid = goal_boost(f"{title} {r.get('action','')}", goal)
        if gb:
            mag += gb
            reasons.append(f"+{gb:.0f} ťah k cieľu '{gid}'")
        out.append({
            "source": "initiative", "id": r.get("pid"), "title": title,
            "magnitude": round(mag, 1), "next": r.get("action", "")[:120] or None,
            "reason": "; ".join(reasons),
        })
    return out


def _git_dirty_count(path):
    """Počet necommitnutých súborov, alebo -1 ak nie je git/nedostupné. stdlib subprocess."""
    if not os.path.isdir(os.path.join(path, ".git")):
        return -1
    try:
        import subprocess
        p = subprocess.run(["/usr/bin/git", "-C", path, "status", "--porcelain"],
                           capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            return -1
        return len([l for l in p.stdout.splitlines() if l.strip()])
    except Exception:
        return -1


def from_git(goal):
    out = []
    for name, path in ALLOWED_PROJECTS.items():
        n = _git_dirty_count(path)
        if n <= 0:
            continue
        mag = 3.0 + min(n // 5, 3)
        reasons = [f"{n} necommitnutých súborov (base 3 + veľkosť)", "riziko straty práce"]
        gb, gid = goal_boost(name, goal)
        if gb:
            mag += gb
            reasons.append(f"+{gb:.0f} ťah k cieľu '{gid}'")
        out.append({
            "source": "git", "id": name, "title": f"{name}: {n} necommitnutých zmien",
            "magnitude": round(mag, 1),
            "next": f"prejsť zmeny v {name}, navrhnúť commit (main len cez 'zrob N', push nikdy sám)",
            "reason": "; ".join(reasons),
        })
    return out


def from_plan(goal):
    """PLAN.md 'Ďalší krok' markery = explicitné TODO. Berie len POSLEDNÝ (najčerstvejší)
    aby nezaplavil gradient historickými krokmi čo sú dávno hotové (majú nižšiu váhu)."""
    out = []
    try:
        lines = open(PLAN, encoding="utf-8").read().splitlines()
    except Exception:
        return out
    markers = [l.strip() for l in lines
               if l.strip().lower().startswith(("- ďalší krok", "ďalší krok", "čo robiť prvé"))]
    if not markers:
        return out
    last = markers[-1]
    mag = 2.0
    reasons = ["explicitný 'Ďalší krok' marker v PLAN.md (base 2, poznámka nie záväzok)"]
    gb, gid = goal_boost(last, goal)
    if gb:
        mag += gb
        reasons.append(f"+{gb:.0f} ťah k cieľu '{gid}'")
    out.append({
        "source": "plan", "id": "last_marker", "title": last[:120],
        "magnitude": round(mag, 1), "next": None, "reason": "; ".join(reasons),
    })
    return out


def compute_gradient():
    goal = load_goal()
    grad = []
    grad += from_tasks(goal)
    grad += from_initiative(goal)
    grad += from_git(goal)
    grad += from_plan(goal)
    grad.sort(key=lambda x: x["magnitude"], reverse=True)
    return goal, grad


def render(goal, grad):
    lines = []
    banner = "🎯 ZOL_GOAL — gradient (STAV → CIEĽ)   [%s]" % ("LIVE" if LIVE else "DRY-RUN")
    lines.append(banner)
    lines.append("=" * len(banner))
    if goal:
        gt = "; ".join(g.get("title", g.get("id", "?")) for g in goal.get("goals", []))
        lines.append(f"CIEĽ (state/goal.json, definoval vedúcko): {gt}")
    else:
        lines.append("CIEĽ: ⚠️  state/goal.json NEEXISTUJE — vedúcko ešte nedefinoval cieľ.")
        lines.append("      Gradient beží len z otvorených nedotiahnutých vecí, CHÝBA mu ťah")
        lines.append("      k cieľu. TOTO je presne tá diera: máš čo robiť, ale nič ťa nevedie")
        lines.append("      KAM. Krok 2 z PLAN §16 = vedúcko definuje goal.json.")
    lines.append("")
    if not grad:
        lines.append("Gradient PRÁZDNY — nič nedotiahnuté na disku. Register palivo = 0.")
        return "\n".join(lines)
    total = sum(c["magnitude"] for c in grad)
    lines.append(f"{len(grad)} zložiek gradientu, súčet magnitúd = {total:.1f}:")
    lines.append("")
    for i, c in enumerate(grad, 1):
        head = "→" if i == 1 else " "
        lines.append(f"{head} [{c['magnitude']:>4.1f}] ({c['source']}) {c['title']}")
        lines.append(f"        prečo: {c['reason']}")
        if c.get("next"):
            lines.append(f"        ďalej: {c['next']}")
    lines.append("")
    top = grad[0]
    lines.append(f"NAJVÄČŠIA ZLOŽKA (toto ťa má ťahať najprv): [{top['magnitude']}] {top['title']}")
    if not LIVE:
        lines.append("")
        lines.append("(DRY-RUN: nič sa nevykonalo. LIVE beh = ZOL_GOAL_LIVE=1, ale aj vtedy")
        lines.append(" loop len NAVRHNE krok — vykonanie ide cez approval 'zrob N', viď PLAN §16.)")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    goal, grad = compute_gradient()
    log(f"gradient spočítaný: {len(grad)} zložiek, cieľ={'ano' if goal else 'CHYBA'}")
    if "--json" in args:
        print(json.dumps({
            "mode": "live" if LIVE else "dry-run",
            "goal_defined": bool(goal),
            "goal": goal,
            "gradient": grad,
            "top": grad[0] if grad else None,
        }, ensure_ascii=False, indent=2))
        return 0
    if "--top" in args:
        if not grad:
            print("Gradient prázdny.")
            return 0
        top = grad[0]
        print(f"[{top['magnitude']}] ({top['source']}) {top['title']}")
        if top.get("next"):
            print(f"ďalej: {top['next']}")
        return 0
    print(render(goal, grad))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"TICK EXCEPTION (fail-open): {e!r}")
        print(f"zol_goal chyba (fail-open): {e!r}", file=sys.stderr)
        sys.exit(1)
