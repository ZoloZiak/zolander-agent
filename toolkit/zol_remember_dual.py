# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""zol_remember_dual.py — zapis jednej spomienky do OBOCH pamati naraz (A/B test).

A = mem_light.py  (lexikalna L0, state/zol_memory.jsonl)
B = zol_mem_text.py (HyperspaceDB lorentz server-side embedding, kolekcia zol_mem)

Rovnaky obsah, rovnake metadata, rozne enginy — aby dual recall (A vs B v
injekte) testoval porovnatelne data, nie rozne. Id pre A je ts, id pre B je
monotonicky int (state/mem_next_id.txt). Fail-open: jedna strana moze padnut,
potom vrati ok:false pre tu stranu a zachova druhu — hlasitel pravdivo.

Obsah je az po zapis PODPISANY Ed25519 identitou (a2a.py, fingerprint
9ae2fbc6...): jeden podpis pre obe pamati (zaznam nesie sig, sig_from_fp,
sig_ts). Rie STATUS integritu: toto si zapisal Zolander s tymto klucom
a obsah nebol po zmeny zmeneny.

Pouzitie:
  python toolkit/zol_remember_dual.py --file payload.json   # preferované (UTF-8 čistý)
  python toolkit/zol_remember_dual.py < stdin.json          # pozor: ASCII mangle v PS 5.1
  stdin JSON {text, [kind=episodic, layer=L0, confidence=0.6, source, project]}
  python toolkit/zol_remember_dual.py verify [--limit N]    # over podpisy v oboch pamatiach

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

# stdout/stderr čisto UTF-8: rodičovské procesy dekódujú s encoding="utf-8";
# bez reconfigure tento proces píše cp1250 (locale) a reader-thread v
# rodičovi padá na nevalidných bajtoch -> výpis príde prázdny.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — fallback: bez reconfigure
        pass

KINDS = {"episodic", "semantic", "procedural", "identity"}
LAYERS = {"L0", "L1", "L2", "L3"}


def make_body(text, kind, layer, conf):
    """Presny kanonicky tvar podpisaneho tela (rovnaky pri sign a pri verify)."""
    return json.dumps(
        {"text": text, "kind": kind, "layer": layer, "confidence": conf},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )


def _a_records(limit):
    path = os.path.join(ROOT, "state", "zol_memory.jsonl")
    if not os.path.exists(path):
        return []
    lines = open(path, encoding="utf-8").read().splitlines()
    out = []
    for line in reversed(lines):
        if len(out) >= limit:
            break
        try:
            o = json.loads(line)
            if isinstance(o, dict):
                out.append(o)
        except json.JSONDecodeError:
            continue
    return out


def _b_records(limit):
    env = dict(os.environ, ZOLANDER_ROOT=ROOT,
               HS_SDK_PATH=os.environ.get("HS_SDK_PATH") or os.path.normpath(
                   os.path.expanduser(r"~\hyperspace-db\sdks\python")))
    sys.path.insert(0, env["HS_SDK_PATH"])
    from hyperspace.client import HyperspaceClient  # noqa: E402
    c = HyperspaceClient(host=env.get("HYPERSPACE_HOST", "localhost:50051"),
                         api_key=env.get("HYPERSPACE_API_KEY", "I_LOVE_HYPERSPACEDB"))
    stats = c.get_collection_stats("zol_mem")
    count = int(stats.get("count", 0))
    n = min(count, max(limit, 400))
    pts = c.scroll(limit=n, collection="zol_mem") or []
    out = []
    for p in pts:
        md = p.get("metadata") or {}
        if md.get("sig"):
            out.append({"id": p.get("id"), "metadata": md})
    return out


