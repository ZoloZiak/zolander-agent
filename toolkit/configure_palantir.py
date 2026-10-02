#!/usr/bin/env python3
"""configure_palantir.py — OPTIONAL: wire a Palantir Foundry LLM proxy into Hermes.

Palantir Foundry's Developer Tier exposes Claude / GPT / Gemini behind one proxy.
This wires all three as Hermes custom providers using ONLY your own tenant name +
token — both prompted at runtime (or read from env), never baked into this repo.

Design choice: we configure through `hermes config set` (config-level provider
wiring), NOT by patching Hermes source. The provider entries survive `hermes update`.
(The strict-proxy QUIRKS that DO need core code — tool-call 400s, Gemini 422s,
the gpt-5 dotted-RID max_tokens bug — are a separate concern handled by
deploy/apply_hermes_patches.sh; this file only wires providers.)

Each provider is written as ONE JSON value, because the model identifiers are
Palantir RIDs full of dots (``ri.language-model-service..language-model.gpt-5-5``)
and `hermes config set a.b.c` would split every dot into a nested map. Setting the
whole provider block as JSON keeps the dotted RID as a single key (verified).

The three proxy quirks are provider settings, not code edits:
  - anthropic branch  -> api_mode ``anthropic_messages``, Bearer + anthropic-version
  - openai branch     -> api_mode ``chat_completions`` (sends max_completion_tokens)
  - google branch     -> api_mode ``chat_completions``, Bearer + chat-completions

NO TLS proxy, NO custom CA, NO local pacing-gate shim: requests go straight to
your Foundry tenant over the system trust store, like any normal program.

Idempotent: re-running overwrites the same provider blocks. Secrets land in
~/.hermes/.env (0600) via Hermes, never here.

Usage:
    python3 configure_palantir.py            # prompts for tenant host + token
    PALANTIR_HOST=... PALANTIR_TOKEN=... python3 configure_palantir.py   # non-interactive
"""
import json
import os
import sys
import subprocess
import shutil

# The proxy path layout is public Foundry API structure, not a secret.
PROXY_PATH = "/api/v2/llm/proxy"

# Per-branch wiring. `sub` is the proxy sub-path; `api_mode` is what Hermes sends;
# `models` maps each enabled Palantir RID -> its limits. Edit the RIDs/limits here
# if your tenant exposes different model versions (check Foundry -> Language Models).
BRANCHES = {
    "palantir-claude": {
        "name": "Palantir Claude (Opus / Sonnet)",
        "sub": "/anthropic",
        "api_mode": "anthropic_messages",
        "default_model": "ri.language-model-service..language-model.anthropic-claude-4-8-opus",
        "models": {
            "ri.language-model-service..language-model.anthropic-claude-4-8-opus": {
                "context_length": 1000000, "max_output_tokens": 200000, "supports_vision": True,
            },
            "ri.language-model-service..language-model.anthropic-claude-4-6-sonnet": {
                "context_length": 200000, "max_output_tokens": 128000, "supports_vision": True,
            },
        },
    },
    "palantir-gpt": {
        "name": "Palantir GPT (5.5 / 5.4 / 5.4-mini)",
        "sub": "/openai/v1",
        "api_mode": "chat_completions",
        "default_model": "ri.language-model-service..language-model.gpt-5-5",
        "models": {
            "ri.language-model-service..language-model.gpt-5-5": {
                "context_length": 1050000, "max_output_tokens": 128000, "supports_vision": True,
            },
            "ri.language-model-service..language-model.gpt-5-4": {
                "context_length": 1050000, "max_output_tokens": 128000, "supports_vision": True,
            },
            "ri.language-model-service..language-model.gpt-5-4-mini": {
                "context_length": 400000, "max_output_tokens": 128000, "supports_vision": True,
            },
        },
    },
    "palantir-gemini": {
        "name": "Palantir Gemini (3.1 Pro / 3.5 Flash)",
        "sub": "/google/v1",
        "api_mode": "chat_completions",
        "default_model": "ri.language-model-service..language-model.gemini-3-1-pro",
        "models": {
            "ri.language-model-service..language-model.gemini-3-1-pro": {
                "context_length": 1000000, "max_output_tokens": 64000, "supports_vision": True,
            },
            "ri.language-model-service..language-model.gemini-3-5-flash": {
                "context_length": 1048576, "max_output_tokens": 65535, "supports_vision": True,
            },
        },
    },
}


