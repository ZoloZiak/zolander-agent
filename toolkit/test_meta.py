#!/usr/bin/env python3
"""test_meta.py — OFFLINE testy pre zol_meta.py (Meta-Agent) + zol_manifest.py (gen).

Dokazuje bod 1 + bod 2 naostro (bez LLM, bez siete):
  - zol_manifest.generate: kazda sablona, povinne params, fail na neznamom type
  - zol_meta.diagnose: lokalizacia komponentu + klasifikacia + priorita blokujucich
  - zol_meta.propose: zapis do pending (docasny, nie ostry state)
  - zol_meta.verify_proposal: validacna brana PASS (opraveny) aj FAIL (stale rozbity)
    + REGRESIA cez baseline -> nevalidne

Beh: /usr/bin/python3 test_meta.py
"""
import os
import sys
import json
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zol_manifest as zm  # noqa: E402
import zol_meta as meta    # noqa: E402
import zol_checker as zc    # noqa: E402

_fails = []


def check(name, cond):
    print(f"  [{'ok' if cond else 'ZLYHALO'}] {name}")
    if not cond:
        _fails.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="zolmeta_")

    print("== bod 2: zol_manifest.generate (kazda sablona) ==")
    m = zm.generate("code", {"path": "/x/y.py", "test_cmd": ["true"]})
    check("code: ma compiles+exists+tests", {a["type"] for a in m["anchors"]} >=
          {"py_compile", "file_exists", "cmd_exit"})
    m2 = zm.generate("push", {"repo": "/r", "sha": "abc", "files": ["/f1"]})
    types2 = [a["type"] for a in m2["anchors"]]
    check("push: ma git_pushed", "git_pushed" in types2)
    check("push: sanit leak-gate na subor", any(
        a["type"] == "not_contains" and a.get("on_fail") == "leak" for a in m2["anchors"]))
    m3 = zm.generate("skill-edit", {"path": "/s/SKILL.md", "must": ["## 6.6"], "version": "2.1.0"})
    check("skill-edit: has-0 marker + version + component=skill", any(
        a["id"] == "has-0" and a["component"] == "skill" for a in m3["anchors"]))
    m4 = zm.generate("chapter", {"path": "/k/ch1.md", "cite_pattern": r"atom:\d+",
                                 "leaks": ["Wojciech"]})
    check("chapter: Regime B (line_count_min + not_contains leak + regex retrieval)",
          {a["type"] for a in m4["anchors"]} >= {"line_count_min", "not_contains", "regex_present"})
    check("chapter: leak-gate obsahuje default sanit vzory", any(
        r"/Users/__USER__" in (a.get("must_not") or []) for a in m4["anchors"]
        if a["type"] == "not_contains"))
    m5 = zm.generate("sanitize", {"paths": ["/a", "/b"]})
    check("sanitize: anchor na kazdy subor", len(m5["anchors"]) == 2)

    print("== bod 2: nove typy (refactor/toolkit) + aliasy + _skipped ==")
    m6 = zm.generate("refactor", {"files": ["/x/a.py", "/x/data.md"],
                                  "tests": ["/x/test_a.py"]})
    t6 = [a["type"] for a in m6["anchors"]]
    check("refactor: py_compile + file_exists (ne-.py) + cmd_exit test",
          "py_compile" in t6 and "file_exists" in t6 and "cmd_exit" in t6)
    m7 = zm.generate("toolkit", {"files": ["/t/z.py"]})
    check("toolkit: ma green-check cmd_exit --offline", any(
        a["id"] == "green-check" and a["cmd"][-1] == "--offline" for a in m7["anchors"]))
    check("alias book -> chapter", zm.generate("book", {"path": "/b.md"})["task_type"] == "chapter")
    check("alias skill -> skill-edit",
          zm.generate("skill", {"path": "/s/SKILL.md"})["task_type"] == "skill-edit")
    m8 = zm.generate("chapter", {"path": "/k/c.md"})  # bez cite_pattern
    check("_skipped: chybajuci cite_pattern sa transparentne poznamena",
          "_skipped" in m8 and any("cites-atoms" in s for s in m8["_skipped"]))
    m9 = zm.generate("skill-edit", {"path": "/s/SKILL.md"})  # auto-frontmatter na SKILL.md
    check("skill-edit: SKILL.md dostane frontmatter anchor auto", any(
        a["id"] == "frontmatter" for a in m9["anchors"]))
    check("refactor bez files aj tests -> ValueError", _raises(zm.generate, "refactor", {}))

    print("== bod 2: fail-closed generovanie ==")
    check("neznamy task_type -> ValueError", _raises(zm.generate, "vymysleny", {}))
    check("code bez path -> ValueError", _raises(zm.generate, "code", {}))
    check("sanitize bez path/paths -> ValueError", _raises(zm.generate, "sanitize", {}))

    print("== bod 1: zol_meta.diagnose (lokalizacia + klasifikacia) ==")
    report = {
        "task": "t", "fail": 3, "results": [
            {"id": "ok1", "type": "file_exists", "pass": True, "component": "artifact"},
            {"id": "leak1", "type": "not_contains", "pass": False, "fail_class": "leak",
             "component": "artifact", "reason": "leak: ['__USER__']", "path": "/pub/f"},
            {"id": "miss1", "type": "file_exists", "pass": False, "fail_class": "missing",
             "component": "artifact", "reason": "neexistuje"},
            {"id": "skl1", "type": "file_contains", "pass": False,
             "fail_class": "implementation_bug", "component": "skill", "reason": "nenaslo"},
        ]}
    d = meta.diagnose(report)
    check("diagnose: 3 directives (len faily)", d["n_fail"] == 3 and len(d["directives"]) == 3)
    leak_dir = next(x for x in d["directives"] if x["anchor"] == "leak1")
    check("leak je blocking", leak_dir["blocking"] is True)
    check("leak action spomina sanitizaciu", "sanit" in leak_dir["action"].lower())
    skl_dir = next(x for x in d["directives"] if x["anchor"] == "skl1")
    check("skill+impl_bug -> action mieri na SKILL.md sekciu", "SKILL.md" in skl_dir["action"])
    check("priorita: blokujuci leak je prvy", d["priority"][0] == "leak1")

    print("== bod 1: propose (zapis do pending, docasny nie ostry) ==")
    orig_pending = meta.PENDING
    meta.PENDING = os.path.join(tmp, "pending.jsonl")
    try:
        res = meta.propose(report)
        check("propose zapisal subor", os.path.exists(meta.PENDING))
        pend = meta.show_pending()
        check("pending ma 1 zaznam status=pending", len(pend) == 1 and pend[0]["status"] == "pending")
        check("propose vratil written_to", res.get("written_to") == meta.PENDING)
    finally:
        meta.PENDING = orig_pending

    print("== bod 1: verify_proposal (validacna brana) ==")
    # rozbity artefakt -> manifest FAIL -> verify NEvaliduje
    manifest = os.path.join(tmp, "man.json")
    target = os.path.join(tmp, "art.py")
    json.dump(zm.generate("code", {"path": target}), open(manifest, "w"))
    v_fail = meta.verify_proposal(manifest)
    check("verify: rozbity (chyba subor) -> validated False", v_fail["validated"] is False)
    # oprav artefakt -> verify validuje
    open(target, "w").write("def g():\n    return 1\n")
    v_ok = meta.verify_proposal(manifest)
    check("verify: opraveny -> validated True", v_ok["validated"] is True)
    check("verify: validated exit 0 semantika", v_ok["fail"] == 0 and not v_ok["regression"])

    print("== bod 1: verify + REGRESIA cez baseline -> nevalidne ==")
    orig_bdir = zc.BASELINE_DIR
    zc.BASELINE_DIR = os.path.join(tmp, "baselines")
    try:
        # baseline ked su OBA PASS
        good2 = os.path.join(tmp, "art2.py")
        open(good2, "w").write("x = 1\n")
        reg_manifest = os.path.join(tmp, "regman.json")
        json.dump({"task": "regtask", "anchors": [
            {"id": "a", "type": "file_exists", "path": target},
            {"id": "b", "type": "file_exists", "path": good2},
        ]}, open(reg_manifest, "w"))
        subprocess.run(["/usr/bin/python3", os.path.join(HERE, "zol_checker.py"),
                        "baseline", reg_manifest],
                       capture_output=True, text=True,
                       env={**os.environ})  # baseline dir cez modul, nie subprocess
        # subprocess ma iny BASELINE_DIR -> radsej over cez modul priamo:
        zc.save_baseline(reg_manifest)
        os.remove(good2)  # znic co bolo PASS -> regresia
        # verify_proposal vola subprocess zol_checker (iny proces) -> ten nevidi nas
        # docasny BASELINE_DIR. Preto regresiu overime priamo modulom (deterministicky).
        rep = zc.run_manifest(reg_manifest, regress=True)
        check("regresia detekovana modulom", rep.get("regression") is True)
        check("exit_code 2 pri regresii", zc._exit_code(rep) == 2)
    finally:
        zc.BASELINE_DIR = orig_bdir

    print("== CLI subprocess (skutocny beh) ==")
    p = subprocess.run(["/usr/bin/python3", os.path.join(HERE, "zol_meta.py"),
                        "diagnose", "-"], input=json.dumps(report),
                       capture_output=True, text=True)
    check("meta diagnose CLI exit 0", p.returncode == 0)
    check("meta diagnose CLI vrati JSON s directives",
          "directives" in (p.stdout or ""))
    pv = subprocess.run(["/usr/bin/python3", os.path.join(HERE, "zol_meta.py"),
                         "verify", manifest], capture_output=True, text=True)
    check("meta verify CLI exit 0 (opraveny)", pv.returncode == 0)

    print("-" * 50)
    if _fails:
        print(f"FAIL: {len(_fails)} zlyhani -> {_fails}")
        return 1
    print("VSETKY TESTY PRESLI")
    return 0


def _raises(fn, *a):
    try:
        fn(*a)
        return False
    except ValueError:
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
