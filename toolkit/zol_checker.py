#!/usr/bin/env python3
"""zol_checker.py — evidence->checker loop (anchor-runner). Recuris/OpenSkill v KODE.

CO to je (a preco NIE je to len lepsi checklist):
  Recuris (arXiv 2608.24876) hovori: ciel je "hotovy" LEN ked to potvrdi OBSERVACIA,
  nie ked model povie "spravil som to". "Invoking a tool is not completion evidence."
  Textovy skill (§6.6 anti-hallucination-protocol) to opisuje; TENTO skript to VYNUCUJE
  ako spustitelny gate (exit 0 = vsetky anchory PASS, 1 = FAIL, 2 = REGRESIA, 3 = chyba).

  Priama zaplatka na realny bug: raz som vyhlasil commit hash bez `git ls-remote`. Anchor
  typu `git_pushed` to znemozni — kym remote nema ten SHA, ciel NIE je done.

Dva rezimy dokazu (destilat z 5 zdrojov, nie 1 papera):
  REGIME A (ground-truth, LLM-free): file_exists/contains/line, git_pushed, cmd_exit,
    cmd_output_contains/lacks, py_compile, json_valid. Binarne, lacne, opakovatelne.
  REGIME B (bez oracle — kniha/analyza; OpenSkill 2606.06741): verification ANCHORS =
    overitelne invarianty z externej evidencie. not_contains (leak-gate mien/ciest),
    regex_present, line_count_min. Nehodnotia "kvalitu", ale MOZU zlyhat -> menia
    negradovatelnu ulohu na sadu binarnych checkov.

Dalsie principy zabudovane:
  - Failure klasifikacia (OpenSkill): kazdy FAIL nesie hint knowledge_gap|
    implementation_bug|leak|regression|missing -> ina oprava.
  - Component localization (Recuris): anchor moze deklarovat `component`
    (skill|state|retrieval|checker|artifact) -> vies KDE opravit, nie len ZE zlyhalo.
  - Revert-on-regression (EvolveMem 2605.13941): `--regress` porovna proti baseline
    (posledny PASS set). Anchor co BOL PASS a je teraz FAIL = regresia -> exit 2
    (silnejsi signal nez cerstvy FAIL). To je mechanicka revert-on-regression brana.

Design (konvencie toolkitu):
  - stdlib only, /usr/bin/python3, ziadne LLM volania.
  - FAIL-CLOSED (opak fail-open daemonov): zmyslom je chytit klamstvo, tak radsej
    falosny poplach nez prehltnute zlyhanie. Chyba checkera != PASS.
  - sandbox: subprocess VZDY argv list, shell=False. Ziadne &&/;/bash -c.
  - Rozlisuj empty vs error (§7.5 anti-hallucination): git bez remote = "no_remote"
    stav, NIE FAIL.

Pouzitie:
  zol_checker.py run <manifest.json|jsonl>        # spusti anchory, JSON report, exit 0/1
  zol_checker.py run <manifest> --regress         # + porovnaj proti baseline (exit 2 na regr.)
  zol_checker.py baseline <manifest>              # uloz aktualny PASS set ako baseline
  zol_checker.py check <type> <json-args>         # jeden ad-hoc anchor (rychly gate)
  echo '<anchor JSON>' | zol_checker.py check -   # anchor zo stdin
  zol_checker.py types                            # zoznam typov anchorov

Manifest = JSON {"anchors":[...]} alebo {"task":"id","anchors":[...]} alebo JSONL (1 anchor/riadok).
Anchor = {"id","type","desc"?,"component"?, + type-specificke args (path, must, cmd, ...)}
"""
import os
import re
import sys
import json
import subprocess
import py_compile

try:
    from zol_paths import ZROOT, STATE
except Exception:  # fail-open na import cesty (skript byva volany z roznych cwd)
    ZROOT = os.environ.get("ZOLANDER_ROOT") or os.path.expanduser("~/projects/zolander")
    STATE = os.path.join(ZROOT, "state")

try:
    from zol_events import emit  # diagnostika: preco anchor zlyhal, dohladatelne
except Exception:
    def emit(*a, **k):  # fail-open stub — logging nikdy nezhodi gate
        pass

BASELINE_DIR = os.path.join(STATE, "checker_baselines")

