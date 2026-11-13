#!/usr/bin/env bash
# bootstrap.sh — one-shot, cross-platform installer for a fresh Zolander agent.
#
# Stands up the whole copyable stack, step by step, and tells you what it's doing:
#   Hermes Agent -> this toolkit -> a Python venv with all
#   deps -> the Node bridge -> your own identity key + integrity manifest -> memory
#   collection -> background daemons (systemd --user on Linux, launchd on macOS).
#
# It wires NO LLM provider and NO secrets by default — you pick your model with
# `hermes model` afterwards, or opt into the free Palantir Foundry proxy (step 6b).
# There is NO TLS-proxy / custom-CA / proxy layer anywhere in here; it uses
# your system trust store like any normal program.
#
# Works on:  Linux (systemd user services)  and  macOS (launchd).
# Usage:     bash bootstrap.sh          (idempotent — re-runs are safe)
set -euo pipefail

# --- config (override via env) ----------------------------------------------
# ROOT must match where the toolkit scripts look for state/identity/toolkit:
# ~40 of them hardcode os.path.expanduser("~/projects/zolander/..."). Keep this
# default in sync with that, or recall/identity/memory silently read an empty
# path. Override with ZOLANDER_ROOT only if you also set it in the daemon env.
ROOT="${ZOLANDER_ROOT:-$HOME/projects/zolander}"
export ZOLANDER_ROOT="$ROOT"
REPO_URL="${ZOLANDER_REPO:-https://github.com/ZoloZiak/zolander-agent.git}"
HS_IMAGE="${HS_IMAGE:-glukhota/hyperspace-db}"
HS_PORT="${HS_PORT:-50051}"
VENV="${ZOLANDER_VENV:-$HOME/.venv-zolander}"
# Skip the heavy torch/transformers embedder install with ZOLANDER_SKIP_EMBED=1
SKIP_EMBED="${ZOLANDER_SKIP_EMBED:-0}"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
step() { printf '\033[1;35m  ·\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Directory this script lives in (empty/unreliable when run via `curl | bash`,
# in which case the repo is cloned to $ROOT at step 2 and we use that instead).
SELF_DIR=""
if [ -n "${BASH_SOURCE:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

OS="$(uname -s)"
case "$OS" in
  Linux)  PLATFORM="linux" ;;
  Darwin) PLATFORM="macos" ;;
  *)      PLATFORM="other" ;;
esac
say "Zolander installer — detected platform: $PLATFORM ($OS)"

# --- 0. prereqs -------------------------------------------------------------
say "0/9  Checking prerequisites"
have curl || die "curl is required"
have git  || die "git is required"
have python3 || die "python3 is required (3.10+)"
have node || warn "node not found — the memory bridge needs it. Install Node 18+ and re-run."
have npm  || warn "npm not found — needed to install the HyperspaceDB SDK."
have cargo || warn "cargo/Rust not found — needed to build the native HyperspaceDB binary (step 4). rustup installs it automatically, or set ZOLANDER_HS_DOCKER=1 to use Docker instead."

# --- 1. Hermes Agent --------------------------------------------------------
say "1/9  Hermes Agent"
if have hermes; then
  step "already installed ($(hermes --version 2>/dev/null || echo '?')) — skipping"
else
  step "installing via the official installer (always latest)"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  have hermes || warn "hermes not on PATH yet — open a new shell or source your profile"
fi

# --- 2. toolkit (clone/update first, so the rest can use it) ----------------
say "2/9  Toolkit"
if [ -d "$ROOT/.git" ]; then
  step "present at $ROOT — pulling latest"
  git -C "$ROOT" pull --ff-only || warn "git pull failed — resolve manually"
elif [ -d "$ROOT" ] && [ -f "$ROOT/toolkit/zol_mem.py" ]; then
  step "found a non-git toolkit at $ROOT — using it as-is"
else
  step "cloning $REPO_URL -> $ROOT"
  git clone "$REPO_URL" "$ROOT"
fi
mkdir -p "$ROOT/state" "$ROOT/logs" "$ROOT/denniky" "$ROOT/identity"

# --- 3. Python venv + deps --------------------------------------------------
say "3/9  Python environment ($VENV)"
if [ ! -d "$VENV" ]; then
  step "creating virtualenv"
  python3 -m venv "$VENV"
fi
PY="$VENV/bin/python"
step "upgrading pip"
"$PY" -m pip install --quiet --upgrade pip
if [ "$SKIP_EMBED" = "1" ]; then
  step "installing core deps only (ZOLANDER_SKIP_EMBED=1 — no torch/transformers)"
  "$PY" -m pip install --quiet "cryptography>=42.0" "numpy>=1.26" \
    || warn "core dep install had issues — see output"
else
  step "installing all deps from requirements.txt (torch/transformers are large, be patient)"
  "$PY" -m pip install --quiet -r "$ROOT/requirements.txt" \
    || warn "dep install had issues — re-run: $PY -m pip install -r $ROOT/requirements.txt"
