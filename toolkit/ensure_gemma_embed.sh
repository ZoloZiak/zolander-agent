#!/bin/bash
# ensure_gemma_embed.sh — nahodi gemma_embed_server ak nebezi (health-check na :8901).
# Ticho ak uz bezi. Vzor ako ensure_agy_bridge.sh. Volatelne z launchd aj rucne.
PORT="${GEMMA_EMBED_PORT:-8901}"
VPY="${ZOL_VENV_PY:-$HOME/.local/share/uv/tools/vmlx/bin/python}"
SRV="$HOME/projects/zolander/toolkit/gemma_embed_server.py"
LOG="$HOME/projects/zolander/logs/gemma_embed.log"

if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  exit 0
fi
mkdir -p "$(dirname "$LOG")"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 nohup "$VPY" "$SRV" >>"$LOG" 2>&1 &
exit 0
