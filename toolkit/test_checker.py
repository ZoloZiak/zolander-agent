#!/usr/bin/env python3
"""test_checker.py — OFFLINE testy pre zol_checker.py (anchor-runner).

Konvencia run_tests.py: kazde tvrdenie o feature ma green-check co ho DOKAZUJE naostro.
Testujeme KAZDY checker v PASS aj FAIL vetve (nie len happy path — §7.5 anti-halluc:
harness co testuje len uspech je slepy na false-positive). Plus E2E manifest + regresia.

Ziadny LLM, ziadna siet — cisto disk + subprocess. Beh: /usr/bin/python3 test_checker.py
"""
import os
import sys
import json
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zol_checker as zc  # noqa: E402

_fails = []


def check(name, cond):
    mark = "ok" if cond else "ZLYHALO"
    print(f"  [{mark}] {name}")
    if not cond:
        _fails.append(name)


def anchor_pass(a):
    return zc.run_anchor(a)["pass"]


def main():
    tmp = tempfile.mkdtemp(prefix="zolcheck_")
    good = os.path.join(tmp, "good.txt")
    open(good, "w").write("riadok jedna\nMARKER_TU\ntreti riadok\n")
    pyf = os.path.join(tmp, "mod.py")
    open(pyf, "w").write("def f():\n    return 1\n")
    badpy = os.path.join(tmp, "bad.py")
    open(badpy, "w").write("def f(:\n  broken\n")
    jgood = os.path.join(tmp, "g.json")
    open(jgood, "w").write('{"a": 1}')
    jbad = os.path.join(tmp, "b.json")
    open(jbad, "w").write('{not json,,}')

    print("== REGIME A: file checkers ==")
    check("file_exists PASS", anchor_pass({"type": "file_exists", "path": good}))
    check("file_exists FAIL", not anchor_pass({"type": "file_exists", "path": good + ".x"}))
    check("file_contains PASS", anchor_pass(
        {"type": "file_contains", "path": good, "must": "MARKER_TU"}))
    check("file_contains FAIL", not anchor_pass(
        {"type": "file_contains", "path": good, "must": "NETU"}))
    check("file_contains regex PASS", anchor_pass(
        {"type": "file_contains", "path": good, "must": r"MARKER_\w+", "regex": True}))
    check("file_line PASS", anchor_pass(
        {"type": "file_line", "path": good, "line": 2, "must": "MARKER_TU"}))
    check("file_line FAIL (zly obsah)", not anchor_pass(
        {"type": "file_line", "path": good, "line": 1, "must": "MARKER_TU"}))

    print("== REGIME A: py_compile / json_valid ==")
    check("py_compile PASS", anchor_pass({"type": "py_compile", "path": pyf}))
    check("py_compile FAIL (syntax)", not anchor_pass({"type": "py_compile", "path": badpy}))
    check("json_valid PASS", anchor_pass({"type": "json_valid", "path": jgood}))
    check("json_valid FAIL", not anchor_pass({"type": "json_valid", "path": jbad}))

    print("== REGIME A: cmd checkers (subprocess, shell=False) ==")
    check("cmd_exit PASS (true->0)", anchor_pass(
        {"type": "cmd_exit", "cmd": ["true"], "expect": 0}))
    check("cmd_exit FAIL (false->1!=0)", not anchor_pass(
        {"type": "cmd_exit", "cmd": ["false"], "expect": 0}))
    check("cmd_output_contains PASS", anchor_pass(
        {"type": "cmd_output_contains", "cmd": ["echo", "ahoj-svet"], "must": "ahoj"}))
    check("cmd_output_contains FAIL", not anchor_pass(
        {"type": "cmd_output_contains", "cmd": ["echo", "x"], "must": "nieje"}))
    check("cmd_output_lacks PASS (ziadny traceback)", anchor_pass(
        {"type": "cmd_output_lacks", "cmd": ["echo", "cisto"], "must_not": "Traceback"}))
    check("cmd_output_lacks FAIL (najde zakazane)", not anchor_pass(
        {"type": "cmd_output_lacks", "cmd": ["echo", "Traceback tu"], "must_not": "Traceback"}))

    print("== REGIME B: anchors bez oracle ==")
    leaky = os.path.join(tmp, "leak.txt")
    open(leaky, "w").write("cista veta\nvolam sa /Users/__USER__ tajne\n")
    clean = os.path.join(tmp, "clean.txt")
    open(clean, "w").write("uplne cista kapitola bez mien\n" * 5)
    check("not_contains PASS (cisty)", anchor_pass(
        {"type": "not_contains", "path": clean, "must_not": ["/Users/__USER__", "tajne"]}))
    check("not_contains FAIL (leak)", not anchor_pass(
        {"type": "not_contains", "path": leaky, "must_not": ["/Users/__USER__", "tajne"]}))
    check("regex_present PASS", anchor_pass(
        {"type": "regex_present", "path": good, "pattern": r"riadok", "min": 1}))
    check("regex_present FAIL (min privysoky)", not anchor_pass(
        {"type": "regex_present", "path": good, "pattern": r"riadok", "min": 99}))
    check("line_count_min PASS", anchor_pass(
        {"type": "line_count_min", "path": clean, "min": 3}))
    check("line_count_min FAIL", not anchor_pass(
        {"type": "line_count_min", "path": good, "min": 99}))

    print("== FAIL-CLOSED: neznamy typ / chybajuce args = FAIL ==")
    check("neznamy typ = FAIL", not anchor_pass({"type": "vymysleny", "path": good}))
    check("chybajuce args = FAIL", not anchor_pass({"type": "file_contains", "path": good}))

    print("== Failure klasifikacia (OpenSkill) ==")
    r = zc.run_anchor({"type": "not_contains", "path": leaky,
                       "must_not": ["tajne"], "id": "leaktest"})
    check("leak -> fail_class=leak", r.get("fail_class") == "leak")
    r2 = zc.run_anchor({"type": "file_exists", "path": good + ".x", "id": "m"})
    check("chybajuci subor -> fail_class=missing", r2.get("fail_class") == "missing")
    r3 = zc.run_anchor({"type": "file_contains", "path": good, "must": "X",
                        "id": "c", "on_fail": "knowledge_gap"})
    check("on_fail override", r3.get("fail_class") == "knowledge_gap")

    print("== Component localization (Recuris) ==")
    r4 = zc.run_anchor({"type": "file_exists", "path": good + ".x",
                        "id": "s1", "component": "skill"})
    check("component propaguje do vysledku", r4.get("component") == "skill")

    print("== E2E: manifest run ==")
    manifest = os.path.join(tmp, "m.json")
    json.dump({"task": "e2e-test", "anchors": [
        {"id": "a1", "type": "file_exists", "path": good},
        {"id": "a2", "type": "py_compile", "path": pyf},
        {"id": "a3", "type": "file_contains", "path": good, "must": "MARKER_TU"},
    ]}, open(manifest, "w"))
    rep = zc.run_manifest(manifest)
    check("E2E vsetky PASS", rep["pass"] == 3 and rep["fail"] == 0)
    check("E2E exit_code 0", zc._exit_code(rep) == 0)

    manifest2 = os.path.join(tmp, "m2.json")
    json.dump({"task": "e2e-fail", "anchors": [
        {"id": "a1", "type": "file_exists", "path": good},
        {"id": "a2", "type": "file_exists", "path": good + ".missing"},
    ]}, open(manifest2, "w"))
    rep2 = zc.run_manifest(manifest2)
    check("E2E mix -> exit 1", zc._exit_code(rep2) == 1)
    check("E2E fail_by_component ma artifact", "artifact" in rep2["fail_by_component"])

    print("== Regresia (EvolveMem revert-on-regression) ==")
    # baseline: manifest kde a1,a2 PASS. Potom zmen tak aby a2 zlyhal -> regresia exit 2.
    reg_manifest = os.path.join(tmp, "reg.json")
    okfile = os.path.join(tmp, "reg_target.txt")
    open(okfile, "w").write("existuje\n")
    json.dump({"task": "reg-test", "anchors": [
        {"id": "r1", "type": "file_exists", "path": good},
        {"id": "r2", "type": "file_exists", "path": okfile},
    ]}, open(reg_manifest, "w"))
    # docasne presmeruj baseline dir do tmp (nesmieme zapisat do ostreho state/)
    orig_bdir = zc.BASELINE_DIR
    zc.BASELINE_DIR = os.path.join(tmp, "baselines")
    try:
        base = zc.save_baseline(reg_manifest)
        check("baseline ulozil oba PASS id", set(base["passed_ids"]) == {"r1", "r2"})
        # teraz znic r2 (zmaz subor) -> r2 padne, co bol PASS -> regresia
        os.remove(okfile)
        rep3 = zc.run_manifest(reg_manifest, regress=True)
        check("regresia detekovana", rep3.get("regression") is True)
        check("regressed obsahuje r2", "r2" in rep3.get("regressed", []))
        check("regresia -> exit_code 2", zc._exit_code(rep3) == 2)
        # kontrola: FAIL bez baseline regresie != exit 2
        rep4 = zc.run_manifest(manifest2, regress=True)  # nema baseline
        check("FAIL bez baseline -> exit 1 (nie 2)", zc._exit_code(rep4) == 1)
    finally:
        zc.BASELINE_DIR = orig_bdir

    print("== CLI subprocess (skutocny beh, nie import) ==")
    p = subprocess.run(["/usr/bin/python3", os.path.join(HERE, "zol_checker.py"),
                        "run", manifest], capture_output=True, text=True)
    check("CLI run exit 0 na PASS manifeste", p.returncode == 0)
    check("CLI vypis je validny JSON", _is_json(p.stdout))
    p2 = subprocess.run(["/usr/bin/python3", os.path.join(HERE, "zol_checker.py"),
                         "run", manifest2], capture_output=True, text=True)
    check("CLI run exit 1 na FAIL manifeste", p2.returncode == 1)

    print("-" * 50)
    if _fails:
        print(f"FAIL: {len(_fails)} zlyhani -> {_fails}")
        return 1
    print("VSETKY TESTY PRESLI")
    return 0


def _is_json(s):
    try:
        json.loads(s)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
