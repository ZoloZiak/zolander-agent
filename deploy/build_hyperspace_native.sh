#!/usr/bin/env bash
# build_hyperspace_native.sh — compile HyperspaceDB from Rust source and run it
# as a NATIVE binary (no Docker), the way the author's Mac runs it under launchd.
#
# Why: bootstrap.sh step 4 starts HyperspaceDB in Docker (portable, zero build).
# This is the OTHER option — bare-metal — for boxes without Docker, or where you
# want the native-on-metal performance (SIMD/NEON, no container overhead).
# They are mutually exclusive: both bind :50051. Pick ONE.
#
# HyperspaceDB is Rust (nightly). Source: github.com/YARlabs/hyperspace-db (MIT).
# Build artifact: ./target/release/hyperspace-server  (gRPC :50051, HTTP :50050).
#
# Usage:
#   bash deploy/build_hyperspace_native.sh            # clone+build+smoke-test
#   HS_SRC=~/src/hyperspace-db bash ... build         # reuse an existing checkout
#   HS_PORT=50051 bash ... run                        # just run an already-built binary
#
# Idempotent: re-running skips the clone if present and rebuilds incrementally.
set -euo pipefail

HS_REPO="${HS_REPO:-https://github.com/YARlabs/hyperspace-db.git}"
HS_SRC="${HS_SRC:-$HOME/src/hyperspace-db}"
HS_PORT="${HS_PORT:-50051}"
HS_HTTP_PORT="${HS_HTTP_PORT:-50050}"
HS_DATA="${HS_DATA:-${ZOLANDER_ROOT:-$HOME/projects/zolander}/state/hyperspace_data}"
BIN="$HS_SRC/target/release/hyperspace-server"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
step() { printf '\033[1;35m  ·\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

ensure_rust() {
  if have cargo; then return; fi
  warn "cargo not found — installing Rust via rustup (needs network)"
  have curl || die "curl required to install Rust"
  curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain nightly
  # shellcheck disable=SC1091
  . "$HOME/.cargo/env" 2>/dev/null || export PATH="$HOME/.cargo/bin:$PATH"
  have cargo || die "cargo still not on PATH — open a new shell and re-run"
}

do_build() {
  ensure_rust
  if [ -d "$HS_SRC/.git" ]; then
    step "source present at $HS_SRC — pulling latest"
    git -C "$HS_SRC" pull --ff-only || warn "git pull failed — building current checkout"
  else
    step "cloning $HS_REPO -> $HS_SRC"
    mkdir -p "$(dirname "$HS_SRC")"
    git clone --depth 1 "$HS_REPO" "$HS_SRC"
  fi
  # rust-toolchain.toml in the repo pins nightly; cargo honours it automatically.
  say "Building release binary (first build is slow: many crates, nightly Rust)"
  ( cd "$HS_SRC" && cargo build --release ) || die "cargo build failed — see output above"
  [ -x "$BIN" ] || die "build finished but $BIN is missing — did the binary name change?"
  step "built: $BIN"
}

do_run() {
  [ -x "$BIN" ] || die "no binary at $BIN — run the 'build' step first"
  mkdir -p "$HS_DATA"
  if curl -s "http://127.0.0.1:${HS_HTTP_PORT}/health" >/dev/null 2>&1 \
     || (have nc && nc -z 127.0.0.1 "$HS_PORT" 2>/dev/null); then
    step "something already listening on :$HS_PORT / :$HS_HTTP_PORT — not starting a second one"
    return
  fi
  say "Starting hyperspace-server (gRPC :$HS_PORT, HTTP :$HS_HTTP_PORT, cwd $HS_DATA)"
  step "foreground; Ctrl-C to stop. For 24/7 wire it into systemd/launchd (see README)."
  step "data is written under the working directory; we cd into $HS_DATA first."
  # Only --port/--http-port are documented flags; the server persists under its
  # working dir (like the Docker image's /app/data volume), so we cd there.
  cd "$HS_DATA"
  exec "$BIN" --port "$HS_PORT" --http-port "$HS_HTTP_PORT"
}

smoke() {
  # Start briefly in the background, probe, then stop — proves the binary runs.
  [ -x "$BIN" ] || die "no binary to smoke-test"
  mkdir -p "$HS_DATA"
  ( cd "$HS_DATA" && exec "$BIN" --port "$HS_PORT" --http-port "$HS_HTTP_PORT" ) \
    >/tmp/hs_smoke.log 2>&1 &
  local pid=$!
  local ok=0 i
  for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${HS_HTTP_PORT}/health" >/dev/null 2>&1; then ok=1; break; fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  if [ "$ok" = "1" ]; then
    say "SMOKE OK — native HyperspaceDB answered /health on :$HS_HTTP_PORT"
  else
    warn "smoke test did not get a health response (see /tmp/hs_smoke.log)."
    warn "the binary may use a different health path/flag — check '$BIN --help'."
  fi
}

case "${1:-build}" in
  build)       do_build ;;
  run)         do_run ;;
  build-run)   do_build; do_run ;;
  smoke)       do_build; smoke ;;
  *) die "usage: $0 {build|run|build-run|smoke}" ;;
esac
