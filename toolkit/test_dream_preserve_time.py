#!/usr/bin/env python3
"""Regression test for The Sleeping Agent (arXiv 2608.11775).

Dream L0->L1 consolidation must not instruct the model to drop dates/time facts.
The test stubs palantir_client.chat, captures the system prompt, and verifies
that the consolidation prompt preserves temporal information when present.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

captured = {}
fake = types.ModuleType("palantir_client")


def chat(prompt, model="opus", max_tokens=200, system=""):
    captured["prompt"] = prompt
    captured["model"] = model
    captured["system"] = system
    return "2026-08-23: Vedúcko zistil, že dátumy sa pri gist kompresii nesmú stratiť."


setattr(fake, "chat", chat)
sys.modules["palantir_client"] = fake

import zolander_dream as dream  # noqa: E402


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


group = [
    {"id": 1, "text": "2026-08-23 vedúcko zistil, že gist prompt zahadzuje dátumy."},
    {"id": 2, "text": "O deň neskôr chcel zachovať časové údaje v L0→L1 konsolidácii."},
]

out = dream._distill_group(group, model="fake")
if not out:
    fail("_distill_group nevrátil destilát cez stub chat")

system = captured.get("system", "")
system_l = system.lower()

banned = ("ziadny datum", "žiadny dátum", "no date", "drop dates", "bez dátumu")
if any(b in system_l for b in banned):
    fail("system prompt stále zakazuje/odstraňuje dátumy: " + system)

has_preserve = any(x in system_l for x in ("zachovaj", "preserve"))
has_temporal = any(x in system_l for x in ("čas", "cas", "dátum", "datum", "temporal"))
if not (has_preserve and has_temporal):
    fail("system prompt neobsahuje explicitné zachovanie časových údajov: " + system)

print("VYSLEDOK: dream prompt zachováva časové údaje OK")
