#!/usr/bin/env python3
"""configure_palantir.py — OPTIONAL: wire a Palantir Foundry LLM proxy into Hermes.

Palantir Foundry's Developer Tier exposes Claude / GPT / Gemini behind one proxy.
This wires all three as Hermes custom providers using ONLY your own server name +
token — both prompted at runtime (or read from env), never baked into this repo.

Design choice: we configure through `hermes config set` (config-level provider
wiring), NOT by patching Hermes source. Source patches rot on every `hermes update`;
a provider entry in config.yaml survives. The three proxy quirks are handled as
provider settings, not code edits:
  - anthropic branch  -> Bearer auth + anthropic-version header, `max_tokens`
  - openai branch     -> `max_completion_tokens` (NOT `max_tokens`)
  - google branch     -> Bearer auth + chat-completions routing

Idempotent: re-running just overwrites the same keys. Secrets land in ~/.hermes/.env
(0600) via Hermes, never here.

Usage:
    python3 configure_palantir.py            # prompts for host + token
    PALANTIR_HOST=... PALANTIR_TOKEN=... python3 configure_palantir.py   # non-interactive
"""
import os
import sys
import subprocess
import shutil

# The proxy path layout is public Foundry API structure, not a secret.
PROXY_PATH = "/api/v2/llm/proxy"
BRANCHES = {
    "palantir-claude": {
        "path": "/anthropic/v1/messages",
        "api_mode": "anthropic",
        "note": "Bearer + anthropic-version header, max_tokens",
    },
    "palantir-gpt": {
        "path": "/openai/v1/chat/completions",
        "api_mode": "chat_completions",
        "note": "uses max_completion_tokens, not max_tokens",
    },
    "palantir-gemini": {
        "path": "/google/v1/chat/completions",
        "api_mode": "chat_completions",
        "note": "Bearer + chat-completions routing",
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


def hset(hermes, key, value):
    subprocess.run([hermes, "config", "set", key, value], check=True)


def guide():
    """Vypis kratky navod PRIAMO pred promptom — user nemusi hladat v README.
    Ukaze sa len ked realne ideme pytat (interaktivne, hodnoty nie su v env)."""
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
        url = base + cfg["path"].rsplit("/v1", 1)[0] + "/v1"
        print(f"  wiring {name}  ({cfg['note']})")
        hset(hermes, f"providers.{name}.base_url", url)
        hset(hermes, f"providers.{name}.api_mode", cfg["api_mode"])
        hset(hermes, f"providers.{name}.api_key_env", "PALANTIR_TOKEN")

    print("\nDone. Three Palantir surfaces wired as providers: "
          + ", ".join(BRANCHES))
    print("Pick one with `hermes model` (or /model in chat). Token is in ~/.hermes/.env.")
    print("Verify live with: hermes chat -q 'say ok' --provider palantir-claude")
    return 0


if __name__ == "__main__":
    sys.exit(main())
