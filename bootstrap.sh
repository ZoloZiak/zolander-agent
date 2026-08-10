#!/usr/bin/env bash
# bootstrap.sh — one-shot installer for a fresh Zolander agent.
#
# Stands up the PUBLIC, copyable stack:
#   Hermes Agent  ->  HyperspaceDB (Docker)  ->  this toolkit  ->  your own
#   identity key, integrity manifest, memory collections, and launchd daemons.
#
# It deliberately does NOT wire any LLM provider or secrets. You pick your own
# model with `hermes model` afterwards. The author's private Palantir/corp
# layer lives outside this repo and is never published.
#
# Usage:   bash bootstrap.sh            (interactive-safe, idempotent)
# Re-runs are safe: every step checks before it acts.
set -euo pipefail

ROOT="${ZOLANDER_ROOT:-$HOME/zolander}"
REPO_URL="${ZOLANDER_REPO:-https://github.com/ZoloZiak/zolander-agent.git}"
HS_IMAGE="glukhota/hyperspace-db"
HS_PORT="${HS_PORT:-50051}"
NODE_MODULES="${NODE_PATH:-}"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 0. prereqs -------------------------------------------------------------
say "Checking prerequisites"
have curl || die "curl is required"
have git  || die "git is required"
have python3 || die "python3 is required"
if ! have docker; then
  warn "docker not found — install Docker/OrbStack, then re-run. HyperspaceDB needs it."
fi

# --- 1. Hermes Agent --------------------------------------------------------
if have hermes; then
  say "Hermes already installed ($(hermes --version 2>/dev/null || echo '?')) — skipping"
else
  say "Installing Hermes Agent (official installer, always latest)"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  have hermes || warn "hermes not on PATH yet — open a new shell or source your profile"
fi

# --- 2. HyperspaceDB --------------------------------------------------------
if have docker; then
  if docker ps --format '{{.Names}}' | grep -q '^hyperspace$'; then
    say "HyperspaceDB container already running — skipping"
  else
    say "Starting HyperspaceDB on :$HS_PORT"
    docker run -d --name hyperspace -p "${HS_PORT}:50051" --restart unless-stopped "$HS_IMAGE" \
      || warn "HyperspaceDB start failed — check 'docker logs hyperspace'"
  fi
fi

# --- 3. toolkit -------------------------------------------------------------
if [ -d "$ROOT/.git" ]; then
  say "Toolkit present at $ROOT — pulling latest (no fork, always HEAD)"
  git -C "$ROOT" pull --ff-only || warn "git pull failed — resolve manually"
else
  say "Cloning toolkit -> $ROOT"
  git clone "$REPO_URL" "$ROOT"
fi
mkdir -p "$ROOT/state" "$ROOT/logs" "$ROOT/denniky" "$ROOT/identity"

# --- 4. identity + integrity ------------------------------------------------
say "Identity key (idempotent — never overwrites an existing key)"
python3 "$ROOT/toolkit/gen_identity.py"
say "Recording integrity manifest"
python3 "$ROOT/toolkit/integrity.py" write

# --- 5. memory collections --------------------------------------------------
if [ -n "$NODE_MODULES" ]; then
  say "Creating memory collections (zol_mem)"
  python3 "$ROOT/toolkit/zol_mem.py" init || warn "collection init failed — is HyperspaceDB up + NODE_PATH set?"
else
  warn "NODE_PATH not set — skipping collection init. Set it and run: python3 $ROOT/toolkit/zol_mem.py init"
fi

# --- 6. launchd daemons (macOS) --------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
  say "Rendering launchd templates for user '$USER'"
  LA="$HOME/Library/LaunchAgents"
  mkdir -p "$LA"
  for tpl in "$ROOT"/toolkit/pl.zolander.*.plist.template; do
    [ -e "$tpl" ] || continue
    name="$(basename "$tpl" .template)"
    sed "s/__USER__/$USER/g" "$tpl" > "$LA/$name"
    label="${name%.plist}"
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LA/$name" && say "loaded $label" || warn "could not load $label"
  done
else
  warn "Non-macOS host — launchd daemons skipped. Port the templates to systemd/cron yourself."
fi

# --- 6b. optional: Palantir Foundry LLM proxy ------------------------------
# Off unless you ask for it. Wires Claude/GPT/Gemini via your own Foundry
# server + token (prompted, never stored in this repo). Skip and use any of
# Hermes' 20+ providers instead with `hermes model`.
if [ "${ZOLANDER_PALANTIR:-}" = "1" ]; then
  say "Configuring Palantir providers (interactive)"
  python3 "$ROOT/toolkit/configure_palantir.py" || warn "Palantir wiring failed — re-run toolkit/configure_palantir.py"
else
  warn "Palantir wiring skipped. To enable: ZOLANDER_PALANTIR=1 bash bootstrap.sh"
  warn "  (or run it later:  python3 $ROOT/toolkit/configure_palantir.py)"
fi

# --- 6c. skills from their own sources (no forks) ---------------------------
if [ -x "$ROOT/toolkit/fetch_skills.sh" ] || [ -f "$ROOT/toolkit/fetch_skills.sh" ]; then
  say "Fetching skills from their origins (hub + your GitHub)"
  bash "$ROOT/toolkit/fetch_skills.sh" || warn "skill fetch had failures — see output above"
fi

# --- 7. next steps ----------------------------------------------------------
cat <<EONEXT

$(say "Done. Zolander scaffolding is in place.")
Next, YOU wire the parts this installer deliberately left open:

  1. Pick your LLM provider:     hermes model
  2. Wire the recall/verify hooks into ~/.hermes/config.yaml
     (see the 'hooks:' block in this repo's README).
  3. Paste your pubkey+fingerprint into skills/zolander/SKILL.md,
     then re-run:                python3 $ROOT/toolkit/integrity.py write
  4. (Optional) messaging gateway: hermes gateway setup

Secrets, corp proxies and any private LLM wiring are NOT handled here by design.
EONEXT
