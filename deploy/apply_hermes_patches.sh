#!/usr/bin/env bash
# apply_hermes_patches.sh — apply the Palantir strict-proxy fixes onto a stock Hermes.
#
# WHY THIS EXISTS
#   Hermes is installed fresh from the official installer (always latest upstream).
#   A handful of fixes this agent needs for the Palantir Foundry LLM proxy are NOT
#   yet merged upstream (they're open/closed PRs on NousResearch/hermes-agent). Without
#   them, a Palantir provider is configurable but the FIRST tool call or Gemini request
#   dies with HTTP 400/422 and the session loops until /new. These patches close that gap.
#
#   They are plain `git format-patch` files under deploy/hermes-patches/. This script
#   applies the ones that still apply cleanly and SKIPS (never force-jams) any that a
#   newer upstream has refactored out from under — so you never end up with conflict
#   markers in your Hermes tree. Re-running is safe (already-applied patches are detected
#   and skipped). Run it again after every `hermes update`.
#
# USAGE
#   bash apply_hermes_patches.sh                 # auto-detects the Hermes checkout
#   HERMES_SRC=/path/to/hermes-agent bash apply_hermes_patches.sh
#
# EXIT: always 0 (best-effort). Reports a summary; Palantir works if the strict-proxy
#       ones (01,02,03,04,05,12,13) applied or were already present.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="$SCRIPT_DIR/hermes-patches"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
skip() { printf '  \033[1;33m•\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }

# --- locate the Hermes git checkout -----------------------------------------
# A git checkout has a .git DIRECTORY; a git WORKTREE has a .git FILE pointing at
# the real gitdir. Accept both so HERMES_SRC can point at either.
is_git_tree() { [ -e "$1/.git" ]; }

find_hermes_src() {
  if [ -n "${HERMES_SRC:-}" ] && is_git_tree "$HERMES_SRC"; then
    echo "$HERMES_SRC"; return 0
  fi
  for c in "$HOME/.hermes/hermes-agent" \
           "$HOME/.local/share/hermes/hermes-agent" \
           "$HOME/.local/pipx/venvs/hermes-agent"; do
    is_git_tree "$c" && { echo "$c"; return 0; }
  done
  # fall back: ask the installed hermes where it lives
  local p
  p="$(python3 - <<'PY' 2>/dev/null
import importlib.util, os
s = importlib.util.find_spec("run_agent") or importlib.util.find_spec("hermes_bootstrap")
if s and s.origin:
    d = os.path.dirname(s.origin)
    if os.path.isdir(os.path.join(d, ".git")):
        print(d)
PY
)"
  [ -n "$p" ] && { echo "$p"; return 0; }
  return 1
}

SRC="$(find_hermes_src || true)"
if [ -z "$SRC" ]; then
  warn "Hermes git checkout not found (looked in ~/.hermes/hermes-agent and others)."
  warn "Set HERMES_SRC=/path/to/hermes-agent and re-run. Skipping core patches."
  warn "Palantir may 400/422 until these are applied — other providers are unaffected."
  exit 0
fi
say "Patching Hermes core at: $SRC"

if [ ! -d "$PATCH_DIR" ]; then
  warn "No patch dir at $PATCH_DIR — nothing to apply."
  exit 0
fi

applied=0; already=0; skipped=0
for patch in "$PATCH_DIR"/*.patch; do
  [ -e "$patch" ] || continue
  name="$(basename "$patch")"

  # already applied? (reverse-check succeeds => the change is already in the tree)
  if git -C "$SRC" apply --reverse --check "$patch" >/dev/null 2>&1; then
    already=$((already+1)); skip "$name (already present)"; continue
  fi
  # applies cleanly as-is? (plain only — we NEVER 3-way, because a conflicted
  # 3-way apply leaves conflict markers in the tree that are fiddly to revert
  # cleanly. A patch upstream has refactored past is skipped honestly, never
  # force-jammed. Your Hermes tree always stays clean and importable.)
  if git -C "$SRC" apply --check "$patch" >/dev/null 2>&1; then
    if git -C "$SRC" apply "$patch" >/dev/null 2>&1; then
      applied=$((applied+1)); ok "$name"
    else
      skipped=$((skipped+1)); warn "$name (apply failed late — skipped)"
    fi
    continue
  fi
  skipped=$((skipped+1))
  skip "$name (upstream moved; skipped — likely already fixed or needs a rebase)"
done

say "Core patches: $applied applied, $already already present, $skipped skipped"

# --- LOUD verify: are the Palantir-critical fixes ACTUALLY in the tree? -------
# A skipped patch is silent by nature: Palantir then 400/422s at runtime with no
# clue why. So instead of trusting "applied/skipped" counts, we grep the tree for
# a distinctive symbol of each CRITICAL fix. Present (whether via our patch or
# because upstream already shipped it) = good. Absent = this fix is NOT in your
# Hermes and the named Palantir path WILL break — we say so loudly and exit non-zero.
# Format: LABEL|symbol|file|impact-if-missing
CRITICAL="\
GEMINI_422_nulls|_strip_nulls|agent/gemini_native_adapter.py|Gemini tool-results 422 (null in functionResponse)
GEMINI_422_role|joined_system|agent/gemini_native_adapter.py|every Gemini request 422 (role in systemInstruction)
GEMINI_proxy_auth|/api/v2/llm/proxy/google|agent/auxiliary_client.py|Gemini proxy routing/bearer broken
GPT5_dotted_RID|dot_tail|utils.py|gpt-5 proxy 400 on every compaction (max_tokens vs max_completion_tokens)
REASONING_strip|strip_reasoning_details_for_non_openrouter|agent/message_sanitization.py|tool-call 400 on strict proxy (reasoning_details leak)
REASONING_wire|strip_reasoning_details_for_non_openrouter|agent/turn_api_request.py|reasoning_details strip not wired into the turn loop"

missing=0
say "Verifying Palantir-critical fixes are present in the tree"
while IFS='|' read -r label sym file impact; do
  [ -n "$label" ] || continue
  if git -C "$SRC" grep -q -F "$sym" -- "$file" 2>/dev/null; then
    ok "$label present"
  else
    missing=$((missing+1))
    warn "MISSING: $label  —  $impact"
    warn "         (expected symbol \`$sym\` in $file)"
  fi
done <<EOF
$CRITICAL
EOF

if [ "$missing" -gt 0 ]; then
  printf '\n\033[1;31m[x]\033[0m %s\n' "$missing critical Palantir fix(es) are NOT in your Hermes tree."
  printf '\033[1;31m   \033[0m %s\n' "Palantir WILL fail on the paths listed above (400/422), silently, at runtime."
  printf '\033[1;31m   \033[0m %s\n' "A fix went missing because a newer upstream refactored past its patch."
  printf '\033[1;31m   \033[0m %s\n' "ACTION: re-cut that patch against current upstream (git format-patch of the"
  printf '\033[1;31m   \033[0m %s\n' "fix), or check whether upstream already shipped an equivalent. Do NOT ship"
  printf '\033[1;31m   \033[0m %s\n' "this install as 'Palantir works' until this is green."
  exit 3
fi

say "All Palantir-critical fixes present ✓"
if [ "$skipped" -gt 0 ]; then
  warn "$skipped non-critical patch(es) were skipped (cosmetic/vision/aux) — Palantir core is fine."
fi
exit 0
