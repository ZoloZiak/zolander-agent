#!/usr/bin/env python3
"""hook_verify.py — pre-finish zamok pre Zolandera (Hermes hook `pre_verify`).

DVE VRSTVY:
  1. MECHANICKA (vzdy, zadarmo, deterministicka): parsuju sa zmenene .py/.json?
     Ak nie -> continue s chybou. Tvrdy zamok proti "hotovo" na rozbitom kode.
  2. MoA LLM REVIEW (opt-in, s poistkami): ak kod parsuje, dva modely co NEpisali
     (gpt+gemini) skontroluju zmenene .md/kod na AI-slop, sycophancy, bohemizmy,
     zjavne diery. Bezi cez zol_eval.evaluate (cross-model, MIN agregacia).

Hermes posle na stdin:
  {"hook_event_name":"pre_verify","cwd":...,
   "extra":{"coding":bool,"attempt":int,"changed_paths":[...],...}}
Vystup {"action":"continue","message":"..."} -> agent pokracuje jeden turn navyse
(bounded max_verify_nudges=3). Cokolvek ine -> turn skonci.

POISTKY MoA (aby nezlozilo session / 429 / DLP):
  - DEFAULT OFF: bezi len ked ZOL_VERIFY_MOA=1 (inak len mechanicka vrstva).
  - LEN attempt 0: nudne raz, neopakuje donekonecna.
  - THROTTLE: max raz za ZOL_VERIFY_MOA_COOLDOWN s (default 120) cez stamp subor.
  - FILTER: len .md/kod, 200..20000 znakov, max 2 subory/turn.
  - ENV self-load: PALANTIR_TOKEN (~/.zsh_secrets) + SSL bundle (hook nema .zshrc).
  - SIGALRM watchdog (default 90s) + FAIL-OPEN vsade: LLM zlyha/visi -> ticho pusti.
  - Hook nikdy nespadne (except -> ticho).
"""
import sys
import os
import json
import time
import tempfile
import py_compile

MAX_NUDGE_ATTEMPT = 2          # mechanicka: po tolkych pokusoch fail-open
REVIEW_EXT = (".md", ".py", ".js", ".ts", ".mjs", ".jsx", ".tsx", ".css", ".html")
MOA_MIN_CHARS = 200
MOA_MAX_CHARS = 20000
MOA_MAX_FILES = 2
LOG = os.path.expanduser("~/zolander/logs/verify.jsonl")


