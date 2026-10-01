#!/usr/bin/env python3
"""test_scaffold_gate.py — väzenie proti VATE pri ZÁPISE.

PREČO (2026-09-01, spike 010 VALIDATED): abstrakčný engine generoval vatu, lebo
zapisoval odvodené "princípy" (L3), ktoré NENIESLI premisy a NEDALI sa dohľadať.
Spike 010 dokázal, že epistemická os explicit/deductive JE reprodukovateľná medzi
labmi (κ 0.60). Neuromancer pravidlo (verbatim): "záver sa smie stavať LEN na
záveroch vyššej/rovnej istoty a MUSÍ niesť svoje premisy."

Toto je to pravidlo ako ZÁMOK ZÁPISU (nie nová vrstva, nie LLM na horúcej ceste):
odvodený (deductive) záznam bez dohľadateľných premís vyššej/rovnej istoty sa
NEZAPÍŠE. Explicit (doslovný) prejde vždy — spätná kompatibilita.

TDD RED: tieto testy definujú kontrakt PRED existenciou scaffold_gate.py.
"""
import os
import sys

ROOT = os.path.expanduser("~/projects/zolander")
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
from scaffold_gate import evaluate, ACCEPT, REFUSED  # noqa: E402


def _fake_resolver(store):
    """store: {id -> {'certainty':..., 'text':...}}. Vráti resolver callable."""
    def _resolve(premise):
        return store.get(premise)
    return _resolve


# --- Explicit prejde VŽDY (doslovný fakt, netreba premisy) ---

def test_missing_certainty_defaults_explicit_accepts():
    # Spätná kompatibilita: existujúce volania cmd_remember NEposielajú certainty.
    dec, _ = evaluate({"text": "vedúcko býva Ulica 1/1"}, _fake_resolver({}))
    assert dec == ACCEPT


def test_explicit_accepts_without_premises():
    dec, _ = evaluate({"text": "PESEL 98041111339", "certainty": "explicit"},
                      _fake_resolver({}))
    assert dec == ACCEPT


# --- Deductive BEZ premís = VATA = REFUSED (jadro väzenia) ---

def test_deductive_without_premises_refused():
    dec, reason = evaluate(
        {"text": "vedúcko je typ čo neznáša placebo", "certainty": "deductive"},
        _fake_resolver({}))
    assert dec == REFUSED
    assert "premis" in reason.lower()


def test_deductive_empty_premises_refused():
    dec, _ = evaluate(
        {"text": "X plynie z Y", "certainty": "deductive", "premises": []},
        _fake_resolver({}))
    assert dec == REFUSED


# --- Deductive s NEDOHĽADATEĽNOU premisou = REFUSED (nesmie visieť vo vzduchu) ---

def test_deductive_unresolvable_premise_refused():
    dec, reason = evaluate(
        {"text": "záver", "certainty": "deductive", "premises": [99999]},
        _fake_resolver({}))  # prázdny store -> 99999 nenájdené
    assert dec == REFUSED
    assert "99999" in reason


# --- Deductive s platnou explicit premisou = ACCEPT ---

def test_deductive_on_explicit_premise_accepts():
    store = {101: {"certainty": "explicit", "text": "statín myopatia"}}
    dec, _ = evaluate(
        {"text": "vedúcko potrebuje statín bez myopatie",
         "certainty": "deductive", "premises": [101]},
        _fake_resolver(store))
    assert dec == ACCEPT


def test_deductive_on_deductive_premise_accepts():
    # deductive sa smie oprieť o deductive (rovná istota) — scaffolding OK.
    store = {202: {"certainty": "deductive", "text": "medzikrok"}}
    dec, _ = evaluate(
        {"text": "ďalší krok", "certainty": "deductive", "premises": [202]},
        _fake_resolver(store))
    assert dec == ACCEPT


# --- SCAFFOLDING PRAVIDLO: záver sa NESMIE stavať na NIŽŠEJ istote ---

def test_deductive_cannot_build_on_inductive_refused():
    store = {303: {"certainty": "inductive", "text": "pravdepodobný vzor"}}
    dec, reason = evaluate(
        {"text": "istý záver z domnienky", "certainty": "deductive",
         "premises": [303]},
        _fake_resolver(store))
    assert dec == REFUSED
    assert "istot" in reason.lower() or "inductive" in reason.lower()


def test_deductive_mixed_premises_one_too_low_refused():
    # jedna dobrá + jedna nižšia = REFUSED (najslabší článok rozhoduje)
    store = {401: {"certainty": "explicit", "text": "fakt"},
             402: {"certainty": "abductive", "text": "domnienka"}}
    dec, _ = evaluate(
        {"text": "záver", "certainty": "deductive", "premises": [401, 402]},
        _fake_resolver(store))
    assert dec == REFUSED


# --- Neznámy certainty = REFUSED (nie tiché prepustenie) ---

def test_unknown_certainty_refused():
    dec, _ = evaluate(
        {"text": "?", "certainty": "vibes", "premises": [1]},
        _fake_resolver({1: {"certainty": "explicit", "text": "x"}}))
    assert dec == REFUSED


# --- KILL-SWITCH: aktívne s vypínačom, nie mŕtvy flag ---

def test_kill_switch_bypasses_gate():
    os.environ["ZOL_SCAFFOLD_GATE"] = "0"
    try:
        dec, reason = evaluate(
            {"text": "vata bez premis", "certainty": "deductive"},
            _fake_resolver({}))
        assert dec == ACCEPT
        assert "kill" in reason.lower() or "vypnut" in reason.lower()
    finally:
        del os.environ["ZOL_SCAFFOLD_GATE"]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"[PASS] {_name}")
    print("OK — scaffold gate: vata bez premis REFUSED, explicit prejde, "
          "scaffolding istota vynútená, kill-switch funguje.")
