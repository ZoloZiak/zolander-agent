#!/bin/bash
# ensure_gemma_embed.sh — nahodi gemma_embed_server ak nebezi (health-check na :8901).
# Ticho ak uz bezi. Volatelne z launchd/systemd aj rucne. Cross-platform.
PORT="${GEMMA_EMBED_PORT:-8901}"

# Toolkit root sa odvodi od umiestnenia tohto skriptu (ziadna hardcoded cesta).
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRV="${GEMMA_SERVER:-$SELF_DIR/gemma_embed_server.py}"
LOG="${GEMMA_LOG:-${ZOL_HOME:-$HOME/.zolander}/logs/gemma_embed.log}"

# Python resolution (v poradi): explicitny override -> vMLX uv-tool (Apple) ->
# toolkit venv -> systemovy python3. Prvy co existuje vyhrava.
pick_py() {
  if [ -n "$ZOL_VENV_PY" ] && [ -x "$ZOL_VENV_PY" ]; then echo "$ZOL_VENV_PY"; return; fi
  for c in \
    "$HOME/.local/share/uv/tools/vmlx/bin/python" \
    "$SELF_DIR/../.venv/bin/python" \
    "$SELF_DIR/.venv/bin/python"; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  command -v python3
}
VPY="$(pick_py)"

if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  exit 0
fi
mkdir -p "$(dirname "$LOG")"
# GEMMA_OFFLINE respektuje server; nenastavujeme ho tu, nech prvy beh moze stiahnut model.
nohup "$VPY" "$SRV" >>"$LOG" 2>&1 &
exit 0
