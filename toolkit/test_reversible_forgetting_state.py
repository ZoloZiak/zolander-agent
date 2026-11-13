#!/usr/bin/env python3
"""Offline test for Reversible Forgetting (arXiv 2608.18177) state helper.

Decay must expose a reversible dormant/retired_candidate state before any hard delete.
Durable memory kinds must never be classified for forgetting.
"""
import importlib.util
import os
import sys
import types

_ey = types.ModuleType("embed_yar")
setattr(_ey, "embed_one", lambda text: [0.0] * 129)
sys.modules["embed_yar"] = _ey
_zp = types.ModuleType("zol_paths")
setattr(_zp, "NODE", "node")
setattr(_zp, "HS", "hs.mjs")
setattr(_zp, "NODE_ENV", {})
setattr(_zp, "ZROOT", "/tmp")
sys.modules["zol_paths"] = _zp

TK = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("zol_mem", os.path.join(TK, "zol_mem.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("neviem načítať zol_mem.py")
zm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zm)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


print("=== Reversible forgetting state ===")
state = getattr(zm, "_forget_state", None)
if state is None:
    fail("zol_mem._forget_state neexistuje")

if state("semantic", age_days=999, salience=0.0) != "active":
    fail("semantic/procedural/identity durable kinds nemajú padať do forgetting state")
if state("episodic", age_days=1, salience=0.0) != "active":
    fail("mladá epizóda má zostať active aj pri nízkej salience")
if state("episodic", age_days=20, salience=0.10) != "dormant":
    fail("staršia low-salience epizóda má byť dormant, nie hard delete")
if state("episodic", age_days=80, salience=0.04) != "retired_candidate":
    fail("veľmi stará low-salience epizóda má byť retired_candidate")

print("VYSLEDOK: reversible forgetting state OK")