def find_hermes():
    h = shutil.which("hermes")
    if h:
        return h
    for c in (os.path.expanduser("~/.local/bin/hermes"),
              "/usr/local/bin/hermes", "/opt/homebrew/bin/hermes"):
        if os.path.exists(c):
            return c
    sys.exit("hermes CLI not found on PATH — install Hermes first (see bootstrap.sh)")


def ask(prompt, env_key):
    val = os.environ.get(env_key, "").strip()
    if val:
        return val
    if not sys.stdin.isatty():
        sys.exit(f"{env_key} not set and no TTY to prompt — export it and re-run")
    return input(prompt).strip()


def guide():
    """Short how-to printed right before the prompt — only when we actually ask."""
    if os.environ.get("PALANTIR_HOST") and os.environ.get("PALANTIR_TOKEN"):
        return
    if not sys.stdin.isatty():
        return
    print("""
──────────────────────────────────────────────────────────────
 Palantir Foundry — need a free AIP Developer Tier account.
──────────────────────────────────────────────────────────────
 1) Sign up (free, no card):
      https://signup.palantirfoundry.com/signup?signupPermitCode=BUILD_WITH_AIP
    Pick "AIP Developer Tier". (May ask for ID + face scan — their KYC.)

 2) HOST = your tenant URL from the browser address bar once logged in:
      https://YOURNAME.REGION.palantirfoundry.co.uk   (REGION e.g. euw-3, us-1)
    Paste the bare tenant URL — the proxy path is appended for you.

 3) TOKEN = Settings -> your profile -> Tokens
      (a.k.a. Account / Personal Access Tokens) -> Generate.
    Copy it immediately — it is shown only ONCE. Longest expiry is best.

 Model RIDs in this script match a typical tenant; if `hermes model` shows no
 models for a provider, your tenant exposes different versions — edit BRANCHES.

 No Palantir? Ctrl-C here and just run `hermes model` to pick any provider.
──────────────────────────────────────────────────────────────
""")


def main():
    hermes = find_hermes()
    guide()

    host = ask("Palantir Foundry host (e.g. myorg.euw-3.palantirfoundry.co.uk): ", "PALANTIR_HOST")
    token = ask("Palantir API token (stored locally in ~/.hermes/.env, 0600): ", "PALANTIR_TOKEN")
    if not host or not token:
        sys.exit("host and token are both required")
    host = host.replace("https://", "").replace("http://", "").rstrip("/")
    base = f"https://{host}{PROXY_PATH}"

    # token -> .env via Hermes (it writes 0600); never printed, never committed.
    subprocess.run([hermes, "config", "set", "PALANTIR_TOKEN", token],
                   check=True, stdout=subprocess.DEVNULL)

    for name, cfg in BRANCHES.items():
        block = {
            "name": cfg["name"],
            "api": base + cfg["sub"],
            "api_mode": cfg["api_mode"],
            "key_env": "PALANTIR_TOKEN",
            "discover_models": False,
            "default_model": cfg["default_model"],
            "models": cfg["models"],
        }
        print(f"  wiring {name}  ({cfg['api_mode']}, {len(cfg['models'])} models)")
        # ONE JSON value — keeps dotted model RIDs as single keys (dot-split safe).
        subprocess.run([hermes, "config", "set", f"providers.{name}", json.dumps(block)],
                       check=True, stdout=subprocess.DEVNULL)

    print("\nDone. Three Palantir surfaces wired as providers: " + ", ".join(BRANCHES))
    print("Pick one with `hermes model` (or /model in chat). Token is in ~/.hermes/.env.")
    print("Config changes take effect in a NEW session (/new or restart).")
    print("Verify live with: hermes chat -q 'say ok' --provider palantir-claude")
    return 0


if __name__ == "__main__":
    sys.exit(main())