fi
step "toolkit will run under: $PY"

# --- 3b. embedder model (YAR 129D Lorentz) ----------------------------------
# embed_yar.py uses a local copy if present (~/models/yar_v5_embedding, offline),
# else downloads YARlabs/v5_Embedding_0.5B (Apache-2.0, ~1.2 GB) on first use.
# Pre-fetch it here so the FIRST recall isn't a multi-minute stall. Fail-soft:
# if this is skipped, embed_yar.py still pulls it lazily at first call.
if [ "$SKIP_EMBED" != "1" ]; then
  say "3b/9 Embedder model (YARlabs/v5_Embedding_0.5B, ~1.2 GB first time)"
  if [ -d "$HOME/models/yar_v5_embedding" ]; then
    step "local copy present (~/models/yar_v5_embedding) — using it offline"
  else
    step "pre-fetching from Hugging Face (one-time; recall needs it)"
    # No local dir -> embed_yar.py resolves to the HF repo and downloads it.
    "$PY" "$ROOT/toolkit/embed_yar.py" warm \
      || warn "model pre-fetch had issues — it will download lazily on first recall"
  fi
fi

# --- 4. HyperspaceDB (native-on-metal by default, Docker opt-in) ------------
say "4/9  HyperspaceDB (vector store) on :$HS_PORT"
# Two ways to run it; they both bind :50051, so pick ONE:
#   - DEFAULT: compile the Rust source and run bare-metal (no Docker), the way the
#     author's Mac runs it under launchd. Native SIMD/NEON, no container overhead.
#   - ZOLANDER_HS_DOCKER=1: run the prebuilt container instead (portable, zero build).
if [ "${ZOLANDER_HS_DOCKER:-0}" != "1" ]; then
  NATIVE_SH=""
  for d in "$SELF_DIR" "$ROOT"; do
    [ -n "$d" ] && [ -f "$d/deploy/build_hyperspace_native.sh" ] && { NATIVE_SH="$d/deploy/build_hyperspace_native.sh"; break; }
  done
  if [ -n "$NATIVE_SH" ]; then
    step "native build (default) — compiling HyperspaceDB from Rust source"
    bash "$NATIVE_SH" build || warn "native build failed — see output; or use Docker with ZOLANDER_HS_DOCKER=1"
    step "built. Start it (foreground) with: bash $NATIVE_SH run"
    step "  or wire it into launchd/systemd for 24/7 (see README). Not auto-started here."
  else
    warn "deploy/build_hyperspace_native.sh not found — skipping (or use ZOLANDER_HS_DOCKER=1)"
  fi
elif have docker; then
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^hyperspace$'; then
    step "container already running — skipping"
  elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^hyperspace$'; then
    step "container exists but stopped — starting"
    docker start hyperspace || warn "could not start existing container — check 'docker logs hyperspace'"
  else
    step "starting a fresh container"
    docker run -d --name hyperspace -p "${HS_PORT}:50051" --restart unless-stopped "$HS_IMAGE" \
      || warn "HyperspaceDB start failed — check 'docker logs hyperspace'"
  fi
else
  warn "ZOLANDER_HS_DOCKER=1 set but docker missing — install Docker and re-run, or use the"
  warn "  native default (unset ZOLANDER_HS_DOCKER): compiles the Rust source instead."
fi

# --- 5. Node bridge (HyperspaceDB SDK) --------------------------------------
say "5/9  Node bridge (hs.mjs + HyperspaceDB SDK)"
if have npm; then
  step "installing the SDK next to the toolkit (toolkit/node_modules)"
  ( cd "$ROOT/toolkit" && npm install --silent --no-audit --no-fund ) \
    || warn "npm install failed — run it by hand in $ROOT/toolkit"
  export NODE_PATH="$ROOT/toolkit/node_modules"
else
  warn "npm missing — install Node 18+ and run: (cd $ROOT/toolkit && npm install)"
fi

# --- 6. identity + integrity + memory collection ----------------------------
say "6/9  Identity key + integrity manifest"
step "generating identity (idempotent — never overwrites an existing key)"
"$PY" "$ROOT/toolkit/gen_identity.py"
step "recording integrity manifest"
"$PY" "$ROOT/toolkit/integrity.py" write

say "     Memory collection (zol_mem)"
if [ -n "${NODE_PATH:-}" ] && have node; then
  step "creating collection"
  "$PY" "$ROOT/toolkit/zol_mem.py" init \
    || warn "collection init failed — is HyperspaceDB up (docker ps) and NODE_PATH set?"
else
  warn "NODE_PATH/node not ready — create it later: NODE_PATH=$ROOT/toolkit/node_modules $PY $ROOT/toolkit/zol_mem.py init"
fi

