#!/usr/bin/env bash
# fetch_skills.sh — pull the skills Zolander uses from THEIR OWN sources.
#
# No forks, no vendored copies. Each skill is installed from its origin so you
# always get the latest:
#   - hub skills          -> `hermes skills install <id>`
#   - your own humanizer   -> installed from YOUR GitHub raw SKILL.md
#   - third-party skills   -> from their published hub id / URL (never re-hosted here)
#
# Edit the lists below to taste. Safe to re-run (hermes skips already-installed).
set -euo pipefail

have() { command -v "$1" >/dev/null 2>&1; }
have hermes || { echo "[!] hermes not on PATH — run bootstrap.sh first"; exit 1; }

# 1. Your own skill(s) — from your GitHub, always newest, no fork.
#    Point at the raw SKILL.md; --name overrides if frontmatter lacks one.
MINE=(
  "https://raw.githubusercontent.com/ZoloZiak/humanizer-slovak/main/SKILL.md"
)

# 2. Third-party skills by hub id (published by their authors; we just install).
#    These carry each author's own provenance — we never copy their content here.
HUB=(
  "anti-hallucination-protocol"
  "weight-activation-priming"
)

echo "==> Installing your own skills (from your GitHub raw)"
for url in "${MINE[@]}"; do
  echo "  $url"
  hermes skills install "$url" || echo "  [!] failed: $url"
done

echo "==> Installing third-party skills (from the hub, latest)"
for id in "${HUB[@]}"; do
  echo "  $id"
  hermes skills install "$id" || echo "  [!] not on hub / failed: $id (install manually)"
done

echo "==> Done. Check with: hermes skills list ; update anytime: hermes skills update"
