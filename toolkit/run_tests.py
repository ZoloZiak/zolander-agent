#!/usr/bin/env python3
"""run_tests.py — green-check runner pre Zolander toolkit.

Konvencia (PLAN bod 2): kazde tvrdenie o feature v README musi mat green-check —
test/skript ktory ho DOKAZUJE naostro. Tento runner ich spusti vsetky a da PASS/FAIL
suhrn. Bez green-checku feature patri do Roadmap, nie do "What runs today".

Testy delime na:
  OFFLINE (deterministicke, bez LLM/siete): rychle, bezia vzdy.
  LIVE    (ostre cez realny LLM/embedder): pomalsie; preskoc cez --offline.

Pouzitie:
  python3 toolkit/run_tests.py            # vsetko (offline + live)
  python3 toolkit/run_tests.py --offline  # len deterministicke
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLKIT = os.path.join(ROOT, "toolkit")
VPY = os.path.join(ROOT, ".venv-yar", "bin", "python")
SYS = sys.executable

# (nazov, interpreter, cesta, je_live)
TESTS = [
    ("anchor-runner zol_checker (12 checkerov PASS+FAIL, E2E, regresia)", SYS,
     "test_checker.py", False),
    ("meta-agent + manifest gen (diagnoza, validacna brana, sablony)", SYS,
     "test_meta.py", False),
    ("parser cluster_llm (validacia zoskupenia)", SYS,
     "test_cluster_llm.py", False),
    ("double-take brana (klasifikacia vazne/trivialne)", SYS,
     "test_double_take_gate.py", False),
    ("dream prompt zachova casove udaje (2608.11775)", SYS,
     "test_dream_preserve_time.py", False),
    ("recall current-state filter (2608.19652)", SYS,
     "test_recall_current_state.py", False),
    ("mem_eval knowledge-gap canaries (2608.26385)", SYS,
     "test_mem_eval_canary.py", False),
    ("structured session recall buckets (2608.08300)", SYS,
     "test_zol_session_structured_recall.py", False),
    ("graph recall expansion opt-in (2608.13334/2608.26983)", SYS,
     "test_recall_graph_expand.py", False),
    ("EARM rerank cache (2608.22767)", SYS,
     "test_mem_rerank_cache.py", False),
    ("Z1 ordinal placement harness (Lorentz ŽL1)", SYS,
     "test_find_roof_z1_eval.py", False),
    ("recall hit telemetry (2608.20631)", SYS,
     "test_recall_hit_telemetry.py", False),
    ("reversible forgetting state (2608.18177)", SYS,
     "test_reversible_forgetting_state.py", False),
    ("IBIA: put() persistuje source (2608.22061)", SYS,
     "test_put_persists_source.py", False),
    ("IBIA: backfill provenance logika (2608.22061)", SYS,
     "test_backfill_provenance_logic.py", False),
    ("MELD: parser znáša odseknutý JSON (2608.16357)", SYS,
     "test_meld_parse_truncated.py", False),
    ("Claim-ledger väzenie: chytá vyvrátené+neoveriteľné tvrdenia", SYS,
     "test_claim_ledger.py", False),
    ("ŽL4 query router: point/aggregate/relation/temporal (kolo30)", SYS,
     "test_query_router.py", False),
    ("ŽL5 when-gate: superseded prefilter pri temporal dotaze (kolo31)", SYS,
     "test_when_gate.py", False),
    ("ŽL3 subtree expansion: aggregate pokrytie témy (kolo28)", SYS,
     "test_subtree_expand.py", False),
    ("F11 guard: sykofancia vs zrkadlo + afektívny kontrakt", SYS,
     "test_f11_guard.py", False),
    ("Judge-scale: ceiling/floor/degenerate cenzúra škály (MoA)", SYS,
     "test_judge_scale.py", False),
    ("Worker-notes scratchpad + skill delta-log (2608.26480/2608.26263)", SYS,
     "test_worker_notes.py", False),
    ("Salience bump + data-readiness gate (2608.20631/ŽL6)", SYS,
     "test_salience_bump.py", False),
    ("Recall routing: router→when_gate/subtree napojený v cmd_recall (ŽL3/4/5)", SYS,
     "test_recall_routing.py", False),
    ("MoA judge-scale audit napojený v zol_eval.evaluate (2608.27309)", SYS,
     "test_moa_judge_scale.py", False),
    ("Salience bump napojený v cmd_decay (WMT/ŽL6 readiness gate)", SYS,
     "test_decay_salience_bump.py", False),
    ("Scaffold gate: deductive bez premís REFUSED, scaffolding istota (spike010)", SYS,
     "test_scaffold_gate.py", False),
    ("fold_singletons (L0 zlep vs L2 split)", VPY,
     "test_cluster_fold.py", True),   # potrebuje embed
    ("LLM clustering MERGE+SPLIT (Opus)", VPY,
     "test_llm_cluster_live.py", True),
    ("F4 dream consolidate (Opus, per-tema L1)", SYS,
     "test_dream_consolidate.py", True),
]


def run(interp, script):
    p = subprocess.run([interp, os.path.join(TOOLKIT, script)],
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