def cmd_verify(argv) -> int:
    limit = int(os.environ.get("ZOL_VERIFY_LIMIT") or "10")
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    sys.path.insert(0, TOOLKIT)
    import a2a  # noqa: E402

    def check(fp, ts, body, sig):
        msg = {"from_fp": fp, "ts": ts, "body": body, "sig": sig}
        ok, why = a2a.verify_msg(msg)
        return {"sig_ok": bool(ok), "why": why}

    a_rows, b_rows = [], []
    for rec in _a_records(limit)[:limit]:
        if not rec.get("sig"):
            a_rows.append({"engine": "A", "id": rec.get("ts"), "unsigned": True,
                           "text_head": str(rec.get("text", ""))[:80]})
            continue
        try:
            body = make_body(rec["text"], rec["kind"], rec["layer"], float(rec["confidence"]))
        except (KeyError, ValueError, TypeError) as e:
            a_rows.append({"engine": "A", "id": rec.get("ts"), "sig_ok": False, "why": f"zaznam bez pola: {e}"})
            continue
        r = check(rec["sig_from_fp"], rec["sig_ts"], body, rec["sig"])
        a_rows.append({"engine": "A", "id": rec.get("ts"), **r, "text_head": str(rec.get("text", ""))[:80]})

    try:
        b_all = _b_records(limit)
    except Exception as e:  # noqa: BLE001 — verify hlasit, nie padat
        b_rows.append({"engine": "B", "sig_ok": False, "why": f"server nedostupny: {e}"})
        b_all = []
    for p in b_all[:limit]:
        md = p["metadata"]
        try:
            body = make_body(md["text"], md["kind"], md["layer"], float(md["confidence"]))
        except (KeyError, ValueError, TypeError) as e:
            b_rows.append({"engine": "B", "id": p.get("id"), "sig_ok": False, "why": f"zaznam bez pola: {e}"})
            continue
        r = check(md.get("sig_from_fp"), md.get("sig_ts"), body, md.get("sig"))
        b_rows.append({"engine": "B", "id": p.get("id"), **r, "text_head": str(md.get("text", ""))[:80]})

    all_rows = a_rows + b_rows
    signed = [r for r in all_rows if r.get("sig_ok") is not None or r.get("unsigned") is True]
    ok_n = sum(1 for r in all_rows if r.get("sig_ok") is True)
    unsigned = sum(1 for r in all_rows if r.get("unsigned"))
    bad = [r for r in all_rows if r.get("sig_ok") is False]

    out = {
        "ok": len(bad) == 0,
        "mode": "verify-dual",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "overene": ok_n,
        "nepodpisane": unsigned,
        "zlyhale": len(bad),
        "records": all_rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if len(bad) == 0 and unsigned == 0 else (0 if len(bad) == 0 else 1)


def main(argv) -> int:
    if argv and argv[0] == "verify":
        return cmd_verify(argv[1:])

    if "--file" in argv:
        # Zolander hojne pouziva PowerShell 5.1, ktory nativnym stdin posiela
        # ASCII ($OutputEncoding default) a DAO diakritiku. Súbor čítaný
        # pythonom s encoding="utf-8" je nevyhnutný pre čistý zápis pamätí.
        path = argv[argv.index("--file") + 1]
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            print(json.dumps({"ok": False, "error": f"nie je možné čítať --file {path}: {e}"}, ensure_ascii=False))
            return 2
    else:
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

    # A2A A2A podpis jeden pre obe pamati (identita aj integrita obsahu).
    sys.path.insert(0, TOOLKIT)
    import a2a  # noqa: E402
    body = json.dumps(
        {"text": text, "kind": kind, "layer": layer, "confidence": conf},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    msg = a2a.sign_body(body)
    sig = msg["sig"]

    env = dict(os.environ, ZOLANDER_ROOT=ROOT)
    # Detské procesy bez PYTHONUTF8=1 čítajú stdin a píšu stdout s LOCALE
    # encodingom (cp1250 tu) -> diakritika sa poškodí, resp. vzniknú
    # \udcxx surrogáty, ktoré protobuf zamietne. Vynútime UTF-8 obojsmerne.
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
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

    extra = {"members": str(obj.get("members") or ""), "members_hash": str(obj.get("members_hash") or "")}
    payload = json.dumps(
        {"text": text, "kind": kind, "layer": layer, "confidence": conf,
         "source": source, "project": project, "sig": sig,
         "from_fp": msg["from_fp"], "ts_signed": msg["ts"], **extra},
        ensure_ascii=False,
    )

    a_args = [os.path.join(TOOLKIT, "mem_light.py"), "remember", f"--text={text}", f"--kind={kind}",
              f"--layer={layer}", f"--confidence={conf}", f"--source={source}", f"--project={project}",
              f"--sig={sig}", f"--from_fp={msg['from_fp']}", f"--ts_signed={msg['ts']}"]
    if extra["members_hash"]:
        a_args += [f"--members={extra['members']}", f"--members_hash={extra['members_hash']}"]
    a = child(a_args)
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
    code = main(sys.argv[1:])
    sys.exit(code)
