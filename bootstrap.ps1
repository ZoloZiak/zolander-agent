<#
.SYNOPSIS
  bootstrap.ps1 - one-shot Windows installer for a fresh Zolander agent.

.DESCRIPTION
  Native PowerShell port of bootstrap.sh for Windows. Stands up the copyable
  stack step by step: Hermes Agent -> this toolkit -> a Python venv with deps
  -> the Node bridge -> your own identity key + integrity manifest -> memory
  collection -> background daemons (Windows Task Scheduler).

  Wires NO LLM provider and NO secrets by default - pick your model with
  `hermes model` afterwards.

  Idempotent - re-runs are safe.

.PARAMETER SkipEmbed
  Skip the heavy torch/transformers embedder install (also env ZOLANDER_SKIP_EMBED=1).
  On a space-constrained disk this is the sensible default; recall falls back to
  the BM25 lexical lane (no model, no GPU) until you install the embedder.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1
#>
[CmdletBinding()]
param(
  [switch]$SkipEmbed,
  [switch]$HsDocker
)

$ErrorActionPreference = 'Stop'

# --- config (override via env) ----------------------------------------------
# ROOT must match where the toolkit scripts look for state/identity/toolkit:
# ~40 of them resolve os.path.expanduser("~/projects/zolander/..."). Keep this
# default in sync, or recall/identity/memory silently read an empty path.
$ROOT    = if ($env:ZOLANDER_ROOT) { $env:ZOLANDER_ROOT } else { Join-Path $HOME 'projects\zolander' }
$env:ZOLANDER_ROOT = $ROOT
$REPO_URL = if ($env:ZOLANDER_REPO) { $env:ZOLANDER_REPO } else { 'https://github.com/ZoloZiak/zolander-agent.git' }
$HS_IMAGE = if ($env:HS_IMAGE) { $env:HS_IMAGE } else { 'glukhota/hyperspace-db' }
$HS_PORT  = if ($env:HS_PORT)  { $env:HS_PORT }  else { '50051' }
$VENV     = if ($env:ZOLANDER_VENV) { $env:ZOLANDER_VENV } else { Join-Path $HOME '.venv-zolander' }
if (-not $SkipEmbed -and $env:ZOLANDER_SKIP_EMBED -eq '1') { $SkipEmbed = $true }
if (-not $HsDocker  -and $env:ZOLANDER_HS_DOCKER  -eq '1') { $HsDocker  = $true }