# Mapovanie typu anchora -> default klasifikacia zlyhania (OpenSkill).
# Konkretny anchor moze prebit cez pole "on_fail".
_DEFAULT_FAIL_CLASS = {
    "file_exists": "missing",
    "file_contains": "implementation_bug",
    "file_line": "implementation_bug",
    "git_pushed": "implementation_bug",
    "cmd_exit": "implementation_bug",
    "cmd_output_contains": "implementation_bug",
    "cmd_output_lacks": "implementation_bug",
    "py_compile": "implementation_bug",
    "json_valid": "implementation_bug",
    "not_contains": "leak",
    "regex_present": "knowledge_gap",
    "line_count_min": "knowledge_gap",
}


# ------------------------------------------------------------------ helpers ---
def _expand(p):
    return os.path.expanduser(os.path.expandvars(p))


def _run_cmd(cmd, timeout=60, cwd=None):
    """Spusti argv list BEZ shellu (shell-safe). Vrati (rc, out, err) alebo (None, "", chyba).
    cmd MUSI byt list — string by vyzadoval shell=True (zakazane). Kazdy argv prvok sa
    expanduje (~ a $VAR), lebo bez shellu ich nikto nerozvinie — inak `python3 ~/x.py`
    hlada doslovny '~' adresar (realny bug ktory checker sam na sebe chytil 2026-08-28)."""
    if isinstance(cmd, str):
        # bezpecnostna poistka: nikdy neinterpretuj string cez shell. Rozdel na argv.
        cmd = cmd.split()
    cmd = [_expand(str(c)) for c in cmd]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=_expand(cwd) if cwd else None)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return None, "", f"cmd_not_found: {e}"
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    except Exception as e:
        return None, "", f"error: {e}"


def ok(a, **extra):
    return {"id": a.get("id", "?"), "type": a.get("type"), "pass": True,
            "component": a.get("component", "artifact"), **extra}


def fail(a, reason, **extra):
    cls = a.get("on_fail") or _DEFAULT_FAIL_CLASS.get(a.get("type"), "implementation_bug")
    return {"id": a.get("id", "?"), "type": a.get("type"), "pass": False,
            "reason": reason, "fail_class": cls,
            "component": a.get("component", "artifact"), **extra}


# ------------------------------------------------------------ checker library ---
# Kazdy checker: dostane anchor dict, vrati result dict (ok(...) | fail(...)).
# ZLATE PRAVIDLO: checker cita OBSERVACIU (disk/proces/vystup), nikdy nedoveruje
# tvrdeniu ze "to bolo spravene".

def c_file_exists(a):
    p = _expand(a["path"])
    return ok(a, path=p) if os.path.exists(p) else fail(a, f"neexistuje: {p}", path=p)


def c_file_contains(a):
    p = _expand(a["path"])
    if not os.path.isfile(p):
        return fail(a, f"subor chyba: {p}", path=p)
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return fail(a, f"nedaco citat: {e}", path=p)
    pat = a["must"]
    use_re = a.get("regex", False)
    hit = re.search(pat, txt) if use_re else (pat in txt)
    return ok(a, path=p) if hit else fail(a, f"nenaslo '{pat}'", path=p)


def c_file_line(a):
    p = _expand(a["path"])
    try:
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        n = int(a["line"])
        actual = lines[n - 1] if 0 < n <= len(lines) else ""
    except Exception as e:
        return fail(a, f"chyba citania: {e}", path=p)
    return ok(a, path=p) if a["must"] in actual else \
        fail(a, f"riadok {a['line']} != '{a['must']}'", actual=actual.strip()[:100], path=p)


def c_git_pushed(a):
    """Overi ze remote REALNE ma dany SHA/branch (git ls-remote). Priama zaplatka na
    vymysleny-hash bug. Rozlisuj: no_remote (repo bez remote) = NIE FAIL, len stav."""
    repo = _expand(a.get("repo", ZROOT))
    remote = a.get("remote", "origin")
    # najprv: ma repo vobec ten remote?
    rc, out, err = _run_cmd(["git", "-C", repo, "remote"], timeout=15)
    if rc is None:
        return fail(a, f"git zlyhal: {err}", repo=repo)
    remotes = out.split()
    if remote not in remotes:
        # empty != error (§7.5): repo bez remote nie je zlyhanie pushu, je to iny stav.
        return ok(a, state="no_remote", note=f"repo nema remote '{remote}' (lokalne)",
                  repo=repo)
    rc, out, err = _run_cmd(["git", "-C", repo, "ls-remote", remote], timeout=45)
    if rc is None or rc != 0:
        return fail(a, f"ls-remote zlyhal: {err or out}", repo=repo)
    want = a.get("sha") or a.get("branch")
    if not want:
        # bez konkretneho SHA/branch: staci ze remote odpoveda (dosiahnutelny)
        return ok(a, note="remote dosiahnutelny", repo=repo)
    return ok(a, repo=repo) if want in out else \
        fail(a, f"remote nema '{want}'", repo=repo)


