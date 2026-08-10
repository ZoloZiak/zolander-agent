#!/usr/bin/env python3
"""run_tests.py — green-check runner pre Zolander toolkit.

Konvencia (PLAN bod 2): kazde tvrdenie o feature v README musi mat green-check —
test/skript ktory ho DOKAZUJE naostro. Tento runner ich spusti vsetky a da PASS/FAIL
suhrn. Bez green-checku feature patri do Roadmap, nie do "What runs today".

Testy delime na:
  OFFLINE (deterministicke, bez LLM/siete): rychle, bezia vzdy.
  LIVE    (ostre cez realny LLM/embedder): pomalsie; preskoc cez --offline.

Pouzitie:
  /usr/bin/python3 toolkit/run_tests.py            # vsetko (offline + live)
  /usr/bin/python3 toolkit/run_tests.py --offline  # len deterministicke
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, "tests")
VPY = os.path.join(ROOT, ".venv-yar", "bin", "python")
SYS = "/usr/bin/python3"

# (nazov, interpreter, cesta, je_live)
TESTS = [
    ("parser cluster_llm (validacia zoskupenia)", SYS,
     "test_cluster_llm.py", False),
    ("double-take brana (klasifikacia vazne/trivialne)", SYS,
     "test_double_take_gate.py", False),
    ("fold_singletons (L0 zlep vs L2 split)", VPY,
     "test_cluster_fold.py", True),   # potrebuje embed
    ("LLM clustering MERGE+SPLIT (Opus)", VPY,
     "test_llm_cluster_live.py", True),
    ("F4 dream consolidate (Opus, per-tema L1)", SYS,
     "test_dream_consolidate.py", True),
]


def run(interp, script):
    p = subprocess.run([interp, os.path.join(TESTS_DIR, script)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def main():
    offline_only = "--offline" in sys.argv
    results = []
    for name, interp, script, is_live in TESTS:
        if offline_only and is_live:
            results.append((name, "SKIP", ""))
            continue
        code, out, err = run(interp, script)
        tail = (out.strip().splitlines() or [""])[-1]
        status = "PASS" if code == 0 else "FAIL"
        results.append((name, status, tail))

    print("=" * 60)
    print("ZOLANDER GREEN-CHECK" + ("  (offline only)" if offline_only else ""))
    print("=" * 60)
    npass = nfail = nskip = 0
    for name, status, tail in results:
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[skip]"}[status]
        print(f"{mark} {name}")
        if status == "FAIL":
            print(f"       -> {tail}")
        npass += status == "PASS"
        nfail += status == "FAIL"
        nskip += status == "SKIP"
    print("-" * 60)
    print(f"PASS={npass}  FAIL={nfail}  SKIP={nskip}")
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