function Say  ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Step ($m) { Write-Host "  . $m" -ForegroundColor Magenta }
function Warn ($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }
function Have ($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

# Directory this script lives in (deploy\), repo root is its parent.
$SELF_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Say "Zolander installer - platform: windows ($([System.Environment]::OSVersion.Version))"

# --- 0. prereqs -------------------------------------------------------------
Say "0/9  Checking prerequisites"
if (-not (Have git))    { Die "git is required" }
$PYEXE = if (Have python) { 'python' } elseif (Have py) { 'py' } else { $null }
if (-not $PYEXE)        { Die "python is required (3.10+) - install from python.org and re-run" }
if (-not (Have node))   { Warn "node not found - the memory bridge needs it. Install Node 18+ and re-run." }
if (-not (Have npm))    { Warn "npm not found - needed to install the HyperspaceDB SDK." }
if (-not (Have cargo))  { Warn "cargo/Rust not found - needed to build the native HyperspaceDB binary (step 4). Install from rustup.rs, or set -HsDocker to use Docker instead." }

# --- 1. Hermes Agent --------------------------------------------------------
Say "1/9  Hermes Agent"
if (Have hermes) {
  $ver = (& hermes --version 2>$null); if (-not $ver) { $ver = '?' }
  Step "already installed ($ver) - skipping"
} else {
  Step "installing via the official installer (always latest)"
  # Windows one-liner from the Hermes install docs (PowerShell).
  try {
    irm https://hermes-agent.nousresearch.com/install.ps1 | iex
  } catch {
    Warn "automatic install failed - install Hermes manually: https://hermes-agent.nousresearch.com"
  }
  if (-not (Have hermes)) { Warn "hermes not on PATH yet - open a new shell or re-check your install" }
}

# --- 2. toolkit (clone/update first) ----------------------------------------
Say "2/9  Toolkit"
if (Test-Path (Join-Path $ROOT '.git')) {
  Step "present at $ROOT - pulling latest"
  try { git -C $ROOT pull --ff-only } catch { Warn "git pull failed - resolve manually" }
} elseif ((Test-Path $ROOT) -and (Test-Path (Join-Path $ROOT 'toolkit\zol_mem.py'))) {
  Step "found a non-git toolkit at $ROOT - using it as-is"
} else {
  Step "cloning $REPO_URL -> $ROOT"
  git clone $REPO_URL $ROOT
}
foreach ($d in 'state','logs','denniky','identity') {
  New-Item -ItemType Directory -Force -Path (Join-Path $ROOT $d) | Out-Null
}

# --- 3. Python venv + deps --------------------------------------------------
Say "3/9  Python environment ($VENV)"
if (-not (Test-Path $VENV)) {
  Step "creating virtualenv"
  & $PYEXE -m venv $VENV
}
$PY = Join-Path $VENV 'Scripts\python.exe'
if (-not (Test-Path $PY)) { Die "venv python missing at $PY - delete $VENV and re-run" }
Step "upgrading pip"
& $PY -m pip install --quiet --upgrade pip
if ($SkipEmbed) {
  Step "installing core deps only (-SkipEmbed - no torch/transformers)"
  try { & $PY -m pip install --quiet "cryptography>=42.0" "numpy>=1.26" } catch { Warn "core dep install had issues - see output" }
} else {
  Step "installing all deps from requirements.txt (torch/transformers are large, be patient)"
  try { & $PY -m pip install --quiet -r (Join-Path $ROOT 'requirements.txt') } catch { Warn "dep install had issues - re-run: $PY -m pip install -r $ROOT\requirements.txt" }
}
Step "toolkit will run under: $PY"

# --- 3b. embedder model (YAR 129D Lorentz) ----------------------------------
if (-not $SkipEmbed) {
  Say "3b/9 Embedder model (YARlabs/v5_Embedding_0.5B, ~1.2 GB first time)"
  if (Test-Path (Join-Path $HOME 'models\yar_v5_embedding')) {
    Step "local copy present (~/models/yar_v5_embedding) - using it offline"
  } else {
    Step "pre-fetching from Hugging Face (one-time; recall needs it)"
    try { & $PY (Join-Path $ROOT 'toolkit\embed_yar.py') warm } catch { Warn "model pre-fetch had issues - it will download lazily on first recall" }
  }
}

# --- 4. HyperspaceDB (native-on-metal by default, Docker opt-in) ------------
Say "4/9  HyperspaceDB (vector store) on :$HS_PORT"
if (-not $HsDocker) {
  $nativeSh = $null
  foreach ($d in $SELF_DIR, (Join-Path $ROOT 'deploy')) {
    $cand = Join-Path $d 'build_hyperspace_native.sh'
    if ($d -and (Test-Path $cand)) { $nativeSh = $cand; break }
  }
  if ($nativeSh -and (Have cargo)) {
    Step "native build (default) - compiling HyperspaceDB from Rust source"
    # build_hyperspace_native.sh is bash; on Windows drive the build directly
    # with cargo if git-bash is absent.
    if (Have bash) {
      try { bash $nativeSh build } catch { Warn "native build failed - see output; or use -HsDocker" }
    } else {
      $hsSrc = if ($env:HS_SRC) { $env:HS_SRC } else { Join-Path $HOME 'src\hyperspace-db' }
      if (-not (Test-Path (Join-Path $hsSrc '.git'))) {
        git clone --depth 1 'https://github.com/YARlabs/hyperspace-db.git' $hsSrc
      }
      Push-Location $hsSrc
      try { cargo build --release } catch { Warn "cargo build failed - see output" } finally { Pop-Location }
    }
    Step "built (if cargo succeeded). Start it from the hyperspace-db checkout:"
    Step "  cd <hyperspace-db>; .\target\release\hyperspace-server.exe --port $HS_PORT --http-port 50050"
  } else {
    Warn "native build unavailable (no build script or no cargo) - install Rust (rustup.rs) or use -HsDocker"
  }
} elseif (Have docker) {
  $running = (docker ps --format '{{.Names}}' 2>$null) -match '^hyperspace$'
  $exists  = (docker ps -a --format '{{.Names}}' 2>$null) -match '^hyperspace$'
  if ($running) {
    Step "container already running - skipping"
  } elseif ($exists) {
    Step "container exists but stopped - starting"
    try { docker start hyperspace } catch { Warn "could not start existing container - check 'docker logs hyperspace'" }
  } else {
    Step "starting a fresh container"
    try { docker run -d --name hyperspace -p "${HS_PORT}:50051" --restart unless-stopped $HS_IMAGE } catch { Warn "HyperspaceDB start failed - check 'docker logs hyperspace'" }
  }
} else {
  Warn "-HsDocker set but docker missing - install Docker Desktop and re-run, or drop -HsDocker for the native build."
}

# --- 5. Node bridge (HyperspaceDB SDK) --------------------------------------
Say "5/9  Node bridge (hs.mjs + HyperspaceDB SDK)"
if (Have npm) {
  Step "installing the SDK next to the toolkit (toolkit/node_modules)"
  Push-Location (Join-Path $ROOT 'toolkit')
  try { npm install --silent --no-audit --no-fund } catch { Warn "npm install failed - run it by hand in $ROOT\toolkit" } finally { Pop-Location }
  $env:NODE_PATH = Join-Path $ROOT 'toolkit\node_modules'
} else {
  Warn "npm missing - install Node 18+ and run: cd $ROOT\toolkit; npm install"
}

# --- 6. identity + integrity + memory collection ----------------------------
Say "6/9  Identity key + integrity manifest"
Step "generating identity (idempotent - never overwrites an existing key)"
& $PY (Join-Path $ROOT 'toolkit\gen_identity.py')
Step "recording integrity manifest"
& $PY (Join-Path $ROOT 'toolkit\integrity.py') write

Say "     Memory collection (zol_mem)"
if ($env:NODE_PATH -and (Have node)) {
  Step "creating collection"
  try { & $PY (Join-Path $ROOT 'toolkit\zol_mem.py') init } catch { Warn "collection init failed - is HyperspaceDB up and NODE_PATH set?" }
} else {
  Warn "NODE_PATH/node not ready - create it later: `$env:NODE_PATH='$ROOT\toolkit\node_modules'; $PY $ROOT\toolkit\zol_mem.py init"
}

# --- 6c. skills from their own sources (no forks) ---------------------------
$fetchSkills = Join-Path $ROOT 'toolkit\fetch_skills.sh'
if (Test-Path $fetchSkills) {
  Say "6c/9 Skills (from their own origins - no forks)"
  if (Have bash) {
    try { bash $fetchSkills } catch { Warn "skill fetch had failures - see output above" }
  } else {
    Warn "bash not found - run skill fetch from git-bash: bash `"$fetchSkills`""
  }
}

# --- 7. background daemons (Windows Task Scheduler) -------------------------
Say "7/9  Background daemons (windows)"
# Linux uses systemd --user, macOS launchd. On Windows the equivalent is the
# Task Scheduler. We register the recurring toolkit loops as per-user scheduled
# tasks (run whether logged on or not is NOT set - they run at logon, like
# systemd --user without linger). Idempotent: an existing task is replaced.
$tasks = @(
  @{ Name='Zolander-Loop';     Script='zol_loop.py';      Minutes=15 },
  @{ Name='Zolander-Watchdog'; Script='hook_verify.py';   Minutes=30 },
  @{ Name='Zolander-Dream';    Script='zolander_dream.py'; Minutes=0  },  # daily, see below
  @{ Name='Zolander-Brief';    Script='initiative.py';    Minutes=60 }
)
$canSchedule = Have schtasks
if ($canSchedule) {
  foreach ($t in $tasks) {
    $scriptPath = Join-Path $ROOT ("toolkit\" + $t.Script)
    if (-not (Test-Path $scriptPath)) { Warn "skip $($t.Name): $($t.Script) not found"; continue }
    $action = "`"$PY`" `"$scriptPath`""
    try {
      if ($t.Minutes -gt 0) {
        schtasks /Create /F /TN $t.Name /TR $action /SC MINUTE /MO $t.Minutes | Out-Null
      } else {
        schtasks /Create /F /TN $t.Name /TR $action /SC DAILY /ST 04:00 | Out-Null
      }
      Step "registered scheduled task: $($t.Name)"
    } catch {
      Warn "could not register $($t.Name) - run elevated or create it manually in Task Scheduler"
    }
  }
  Warn "scheduled tasks run under your logon. For 24/7 open Task Scheduler and tick 'Run whether user is logged on or not'."
} else {
  Warn "schtasks unavailable - register the toolkit loops manually in Task Scheduler (see README)."
}

# --- 8. hooks hint ----------------------------------------------------------
Say "8/9  Hermes hooks (optional, recommended)"
Step "wire recall/verify hooks into ~/.hermes/config.yaml - see the 'hooks:' block in the README"
Step "paths there use PY=$PY and ROOT=$ROOT"

# --- 9. done ----------------------------------------------------------------
Say "9/9  Done. Zolander scaffolding is in place."
@"

Next, YOU wire the parts this installer deliberately left open:

  1. Pick your LLM provider:     hermes model
  2. Wire the recall/verify hooks into ~/.hermes/config.yaml
     (copy the 'hooks:' block from the README; paths use the two below).
  3. Paste your pubkey+fingerprint into skills/zolander/SKILL.md,
     then re-run:                $PY $ROOT\toolkit\integrity.py write
  4. (Optional) messaging gateway: hermes gateway setup

Toolkit python:  $PY
Toolkit root:    $ROOT
Secrets, proxies and private LLM wiring are NOT handled here by design.
"@ | Write-Host