def c_cmd_exit(a):
    rc, out, err = _run_cmd(a["cmd"], timeout=a.get("timeout", 60), cwd=a.get("cwd"))
    want = a.get("expect", 0)
    if rc is None:
        return fail(a, f"prikaz nebezal: {err}")
    return ok(a, rc=rc) if rc == want else fail(a, f"exit {rc} != {want}", rc=rc,
                                                stderr=err.strip()[:200])


def c_cmd_output_contains(a):
    rc, out, err = _run_cmd(a["cmd"], timeout=a.get("timeout", 60), cwd=a.get("cwd"))
    if rc is None:
        return fail(a, f"prikaz nebezal: {err}")
    blob = out + err
    pat = a["must"]
    hit = re.search(pat, blob) if a.get("regex") else (pat in blob)
    return ok(a, rc=rc) if hit else fail(a, f"vystup neobsahuje '{pat}'", rc=rc)


def c_cmd_output_lacks(a):
    """Vystup NESMIE obsahovat vzor (napr. 'Traceback', 'FAIL', 'error')."""
    rc, out, err = _run_cmd(a["cmd"], timeout=a.get("timeout", 60), cwd=a.get("cwd"))
    if rc is None:
        return fail(a, f"prikaz nebezal: {err}")
    blob = out + err
    pat = a["must_not"]
    hit = re.search(pat, blob) if a.get("regex") else (pat in blob)
    return fail(a, f"vystup obsahuje zakazane '{pat}'", rc=rc) if hit else ok(a, rc=rc)


def c_py_compile(a):
    p = _expand(a["path"])
    if not os.path.isfile(p):
        return fail(a, f"subor chyba: {p}", path=p)
    try:
        py_compile.compile(p, doraise=True)
        return ok(a, path=p)
    except py_compile.PyCompileError as e:
        return fail(a, f"syntax: {str(e).splitlines()[-1][:150]}", path=p)
    except Exception as e:
        return fail(a, f"chyba: {e}", path=p)


def c_json_valid(a):
    p = _expand(a["path"])
    try:
        json.load(open(p, encoding="utf-8"))
        return ok(a, path=p)
    except Exception as e:
        return fail(a, f"nevalidny JSON: {e}", path=p)


def c_not_contains(a):
    """REGIME B leak-gate: subor NESMIE obsahovat ziadny zo vzorov (mena, cesty).
    Napr. sanitizacia pred verejnym pushom / kniha bez leaknutych mien."""
    p = _expand(a["path"])
    if not os.path.isfile(p):
        return fail(a, f"subor chyba: {p}", path=p)
    txt = open(p, encoding="utf-8", errors="replace").read()
    pats = a["must_not"] if isinstance(a["must_not"], list) else [a["must_not"]]
    leaked = []
    for pat in pats:
        if (re.search(pat, txt) if a.get("regex") else (pat in txt)):
            leaked.append(pat)
    return ok(a, path=p) if not leaked else \
        fail(a, f"leak: {leaked}", leaked=leaked, path=p)


def c_regex_present(a):
    """REGIME B invariant: subor MUSI matchnut regex (napr. citacia atomu, ISO datum)."""
    p = _expand(a["path"])
    if not os.path.isfile(p):
        return fail(a, f"subor chyba: {p}", path=p)
    txt = open(p, encoding="utf-8", errors="replace").read()
    n = len(re.findall(a["pattern"], txt))
    need = a.get("min", 1)
    return ok(a, matches=n) if n >= need else \
        fail(a, f"regex {n}x < min {need}", matches=n, path=p)