# --- 6b. optional: Palantir Foundry LLM proxy -------------------------------
# Foundry's free AIP Developer Tier exposes Claude/GPT/Gemini behind one proxy.
# Opt in with ZOLANDER_PALANTIR=1 (+ PALANTIR_HOST + PALANTIR_TOKEN for non-interactive),
# ZOLANDER_PALANTIR=0 to skip silently, or answer the prompt. Secrets go to
# ~/.hermes/.env (0600), never this repo. No Palantir? Pick any provider with `hermes model`.
say "6b/9 Optional LLM provider (Palantir Foundry)"
do_palantir=0
if [ "${ZOLANDER_PALANTIR:-}" = "1" ]; then do_palantir=1
elif [ "${ZOLANDER_PALANTIR:-}" = "0" ]; then do_palantir=0
elif [ -t 0 ]; then
  read -r -p "  Wire a free Palantir Foundry LLM proxy now? [y/N] " _ans
  case "$_ans" in [Yy]*) do_palantir=1 ;; esac
fi
if [ "$do_palantir" = "1" ]; then
  step "configuring Palantir providers (prompts for host + token)"
  "$PY" "$ROOT/toolkit/configure_palantir.py" || warn "Palantir wiring failed — re-run toolkit/configure_palantir.py"
else
  step "skipped — pick a model later with: hermes model"
  step "  (or wire Palantir anytime: $PY $ROOT/toolkit/configure_palantir.py)"
fi

# --- 6c. skills from their own sources (no forks) ---------------------------
if [ -f "$ROOT/toolkit/fetch_skills.sh" ]; then
  say "6c/9 Skills (from their own origins — no forks)"
  bash "$ROOT/toolkit/fetch_skills.sh" || warn "skill fetch had failures — see output above"
fi

# --- 7. background daemons --------------------------------------------------
say "7/9  Background daemons ($PLATFORM)"
render() { sed -e "s#__USER__#$USER#g" -e "s#__PY__#$PY#g" -e "s#__ROOT__#$ROOT#g" "$1"; }

if [ "$PLATFORM" = "linux" ]; then
  if have systemctl; then
    UD="$HOME/.config/systemd/user"
    mkdir -p "$UD"
    step "rendering systemd --user units -> $UD"
    for unit in "$ROOT"/deploy/systemd/zolander-*.service "$ROOT"/deploy/systemd/zolander-*.timer; do
      [ -e "$unit" ] || continue
      render "$unit" > "$UD/$(basename "$unit")"
    done
    systemctl --user daemon-reload || warn "systemctl daemon-reload failed"
    for t in loop watchdog dream brief; do
      systemctl --user enable --now "zolander-$t.timer" 2>/dev/null \
        && step "enabled zolander-$t.timer" || warn "could not enable zolander-$t.timer"
    done
    warn "systemd --user timers only run while you're logged in. For 24/7 run:"
    warn "  sudo loginctl enable-linger $USER"
  else
    warn "no systemctl — port deploy/systemd/*.timer to cron yourself (see README)."
  fi
elif [ "$PLATFORM" = "macos" ]; then
  LA="$HOME/Library/LaunchAgents"
  mkdir -p "$LA"
  step "rendering launchd templates -> $LA"
  for tpl in "$ROOT"/toolkit/pl.zolander.*.plist.template; do
    [ -e "$tpl" ] || continue
    name="$(basename "$tpl" .template)"
    # templates hardcode /usr/bin/python3 + ~/zolander layout; rewrite to venv + ROOT
    sed -e "s#__USER__#$USER#g" \
        -e "s#/usr/bin/python3#$PY#g" \
        -e "s#/Users/$USER/zolander#$ROOT#g" "$tpl" > "$LA/$name"
    label="${name%.plist}"
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LA/$name" && step "loaded $label" || warn "could not load $label"
  done
else
  warn "unknown platform — port deploy/systemd/*.timer or toolkit/*.plist.template to your init system."
fi

# --- 8. hooks hint ----------------------------------------------------------
say "8/9  Hermes hooks (optional, recommended)"
step "wire recall/verify hooks into ~/.hermes/config.yaml — see the 'hooks:' block in the README"
step "paths there use PY=$PY and ROOT=$ROOT"

# --- 9. done ----------------------------------------------------------------
say "9/9  Done. Zolander scaffolding is in place."
cat <<EONEXT

Next, YOU wire the parts this installer deliberately left open:

  1. Pick your LLM provider:     hermes model
  2. Wire the recall/verify hooks into ~/.hermes/config.yaml
     (copy the 'hooks:' block from the README; paths use $PY and $ROOT).
  3. Paste your pubkey+fingerprint into skills/zolander/SKILL.md,
     then re-run:                $PY $ROOT/toolkit/integrity.py write
  4. (Optional) messaging gateway: hermes gateway setup

Toolkit python:  $PY
Toolkit root:    $ROOT
Secrets, proxies and private LLM wiring are NOT handled here by design.
EONEXT
