#!/usr/bin/env python3
"""zol_matrix_digest.py — stupňovaná pamäť konverzácie (roky→mesiace→týždne→dni).

Z archívu (zol_matrix_archive) postaví ČASOVO ODSTUPŇOVANÝ súhrn: čím staršie
správy, tým hrubšie zhrnutie; čím čerstvejšie, tým jemnejšie; posledné doslovne
(to rieši hook, nie tu). Súhrny sa počítajú cez Palantir Opus a CAnevhodneÚ — batch,
NIE pri každom turne. Regeneruje sa len keď v pásme pribudli nové správy
(fingerprint = počet+posledná ts v pásme).

Vrstvy (podľa veku správy, každá správa v práve JEDNEJ):
    roky     : > 365 dní         -> 1 súhrn / rok
    mesiace  : 35–365 dní        -> 1 súhrn / mesiac
    týždne   : 7–35 dní          -> 1 súhrn / ISO-týždeň
    dni      : 1–7 dní           -> 1 súhrn / deň
    (posledných ~15 správ = doslovný tail, dopĺňa hook)

CLI:  python zol_matrix_digest.py build <room_id> [--force]
      python zol_matrix_digest.py show  <room_id>
Modul: from zol_matrix_digest import build_digest, render_digest
"""
import os
import sys
import json
import time
import hashlib
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from zol_matrix_archive import load_archive, sync_room, room_hash  # noqa: E402

DIGEST_DIR = os.path.expanduser("~/projects/zolander/state/matrix_archive")
ZOLO2_TOOLKIT = os.path.expanduser("~/projects/zolo2.0/toolkit")

DAY = 86400.0
NOW = None  # nastaví sa v build (testovateľné)


def _now():
    return NOW if NOW is not None else time.time()


def _digest_path(room_id):
    return os.path.join(DIGEST_DIR, room_hash(room_id) + ".digest.json")


def _palantir_chat(prompt, max_tokens=700):
    """Zavolá Palantir Opus cez zolo2.0 klienta. Vráti text alebo ''."""
    if ZOLO2_TOOLKIT not in sys.path:
        sys.path.insert(0, ZOLO2_TOOLKIT)
    try:
        from palantir_client import chat
    except Exception as exc:
        return f"[digest: palantir_client nedostupný: {exc}]"
    try:
        return (chat(prompt, model="opus", max_tokens=max_tokens) or "").strip()
    except Exception as exc:
        return f"[digest: LLM volanie zlyhalo: {exc}]"


def _fmt_msgs(rows, cap=None):
    """Riadky správ -> text pre prompt. cap = max správ (najnovšie)."""
    if cap and len(rows) > cap:
        rows = rows[-cap:]
    out = []
    for r in rows:
        who = "Zolo/bot" if r["who"] == "self" else "kontakt"
        dt = datetime.datetime.utcfromtimestamp(r["ts"] / 1000).strftime("%Y-%m-%d %H:%M")
        out.append(f"[{dt}] {who}: {r['body']}")
    return "\n".join(out)


def _bucket(rows, now):
    """Rozdelí správy do vekových pásiem a kľúčov v pásme."""
    years, months, weeks, days = {}, {}, {}, {}
    for r in rows:
        age = now - (r["ts"] / 1000.0)
        dt = datetime.datetime.utcfromtimestamp(r["ts"] / 1000)
        if age > 365 * DAY:
            years.setdefault(dt.strftime("%Y"), []).append(r)
        elif age > 35 * DAY:
            months.setdefault(dt.strftime("%Y-%m"), []).append(r)
        elif age > 7 * DAY:
            iso = dt.isocalendar()
            weeks.setdefault(f"{iso[0]}-W{iso[1]:02d}", []).append(r)
        elif age > 1 * DAY:
            days.setdefault(dt.strftime("%Y-%m-%d"), []).append(r)
        # < 1 deň: to je vec hooku (živý tail), sem nie
    return years, months, weeks, days