def c_line_count_min(a):
    """REGIME B invariant: artefakt ma aspon N riadkov (napr. kapitola nie prazdna)."""
    p = _expand(a["path"])
    if not os.path.isfile(p):
        return fail(a, f"subor chyba: {p}", path=p)
    n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
    need = int(a.get("min", 1))
    return ok(a, lines=n) if n >= need else fail(a, f"{n} riadkov < min {need}", lines=n)


CHECKERS = {
    "file_exists": c_file_exists,
    "file_contains": c_file_contains,
    "file_line": c_file_line,
    "git_pushed": c_git_pushed,
    "cmd_exit": c_cmd_exit,
    "cmd_output_contains": c_cmd_output_contains,
    "cmd_output_lacks": c_cmd_output_lacks,
    "py_compile": c_py_compile,
    "json_valid": c_json_valid,
    "not_contains": c_not_contains,
    "regex_present": c_regex_present,
    "line_count_min": c_line_count_min,
}


# ------------------------------------------------------------------- engine ---
def run_anchor(a):
    """Spusti jeden anchor. FAIL-CLOSED: neznamy typ / vynimka checkera = FAIL,
    nikdy nie ticho-PASS (zmyslom je chytit klamstvo)."""
    t = a.get("type")
    fn = CHECKERS.get(t)
    if fn is None:
        return fail(a, f"neznamy typ anchora: {t}")
    missing = [k for k in _required_args(t) if k not in a]
    if missing:
        return fail(a, f"chybajuce args: {missing}")
    try:
        return fn(a)
    except Exception as e:
        return fail(a, f"checker vynimka: {e}")


def _required_args(t):
    return {
        "file_exists": ["path"], "file_contains": ["path", "must"],
        "file_line": ["path", "line", "must"], "git_pushed": [],
        "cmd_exit": ["cmd"], "cmd_output_contains": ["cmd", "must"],
        "cmd_output_lacks": ["cmd", "must_not"], "py_compile": ["path"],
        "json_valid": ["path"], "not_contains": ["path", "must_not"],
        "regex_present": ["path", "pattern"], "line_count_min": ["path"],
    }.get(t, [])


def load_manifest(path):
    """Nacitaj manifest: JSON {"anchors":[...]} / {"task","anchors"} alebo JSONL."""
    raw = open(_expand(path), encoding="utf-8").read().strip()
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d.get("task", os.path.basename(path)), d.get("anchors", [])
        if isinstance(d, list):
            return os.path.basename(path), d
    except json.JSONDecodeError:
        pass
    # JSONL fallback
    anchors = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln:
            anchors.append(json.loads(ln))
    return os.path.basename(path), anchors


def run_manifest(path, regress=False):
    task, anchors = load_manifest(path)
    return run_anchors(task, anchors, regress=regress)


def run_anchors(task, anchors, regress=False):
    results = [run_anchor(a) for a in anchors]
    rid = None
    try:
        from zol_events import new_run
        rid = new_run("checker")
    except Exception:
        pass
    npass = sum(r["pass"] for r in results)
    nfail = len(results) - npass
    report = {
        "task": task, "total": len(results), "pass": npass, "fail": nfail,
        "results": results,
        "fail_by_class": _group_fail(results),
        "fail_by_component": _group_component(results),
    }
    # Regresia (EvolveMem): anchor co bol PASS v baseline a je teraz FAIL.
    if regress:
        regressed = _detect_regression(task, results)
        report["regressed"] = regressed
        report["regression"] = bool(regressed)
    for r in results:
        if not r["pass"]:
            emit("checker", "anchor_fail",
                 {"task": task, "id": r["id"], "type": r["type"],
                  "class": r.get("fail_class"), "reason": r.get("reason")}, rid)
    emit("checker", "done",
         {"task": task, "pass": npass, "fail": nfail,
          "regression": report.get("regression", False)}, rid)
    return report


def _group_fail(results):
    g = {}
    for r in results:
        if not r["pass"]:
            g.setdefault(r.get("fail_class", "?"), []).append(r["id"])
    return g


def _group_component(results):
    g = {}
    for r in results:
        if not r["pass"]:
            g.setdefault(r.get("component", "artifact"), []).append(r["id"])
    return g


# --------------------------------------------------- baseline / regression ---
def _baseline_path(task):
    safe = re.sub(r"[^\w.-]", "_", task)
    return os.path.join(BASELINE_DIR, safe + ".json")


