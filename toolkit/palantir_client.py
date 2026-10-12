#!/usr/bin/env python3
"""palantir_client.py — portable client for a Palantir Foundry LLM proxy.

Foundry's AIP Developer Tier exposes Claude / GPT / Gemini behind ONE proxy on
your own tenant. This is a thin, stdlib-only client (no `requests`, no SDK) the
toolkit scripts import as `from palantir_client import chat`.

NOTHING here is hardcoded to the author's machine: tenant URL, token and CA trust
all come from the environment (or ~/.hermes/.env). It uses your SYSTEM trust store
like any normal HTTPS client — there is no TLS-proxy / custom-CA / cert-strict
workaround in this file (that was the author's locked-down-laptop concern and
has no place in a copyable repo). On a normal Linux/macOS box it just works.

Configure (any one of):
  - export PALANTIR_HOST=myorg.euw-3.palantirfoundry.co.uk   (bare tenant host)
    or  PALANTIR_BASE=https://.../api/v2/llm/proxy           (full base, wins)
  - export PALANTIR_TOKEN=...        (or put PALANTIR_TOKEN=... in ~/.hermes/.env)
  `configure_palantir.py` writes both for you and wires Hermes providers too.

Use as a module:
  from palantir_client import chat
  txt = chat("summarize...", model="opus", max_tokens=2000)

Model aliases: opus, sonnet, gpt, gpt-mini, gpt55, gemini, flash. Pass a full
model id through unchanged. Optional OpenRouter escape hatch (`ox`) if you set
OPENROUTER_API_KEY — off by default, Palantir is the primary surface.
"""
import os, time, json, ssl, urllib.request, urllib.error, random, http.client

# --- endpoint: env-driven, never baked in -----------------------------------
PROXY_PATH = "/api/v2/llm/proxy"


def _base():
    """Resolve the proxy base URL from env. PALANTIR_BASE wins; else build it
    from the bare PALANTIR_HOST tenant. Raises a clear error if neither is set."""
    base = os.environ.get("PALANTIR_BASE", "").strip()
    if base:
        return base.rstrip("/")
    host = os.environ.get("PALANTIR_HOST", "").strip()
    if not host:
        # also try ~/.hermes/.env so a scripted run picks it up without exports
        host = _from_hermes_env("PALANTIR_HOST")
    if not host:
        raise RuntimeError(
            "PALANTIR_HOST (or PALANTIR_BASE) not set. Run configure_palantir.py "
            "or `export PALANTIR_HOST=yourtenant.region.palantirfoundry.co.uk`."
        )
    host = host.replace("https://", "").replace("http://", "").rstrip("/")
    return f"https://{host}{PROXY_PATH}"


MODELS = {
    "opus":     "ri.language-model-service..language-model.anthropic-claude-4-8-opus",
    "sonnet":   "ri.language-model-service..language-model.anthropic-claude-4-6-sonnet",
    "gpt":      "ri.language-model-service..language-model.gpt-5-4",
    "gpt-mini": "ri.language-model-service..language-model.gpt-5-4-mini",
    "gpt55":    "ri.language-model-service..language-model.gpt-5-5",
    "gemini":   "ri.language-model-service..language-model.gemini-3-1-pro",
    "flash":    "ri.language-model-service..language-model.gemini-3-5-flash",
    # OpenRouter escape hatch (OUTSIDE Palantir — different base + auth). Off unless
    # OPENROUTER_API_KEY is set. Prompts go to a third party; don't send secrets.
    "ox":       "stealth/ox-alpha",
}
OPENROUTER_MODELS = {"ox"}


def _from_hermes_env(key):
    """Read KEY=value from ~/.hermes/.env (Hermes' 0600 credential store)."""
    try:
        for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _token():
    """Palantir token: env PALANTIR_TOKEN first, then ~/.hermes/.env."""
    return os.environ.get("PALANTIR_TOKEN", "").strip() or _from_hermes_env("PALANTIR_TOKEN")


def _openrouter_key():
    return os.environ.get("OPENROUTER_API_KEY", "").strip() or _from_hermes_env("OPENROUTER_API_KEY")


# and must not ship in a copyable repo.
_ctx = ssl.create_default_context()
_TOK = _token()
_OR_KEY = _openrouter_key()


def _reload_token():
    """Re-read the token (it may have rotated during a long run). True if changed."""
    global _TOK
    new = _token()
    if new and new != _TOK:
        _TOK = new
        return True
    return False


# --- throttle: minimal spacing between requests (safe default) ---------------
MIN_INTERVAL = float(os.environ.get("PALANTIR_MIN_INTERVAL", "0.4"))
_last_call = [0.0]


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last_call[0] = time.time()


