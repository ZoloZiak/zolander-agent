# Installing this repo — instructions for an AI agent

You are an AI coding agent (Antigravity / Claude Code / Codex / OpenHands / etc.)
and the user told you something like *"install this repo for me."* This file is
your entry point. `README.md` is the human narrative and the honest design doc —
read it for *why*; read **this** for *how*, in order, with the traps called out.

## What this is

Zolander is a persistent AI-companion stack that runs **on top of
[Hermes Agent](https://hermes-agent.nousresearch.com)**. It is not a standalone
app. It adds: a hyperbolic (Lorentz-129D) vector memory with multi-lens recall,
an identity key stable across models, shell hooks that turn soft rules into hard
locks, Slovak voice input (STT), optional background daemons, and an optional
signed agent-to-agent bridge.

It was built on one person's locked-down macOS box. The code is sanitized and
cross-platform, but **assume the reference machine was a Mac** when you read
paths or templates — bootstrap rewrites them for Linux.

## Honesty contract (do not break this)

This project's whole thesis is *not telling the user what they want to hear.* So:

- **Do not fabricate success.** If a step fails, say so and show the real error.
  A half-installed stack reported as "done" is worse than an honest failure.
- `README.md` separates **what runs today** from a **roadmap**. Don't promise
  roadmap features as if they work.
- Every memory carries a `confidence` score for the same reason — don't launder
  guesses into facts.

## Install order (run `bootstrap.sh`; it does these in sequence)

`bash bootstrap.sh` is the installer. It is idempotent and fail-soft. The steps:

1. **venv + deps** — `~/.venv-zolander` from `requirements.txt`
   (torch/transformers are heavy; CPU wheels on Linux, ~2–3 GB).
2. **YAR embedder** — pre-fetches `YARlabs/v5_Embedding_0.5B` (129-D hyperbolic
   embedder) so the first recall isn't a multi-minute stall. Skippable with
   `ZOLANDER_SKIP_EMBED=1` (then it downloads lazily on first use).
3. **HyperspaceDB** — the vector store on `:50051`. Two ways, pick one:
   - default: Docker (`glukhota/hyperspace-db`).
   - `ZOLANDER_HS_NATIVE=1`: compile the Rust source
     (`deploy/build_hyperspace_native.sh`, needs a nightly `cargo`) and run it
     bare-metal. Functionally equivalent; same port, same API.
4. **identity** — generates an Ed25519 key under `$ROOT/identity/` **if absent**.
   NEVER overwrite an existing one; that key *is* the agent's identity.
5. **skills** — `toolkit/fetch_skills.sh` pulls skills from their own origins.
6. **daemons** (optional) — launchd on macOS, systemd --user on Linux.
7. **LLM provider** — see below; this is the step most likely to need the user.
8. **hooks** — printed as a `hooks:` block to paste into `~/.hermes/config.yaml`
   (or run `toolkit/_add_cmdguard_hook.py` for the cmd-guard).

Key env vars: `ZOLANDER_ROOT` (default `$HOME/projects/zolander` — **keep this
default**, ~40 scripts resolve state/identity/toolkit under it), `ZOLANDER_REPO`,
`ZOLANDER_HS_NATIVE`, `ZOLANDER_SKIP_EMBED`.

## The LLM provider — the one thing that needs a human decision

The reference machine used a specific private LLM gateway ("Palantir"). **That is
not yours and `configure_palantir.py` only helps if the user has their own
Palantir access.** For a normal install, the user must point Hermes at whatever
provider *they* have (Anthropic, OpenAI, OpenRouter, a local model, …) with
`hermes config set providers.…`. There is NO TLS proxy, NO custom CA, and NO
pacing-gate shim in this repo — that was host-specific plumbing and was
deliberately left out. If LLM calls fail, it's a provider-config problem, not a
missing shim. **Ask the user which provider to use; don't guess or hardcode.**

## Hooks (soft rules → hard locks)

Wire these into the single `hooks:` key in `~/.hermes/config.yaml` (README has
the full block; merge all `pre_llm_call` / `pre_tool_call` / `pre_verify` lists):

- `hook_recall.py` (`pre_llm_call`) — injects session-start memory recall.
- `hook_skill_matcher.py` (`pre_llm_call`) — deterministic skill navigator.
- `hook_verify.py` (`pre_verify`) — mechanical "did you actually do it" check.
- `hook_cmd_guard.py` (`pre_tool_call`, matcher `terminal`) — HARD-blocks
  `rm -rf`, `bash -c`, command chaining, disk wipes, and destructive ops on the
  identity key / memory. This is the real safety lock; keep it.
- `hook_clarify_notify.py` / `hook_done_notify.py` — desktop banners (optional).

All hooks are stdlib-only, fail-open (a hook must never crash the agent), and
resolve paths from `$HOME` / their own location — no hardcoded user.

## Voice input (STT)

`toolkit/stt_whisper.py` transcribes voice (desktop mic + Matrix/WhatsApp voice
messages) with a Slovak-finetuned Whisper large-v3-turbo. Auto-picks a backend:
mlx_whisper (Apple) → faster-whisper (CPU/CUDA) → transformers (always works).
Wire it under `stt:` in config (README has the block). Optional; skip if the
user doesn't want voice.

## Shell discipline (inherited convention — follow it)

The toolkit assumes a strict/sandbox shell: **one atomic command per call, no
`&&`/`||`/`;` chaining, no `bash -c`, no heredocs.** This is prompt-level
convention, not enforced by the repo (except what `hook_cmd_guard.py` blocks).
Honor it when you run commands here — it keeps the install clean on a locked-down
host and the cmd-guard will reject the dangerous shapes anyway.

## When you're done

Report honestly: which steps ran, which were skipped (and why), what the user
still has to do themselves (provider config is the usual one), and how to verify
the stack is live (HyperspaceDB health on `:50051`, a test recall via
`zol_session.py`, `hermes hooks doctor` for the hooks).