def save_baseline(path):
    """Uloz aktualny PASS set anchorov ako baseline (EvolveMem anchor set)."""
    task, anchors = load_manifest(path)
    results = [run_anchor(a) for a in anchors]
    passed = sorted(r["id"] for r in results if r["pass"])
    os.makedirs(BASELINE_DIR, exist_ok=True)
    bp = _baseline_path(task)
    with open(bp, "w", encoding="utf-8") as f:
        json.dump({"task": task, "passed_ids": passed,
                   "total": len(results)}, f, ensure_ascii=False, indent=2)
    return {"task": task, "baseline": bp, "passed_ids": passed}


def _detect_regression(task, results):
    """Vrat zoznam id anchorov co BOLI PASS v baseline ale su teraz FAIL."""
    bp = _baseline_path(task)
    if not os.path.exists(bp):
        return []
    try:
        base = json.load(open(bp, encoding="utf-8"))
        was_pass = set(base.get("passed_ids", []))
    except Exception:
        return []
    now_fail = {r["id"] for r in results if not r["pass"]}
    return sorted(was_pass & now_fail)


# --------------------------------------------------------------------- CLI ---
def _print_report(report):
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _exit_code(report):
    """0 = vsetko PASS; 2 = regresia (silnejsi signal); 1 = FAIL bez regresie."""
    if report.get("regression"):
        return 2
    return 0 if report["fail"] == 0 else 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 3
    cmd = sys.argv[1]
    if cmd == "types":
        print(json.dumps({t: _required_args(t) for t in CHECKERS}, indent=2))
        return 0
    if cmd == "run":
        if len(sys.argv) < 3:
            print("run <manifest> [--regress]", file=sys.stderr)
            return 3
        regress = "--regress" in sys.argv[3:]
        report = run_manifest(sys.argv[2], regress=regress)
        _print_report(report)
        return _exit_code(report)
    if cmd == "gen":
        # Auto-generuj manifest z typu ulohy (bod 2) — deleguje na zol_manifest.
        # gen <task_type> '<json>'|k=v...  [--run] [--out <path>]
        try:
            import zol_manifest
        except Exception as e:
            print(f"zol_manifest nedostupny: {e}", file=sys.stderr)
            return 3
        if len(sys.argv) < 3:
            print("gen <task_type> '<json>'|k=v... [--run] [--out <path>]", file=sys.stderr)
            return 3
        task_type = sys.argv[2]
        rest = sys.argv[3:]
        do_run = "--run" in rest
        out_path = None
        if "--out" in rest:
            i = rest.index("--out")
            out_path = rest[i + 1] if i + 1 < len(rest) else None
            rest = rest[:i] + rest[i + 2:]
        rest = [x for x in rest if x != "--run"]
        params = zol_manifest._parse_params(rest) if rest else {}
        try:
            man = zol_manifest.generate(task_type, params)
        except ValueError as e:
            print(f"CHYBA: {e}", file=sys.stderr)
            return 3
        if out_path:
            with open(_expand(out_path), "w", encoding="utf-8") as f:
                json.dump(man, f, ensure_ascii=False, indent=2)
        if do_run:
            # spusti vygenerovany manifest rovno (zapis do docasneho suboru ak treba)
            import tempfile
            tmp = out_path
            if not tmp:
                fd, tmp = tempfile.mkstemp(prefix="zolgen_", suffix=".json")
                os.close(fd)
                json.dump(man, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            report = run_manifest(tmp, regress="--regress" in sys.argv[3:])
            # transparentne: co sa NEdalo overit (chybajuce params) prenes do reportu
            if man.get("_skipped"):
                report["_skipped"] = man["_skipped"]
            _print_report(report)
            if not out_path:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            return _exit_code(report)
        print(json.dumps(man, ensure_ascii=False, indent=2))
        return 0
    if cmd == "baseline":
        if len(sys.argv) < 3:
            print("baseline <manifest>", file=sys.stderr)
            return 3
        print(json.dumps(save_baseline(sys.argv[2]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "check":
        arg = sys.argv[2] if len(sys.argv) > 2 else "-"
        if arg == "-":
            anchor = json.loads(sys.stdin.read())
        elif len(sys.argv) > 3:
            # check <type> <json-args>
            anchor = json.loads(sys.argv[3])
            anchor["type"] = arg
        else:
            anchor = json.loads(arg)
        r = run_anchor(anchor)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["pass"] else 1
    print(f"neznamy prikaz: {cmd}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