def chat(prompt, model="opus", max_tokens=2000, system=None, max_retries=6,
         thinking=None):
    """Call an LLM with retry + backoff. Returns the response text, or raises
    after retries are exhausted.

    thinking=None|'high'|'xhigh'|'max' enables extended reasoning where supported:
      - anthropic: adaptive thinking with an effort level
      - openai/gpt: reasoning_effort
      - google/gemini: thinkingConfig budget
      - openrouter/ox: reasoning.effort
    """
    mid = MODELS.get(model, model)
    is_openrouter = model in OPENROUTER_MODELS or mid.startswith("stealth/") or "/" in mid
    is_anthropic = (not is_openrouter) and ("anthropic" in mid or model in ("opus", "sonnet"))
    is_google = (not is_openrouter) and ("gemini" in mid or model in ("gemini", "flash"))

    if is_openrouter:
        if not _OR_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set — needed for model 'ox'.")
        url = "https://openrouter.ai/api/v1/chat/completions"
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        payload = {"model": mid, "max_tokens": max_tokens, "messages": msgs}
        if thinking:
            payload["reasoning"] = {"effort": thinking}
        headers = {"Authorization": f"Bearer {_OR_KEY}", "Content-Type": "application/json"}
    elif is_anthropic:
        url = _base() + "/anthropic/v1/messages"
        payload = {"model": mid, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": prompt}]}
        if system:
            payload["system"] = system
        if thinking:
            effort_map = {"high": "high", "xhigh": "xhigh", "max": "max"}
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}
            payload["output_config"] = {"effort": effort_map.get(thinking, "xhigh")}
        headers = {"Authorization": f"Bearer {_TOK}", "Content-Type": "application/json",
                   "anthropic-version": "2023-06-01"}
    elif is_google:
        url = _base() + f"/google/v1/models/{mid}:generateContent"
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if thinking:
            tbud = {"high": 16384, "xhigh": 32768, "max": 65000}.get(thinking, 24576)
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": tbud}
        headers = {"Authorization": f"Bearer {_TOK}", "Content-Type": "application/json"}
    else:
        url = _base() + "/openai/v1/chat/completions"
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        # OpenAI branch wants max_completion_tokens, NOT max_tokens.
        payload = {"model": mid, "max_completion_tokens": max_tokens, "messages": msgs}
        if thinking:
            payload["reasoning_effort"] = "high"
        headers = {"Authorization": f"Bearer {_TOK}", "Content-Type": "application/json"}

    if not is_openrouter and not _TOK:
        raise RuntimeError("PALANTIR_TOKEN not set — run configure_palantir.py or export it.")

    body = json.dumps(payload).encode()
    for attempt in range(max_retries):
        _throttle()
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=_ctx, timeout=420)
            d = json.loads(resp.read())
            if is_anthropic:
                return "".join(b.get("text", "") for b in d.get("content", []))
            if is_google:
                cands = d.get("candidates", [])
                if not cands:
                    return ""
                fr = cands[0].get("finishReason", "")
                parts = cands[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in parts)
                # Gemini is a reasoning model; if thinking eats the whole budget the
                # parts come back empty with finishReason=MAX_TOKENS. Raise loudly
                # instead of silently returning "" (so the caller can raise budget).
                if not txt and fr == "MAX_TOKENS":
                    raise RuntimeError(
                        f"Gemini MAX_TOKENS with no text (thinking ate the budget, "
                        f"model={model}, max_tokens={max_tokens})")
                return txt
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529):
                ra = e.headers.get("Retry-After") or e.headers.get("retry-after")
                wait = float(ra) if (ra and ra.isdigit()) else min(60, (2 ** attempt) + random.random())
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                # token may have rotated during a long run -> reload + retry once.
                if _reload_token():
                    headers["Authorization"] = f"Bearer {_TOK}"
                    time.sleep(min(30, (2 ** attempt) + random.random()))
                    continue
                raise
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.RemoteDisconnected, http.client.IncompleteRead):
            time.sleep(min(30, (2 ** attempt) + random.random()))
            continue
    raise RuntimeError(f"chat() failed after {max_retries} attempts (model={model})")


def chat_vision(prompt, image_b64, media_type="image/jpeg", model="opus",
                max_tokens=300, system=None, max_retries=6):
    """Vision call: text + one base64 image via the Palantir Anthropic proxy.
    Mirrors the anthropic branch of chat(); forces Opus/Sonnet (vision-capable)."""
    mid = MODELS.get(model, model)
    if not ("anthropic" in mid or model in ("opus", "sonnet")):
        mid = MODELS["opus"]
    if not _TOK:
        raise RuntimeError("PALANTIR_TOKEN not set — run configure_palantir.py or export it.")
    url = _base() + "/anthropic/v1/messages"
    content = [
        {"type": "image", "source": {"type": "base64",
                                     "media_type": media_type, "data": image_b64}},
        {"type": "text", "text": prompt},
    ]
    payload = {"model": mid, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": content}]}
    if system:
        payload["system"] = system
    headers = {"Authorization": f"Bearer {_TOK}", "Content-Type": "application/json",
               "anthropic-version": "2023-06-01"}
    body = json.dumps(payload).encode()
    for attempt in range(max_retries):
        _throttle()
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=_ctx, timeout=420)
            d = json.loads(resp.read())
            return "".join(b.get("text", "") for b in d.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529):
                ra = e.headers.get("Retry-After") or e.headers.get("retry-after")
                wait = float(ra) if (ra and ra.isdigit()) else min(60, (2 ** attempt) + random.random())
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                if _reload_token():
                    headers["Authorization"] = f"Bearer {_TOK}"
                    time.sleep(min(30, (2 ** attempt) + random.random()))
                    continue
                raise
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.RemoteDisconnected, http.client.IncompleteRead):
            time.sleep(min(30, (2 ** attempt) + random.random()))
            continue
    raise RuntimeError(f"chat_vision() failed after {max_retries} attempts (model={model})")


if __name__ == "__main__":
    import sys
    print(chat(sys.argv[1] if len(sys.argv) > 1 else "say ok", model="opus", max_tokens=50))