def _fingerprint(rows):
    return f"{len(rows)}:{rows[-1]['ts'] if rows else 0}"


_PROMPTS = {
    "years": ("Toto je konverzácia medzi Zolom (a jeho AI parťákom Zolanderom, "
              "spolu vystupujú ako 'Zolo/bot') a kontaktom, za CELÝ ROK {key}. "
              "Zhrň v 2–3 vetách po slovensky: kto ten kontakt pre Zola je, o čom "
              "sa ten rok najviac bavili, dôležité udalosti/rozhodnutia. Bez omáčky."),
    "months": ("Konverzácia Zolo/bot ↔ kontakt za MESIAC {key}. Zhrň v 2–3 vetách "
               "po slovensky: hlavné témy, čo sa udialo, nálada vzťahu. Stručne."),
    "weeks": ("Konverzácia Zolo/bot ↔ kontakt za TÝŽDEŇ {key}. Zhrň v 1–2 vetách "
              "po slovensky: o čom sa bavili, čo je dôležité si pamätať."),
    "days": ("Konverzácia Zolo/bot ↔ kontakt za DEŇ {key}. Zhrň v 1 vete po "
             "slovensky: čo podstatné sa v ten deň riešilo."),
}


def build_digest(room_id, force=False, now=None):
    """Zosúladí archív, prepočíta zmenené pásma, uloží digest. Vráti dict."""
    global NOW
    NOW = now
    n = _now()

    rows = load_archive(room_id)
    if not rows:
        return {"error": "archív prázdny — spusti sync"}

    years, months, weeks, days = _bucket(rows, n)
    layers = [("years", years), ("months", months),
              ("weeks", weeks), ("days", days)]

    path = _digest_path(room_id)
    old = {}
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding="utf-8"))
        except Exception:
            old = {}
    old_layers = old.get("layers", {})

    result = {"room_id": room_id, "built_at": n, "layers": {}}
    llm_calls = 0
    for name, buckets in layers:
        result["layers"][name] = {}
        old_l = old_layers.get(name, {})
        for key in sorted(buckets):
            brows = buckets[key]
            fp = _fingerprint(brows)
            prev = old_l.get(key)
            # cache hit: rovnaký fingerprint -> neregeneruj
            if not force and prev and prev.get("fp") == fp:
                result["layers"][name][key] = prev
                continue
            prompt = _PROMPTS[name].format(key=key) + "\n\n" + _fmt_msgs(brows, cap=200)
            summary = _palantir_chat(prompt, max_tokens=400)
            llm_calls += 1
            result["layers"][name][key] = {
                "fp": fp, "n": len(brows), "summary": summary,
            }

    result["llm_calls"] = llm_calls
    os.makedirs(DIGEST_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    NOW = None
    return result


def render_digest(room_id):
    """Digest -> čitateľný text pre kontext (od najstaršieho po najnovšie)."""
    path = _digest_path(room_id)
    if not os.path.exists(path):
        return ""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return ""
    layers = d.get("layers", {})
    parts = []
    labels = [("years", "── ZA ROKY ──"), ("months", "── ZA MESIACE ──"),
              ("weeks", "── ZA TÝŽDNE ──"), ("days", "── ZA DNI ──")]
    for name, label in labels:
        block = layers.get(name, {})
        if not block:
            continue
        lines = [label]
        for key in sorted(block):
            s = block[key].get("summary", "").strip()
            if s and not s.startswith("[digest:"):
                lines.append(f"• {key}: {s}")
        if len(lines) > 1:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: zol_matrix_digest.py build|show <room_id> [--force]", file=sys.stderr)
        sys.exit(2)
    cmd, room = sys.argv[1], sys.argv[2]
    if cmd == "build":
        sync_room(room)
        r = build_digest(room, force="--force" in sys.argv)
        print(f"digest built: {r.get('llm_calls','?')} LLM volaní")
        print(render_digest(room))
    elif cmd == "show":
        print(render_digest(room))