def _log(ev, **kw):
    """Struktrovany JSONL log kazdeho kroku -> diagnosticke okno. Fail-open."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": ev}
        rec.update(kw)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

REVIEW_SYSTEM = """Si prisny recenzent (mixture-of-agents) pre AI partaka Zolander.
Dostanes ZADANIE (co mal subor robit) a OBSAH zmeneneho suboru. Ohodnot 0.0-1.0:
- vernost: robi co ma, nic si nevymysla, ziadne halucinovane API/cesty
- vecnost: bez vaty a AI-slop frazi
- ton: pri .md cista slovencina bez bohemizmov a bez lichotiek; pri kode jasnost
- uzitocnost: realne funkcne a bezpecne, bez zjavnych bugov/dier
Vrat LEN validny JSON, nic pred ani za:
{"vernost":0.0,"vecnost":0.0,"ton":0.0,"uzitocnost":0.0,"celkom":0.0,"dovod":"1-2 vety konkretne"}"""


def _check_py(path: str) -> str:
    try:
        py_compile.compile(path, doraise=True)
        return ""
    except py_compile.PyCompileError as exc:
        return str(exc).strip().splitlines()[-1][:300]
    except Exception:
        return ""


def _check_json(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            json.load(f)
        return ""
    except json.JSONDecodeError as exc:
        return f"JSON: {exc}"[:300]
    except Exception:
        return ""


def _mechanical(changed):
    """Vrati zoznam '  path: chyba' pre subory co neparsuju."""
    broken = []
    for p in changed:
        if not isinstance(p, str) or not os.path.isfile(p):
            continue
        if p.endswith(".py"):
            err = _check_py(p)
        elif p.endswith(".json"):
            err = _check_json(p)
        else:
            continue
        if err:
            broken.append(f"  {p}: {err}")
    return broken


# ---------- MoA vrstva (opt-in) ----------

def _ensure_env():
    """Hook bezi pod /usr/bin/python3 bez .zshrc -> dopln token + SSL sam."""
    if not os.environ.get("PALANTIR_TOKEN"):
        try:
            for line in open(os.path.expanduser("~/.zsh_secrets"), encoding="utf-8"):
                s = line.strip()
                if "PALANTIR_TOKEN" in s and "=" in s:
                    os.environ["PALANTIR_TOKEN"] = s.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    if not os.environ.get("SSL_CERT_FILE"):
        b = os.path.expanduser("~/.config/certs/corp-ca-bundle.pem")
        if os.path.isfile(b):
            os.environ["SSL_CERT_FILE"] = b
            os.environ["REQUESTS_CA_BUNDLE"] = b


def _throttled():
    cooldown = float(os.environ.get("ZOL_VERIFY_MOA_COOLDOWN", "120"))
    stamp = os.path.join(tempfile.gettempdir(), "zol_moa_stamp")
    now = time.time()
    try:
        if os.path.isfile(stamp) and now - os.path.getmtime(stamp) < cooldown:
            return True
        open(stamp, "w").write(str(now))
    except Exception:
        pass
    return False


def _pick_files(changed):
    """Len review-hodne subory v rozsahu velkosti; max MOA_MAX_FILES."""
    out = []
    for p in changed:
        if not isinstance(p, str) or not os.path.isfile(p):
            continue
        if not p.endswith(REVIEW_EXT):
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:
            continue
        if MOA_MIN_CHARS <= len(txt) <= MOA_MAX_CHARS:
            out.append((p, txt))
        if len(out) >= MOA_MAX_FILES:
            break
    return out


def _moa_review(changed, cwd):
    """Vrati continue-message (str) ak MoA nasla problem, inak ''. Fail-open."""
    files = _pick_files(changed)
    if not files:
        return ""
    if _throttled():
        return ""
    _ensure_env()
    if not os.environ.get("PALANTIR_TOKEN"):
        return ""  # bez tokenu netlac

    # watchdog: cely MoA ohranicny SIGALRM (default 90s)
    import signal
    budget = int(float(os.environ.get("ZOL_VERIFY_MOA_BUDGET", "90")))

    def _timeout(*_):
        raise TimeoutError("MoA budget")

    try:
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(budget)
    except Exception:
        pass

    problems = []
    try:
        sys.path.insert(0, os.path.expanduser("~/zolander/toolkit"))
        sys.path.insert(0, os.path.expanduser("~/projects/zolo2.0/toolkit"))
        from zol_eval import evaluate
        threshold = float(os.environ.get("ZOL_VERIFY_MOA_THRESHOLD", "0.6"))
        for path, txt in files:
            zadanie = (f"Recenzuj zmeneny subor '{os.path.basename(path)}'. "
                       f"Ma byt korektny, cistou slovencinou (pri .md), bez AI-slop, "
                       f"bez lichotiek, bez zjavnych bugov/dier.")
            ev = evaluate(zadanie, txt, generator="opus", eval_system=REVIEW_SYSTEM)
            cel = ev.get("celkom")
            per = ev.get("per_judge", {})
            _log("moa_file", path=path, celkom=cel,
                 judges={k: (v.get("celkom") if isinstance(v, dict) else None)
                         for k, v in per.items()})
            if cel is not None and cel < threshold:
                dovody = " | ".join(
                    str(s.get("dovod", "")) for s in per.values()
                    if isinstance(s, dict) and s.get("dovod"))
                problems.append(f"  {path} [{cel:.2f}/1.0]: {dovody[:400]}")
    except TimeoutError:
        return ""  # vyprsal budget -> fail-open
    except Exception:
        return ""  # akakolvek chyba -> fail-open
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass

    if not problems:
        return ""
    return ("[Zolander MoA review] Dva recenzenti (gpt+gemini) nasli problem v "
            "zmenenych suboroch — zvaz opravu pred 'hotovo':\n" + "\n".join(problems))


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return

    extra = payload.get("extra") or {}
    if not extra.get("coding"):
        return
    attempt = int(extra.get("attempt") or 0)
    changed = extra.get("changed_paths") or []
    if not isinstance(changed, list):
        return

    _log("fired", attempt=attempt, n_changed=len(changed), changed=changed[:8])

    # --- vrstva 1: mechanicka (vzdy) ---
    if attempt < MAX_NUDGE_ATTEMPT:
        broken = _mechanical(changed)
        if broken:
            _log("mechanical_block", broken=broken)
            msg = ("[Zolander pre-verify zamok] Zmenene subory NEPARSUJU — oprav "
                   "syntax PRED tym nez vyhlasis hotovo:\n" + "\n".join(broken))
            print(json.dumps({"action": "continue", "message": msg}, ensure_ascii=False))
            return  # rozbity kod -> netreba MoA, najprv oprav syntax

    # --- vrstva 2: MoA LLM review (default ON, vypina ZOL_VERIFY_MOA=0) ---
    if os.environ.get("ZOL_VERIFY_MOA", "1") == "0":
        _log("moa_disabled")
        return
    if attempt != 0:
        _log("moa_skip", reason="attempt!=0", attempt=attempt)
        return
    _log("moa_start", n_changed=len(changed))
    try:
        msg = _moa_review(changed, payload.get("cwd"))
    except Exception as e:
        _log("moa_error", err=repr(e)[:200])
        msg = ""  # fail-open
    if msg:
        _log("moa_block", msg=msg[:400])
        print(json.dumps({"action": "continue", "message": msg}, ensure_ascii=False))
    else:
        _log("moa_pass")


if __name__ == "__main__":
    main()
