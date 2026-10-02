#!/usr/bin/env python3
"""_add_cmdguard_hook.py — one-shot idempotent helper: adds the pre_tool_call
cmd-guard to the hooks block in ~/.hermes/config.yaml.

The Hermes config is text-edited here (not via write_file/patch) on purpose:
it's the one file the agent's own file tools are told to leave alone. Safe to
run repeatedly — if the guard is already wired, it's a no-op.

Path resolution (cross-platform, no hardcoded home):
  1. $ZOLANDER_ROOT/toolkit/hook_cmd_guard.py if ZOLANDER_ROOT is set
  2. else the hook_cmd_guard.py sitting next to THIS file
"""
import os
import sys

CFG = os.path.expanduser("~/.hermes/config.yaml")

root = os.environ.get("ZOLANDER_ROOT")
if root:
    guard = os.path.join(os.path.expanduser(root), "toolkit", "hook_cmd_guard.py")
else:
    guard = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_cmd_guard.py")

# Prefer the interpreter running this script (bootstrap passes its venv python),
# falling back to a system python if that's somehow empty.
PY = sys.executable or "/usr/bin/python3"
GUARD = f"{PY} {guard}"

if not os.path.exists(CFG):
    print(f"CHYBA: {CFG} neexistuje — spusti najprv Hermes aspon raz")
    raise SystemExit(1)

with open(CFG) as f:
    txt = f.read()

if "hook_cmd_guard.py" in txt:
    print("uz je tam — no-op")
    raise SystemExit(0)

if "\nhooks:\n" not in txt and not txt.endswith("hooks:\n") and "hooks:\n" not in txt:
    print("CHYBA: hooks blok nenajdeny — nepridavam naslepo "
          "(skopiruj 'hooks:' blok z README najprv)")
    raise SystemExit(1)

# insert pre_tool_call as the first sub-key right after 'hooks:'
block = (
    "hooks:\n"
    "  pre_tool_call:\n"
    "    - command: " + GUARD + "\n"
    "      matcher: terminal\n"
    "      timeout: 30\n"
)
txt = txt.replace("hooks:\n", block, 1)

with open(CFG, "w") as f:
    f.write(txt)
print("pre_tool_call cmd-guard pridany")
