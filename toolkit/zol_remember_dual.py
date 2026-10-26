#!/usr/bin/env python3
"""zol_remember_dual.py — zapis jednej spomienky do OBOCH pamati naraz (A/B test).

A = mem_light.py  (lexikalna L0, state/zol_memory.jsonl)
B = zol_mem_text.py (HyperspaceDB lorentz server-side embedding, kolekcia zol_mem)

Rovnaky obsah, rovnake metadata, rozne enginy — aby dual recall (A vs B v
injekte) testoval porovnatelne data, nie rozne. Id pre A je ts, id pre B je
monotonicky int (state/mem_next_id.txt). Fail-openNie: jedna strana moze padnut,
potom vrati ok:false pre tu stranu a zachova druhu — hlasiteľ pravdivo.

Pouzitie:
  python toolkit/zol_remember_dual.py < stdin.json
  stdin JSON {text, [kind=episodic, layer=L0, confidence=0.6, source, project]}

Vystup JSON na stdout: {"ok": ..., "A": {...}, "B": {...}}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

TOOLKIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLKIT)

KINDS = {"episodic", "semantic", "procedural", "identity"}
LAYERS = {"L0", "L1", "L2", "L3"}


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"ok": False, "error": "ocakavam JSON na stdin — prazdny vstup"}, ensure_ascii=False))
        return 2
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"nevalidny JSON: {e}"}, ensure_ascii=False))
        return 2

    text = str(obj.get("text", "")).strip()
    if not text:
        print(json.dumps({"ok": False, "error": "text nesmie byt prazdny"}, ensure_ascii=False))
        return 2
    kind = obj.get("kind", "episodic")
    layer = obj.get("layer", "L0")
    conf = float(obj.get("confidence", 0.6))
    if kind not in KINDS:
        print(json.dumps({"ok": False, "error": f"kind musi byt z {sorted(KINDS)}"}, ensure_ascii=False))
        return 2
    if layer not in LAYERS:
        print(json.dumps({"ok": False, "error": f"layer musi byt z {sorted(LAYERS)}"}, ensure_ascii=False))
        return 2
    if not 0.0 <= conf <= 1.0:
        print(json.dumps({"ok": False, "error": "confidence musi byt 0..1"}, ensure_ascii=False))
        return 2

    source = str(obj.get("source", "session"))
    project = str(obj.get("project", ""))

    env = dict(os.environ, ZOLANDER_ROOT=ROOT)
    env.setdefault("HS_SDK_PATH", os.path.normpath(os.path.expanduser(r"~\hyperspace-db\sdks\python")))
    env.setdefault("HYPERSPACE_HOST", "localhost:50051")
    env.setdefault("HYPERSPACE_API_KEY", "I_LOVE_HYPERSPACEDB")

    def child(args: list[str], stdin_payload: str | None = None) -> dict:
        try:
            p = subprocess.run(
                [sys.executable, args[0], *args[1:]],
                input=stdin_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=ROOT,
                timeout=60,
            )
            if p.returncode == 0:
                try:
                    return json.loads(p.stdout or "{}")
                except json.JSONDecodeError:
                    return {"ok": False, "error": "nevalidny JSON vystup childu", "raw": p.stdout[-300:]}
            return {"ok": False, "error": f"child exit {p.returncode}: {(p.stderr or '').strip()[-300:]}"}
        except Exception as e:  # noqa: BLE001 — hlasim co narazilo, nepadam
            return {"ok": False, "error": str(e)}

    payload = json.dumps(
        {"text": text, "kind": kind, "layer": layer, "confidence": conf, "source": source, "project": project},
        ensure_ascii=False,
    )

    a = child([os.path.join(TOOLKIT, "mem_light.py"), "remember", f"--text={text}", f"--kind={kind}",
               f"--layer={layer}", f"--confidence={conf}", f"--source={source}", f"--project={project}"])
    b = child([os.path.join(TOOLKIT, "zol_mem_text.py"), "remember"], stdin_payload=payload)

    out = {
        "ok": bool(a.get("ok") and b.get("ok")),
        "mode": "remember-dual",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "A_engine": "light-lexical-v1",
        "B_engine": "lorentz-server-v1",
        "A": a,
        "B": b,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    code = main()
    sys.exit(code)
