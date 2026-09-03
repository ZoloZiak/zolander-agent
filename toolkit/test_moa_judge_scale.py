#!/usr/bin/env python3
"""test_moa_judge_scale.py — judge_scale audit napojený do zol_eval.evaluate.

Paper 2608.27309: LLM judgovia natláčajú skóre k okrajom škály (ceiling/floor).
Keď MoA spraví konsenzus zo skóre nalepených na 1.0, konsenzus je falošne vysoký —
nemal rozlišovaciu silu. Tento test dokazuje, že evaluate() teraz volá
judge_scale.audit() na zozbierané per-judge 'celkom' skóre a pripája verdikt do
výstupu ako 'scale_audit', bez zmeny existujúceho kontraktu (celkom/per_judge/agg).

Stubuje palantir_client.chat (žiadny live LLM) → deterministický offline test.
"""
import os
import sys
import types
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_zol_eval_with_scores(scores):
    """Naimportuj zol_eval so stubnutým palantir_client.chat, čo vracia dané skóre.

    scores = list čísel; každý ďalší judge dostane ďalšie číslo (round-robin).
    """
    calls = {"i": 0}

    def _fake_chat(prompt, model=None, system=None, max_tokens=None):
        i = calls["i"]
        val = scores[i % len(scores)]
        calls["i"] += 1
        return ('{"vernost":%s,"vecnost":%s,"ton":%s,"uzitocnost":%s,'
                '"celkom":%s,"dovod":"stub"}' % (val, val, val, val, val))

    pc = types.ModuleType("palantir_client")
    setattr(pc, "chat", _fake_chat)
    sys.modules["palantir_client"] = pc

    if "zol_eval" in sys.modules:
        del sys.modules["zol_eval"]
    import zol_eval
    importlib.reload(zol_eval)
    return zol_eval


def _check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        raise AssertionError(name)


def test_ceiling_censored_flagged():
    """Obaja judgeovia dajú 1.0 → konsenzus 1.0, ale scale_audit hlási CENSORED_CEILING."""
    ze = _load_zol_eval_with_scores([1.0])
    out = ze.evaluate("zadanie", "odpoved", generator="opus")
    _check("celkom kontrakt zachovaný (1.0)", out.get("celkom") == 1.0)
    sa = out.get("scale_audit")
    _check("scale_audit prítomný", isinstance(sa, dict))
    _check("verdikt CENSORED_CEILING", sa.get("verdict") == "CENSORED_CEILING")
    _check("censored=True", sa.get("censored") is True)


def test_degenerate_flagged():
    """Všetky skóre identické (nulový spread) → DEGENERATE."""
    ze = _load_zol_eval_with_scores([0.5])
    out = ze.evaluate("zadanie", "odpoved", generator="opus")
    sa = out.get("scale_audit")
    _check("scale_audit prítomný (degenerate)", isinstance(sa, dict))
    _check("verdikt DEGENERATE", sa.get("verdict") == "DEGENERATE")


def test_healthy_spread_ok():
    """Rôzne skóre (0.3 vs 0.8) → OK, konsenzus dôveryhodný."""
    ze = _load_zol_eval_with_scores([0.3, 0.8])
    out = ze.evaluate("zadanie", "odpoved", generator="opus")
    sa = out.get("scale_audit")
    _check("scale_audit prítomný (ok)", isinstance(sa, dict))
    _check("verdikt OK pri zdravom spreade", sa.get("verdict") == "OK")
    # min agregácia: konsenzus = min(0.3, 0.8) = 0.3
    _check("min agregácia zachovaná", out.get("celkom") == 0.3)


def test_no_scores_no_crash():
    """Keď všetci judgeovia zlyhajú (žiadne skóre), scale_audit nespadne."""
    ze = _load_zol_eval_with_scores([1.0])
    # vynúť zlyhanie: stub chat vráti nezmysel
    import palantir_client
    palantir_client.chat = lambda *a, **k: "toto nie je JSON"
    out = ze.evaluate("zadanie", "odpoved", generator="opus")
    _check("celkom=None keď nič neparsuje", out.get("celkom") is None)
    # scale_audit buď chýba, alebo verdikt NO_DATA — nesmie spadnúť
    sa = out.get("scale_audit")
    _check("scale_audit fail-safe (chýba alebo NO_DATA)",
           sa is None or sa.get("verdict") in ("NO_DATA", "OK"))


if __name__ == "__main__":
    test_ceiling_censored_flagged()
    test_degenerate_flagged()
    test_healthy_spread_ok()
    test_no_scores_no_crash()
    print("PASS moa judge-scale: ceiling/degenerate/healthy/no-data napojené v evaluate()")
