#!/usr/bin/env python3
"""llm_client.py - provider-neutral, stdlib-only chat client.

Talks directly to the public APIs (Anthropic, Google Gemini, OpenAI-compatible,
OpenRouter). Toolkit scripts use `from llm_client import chat`.

Keys: environment first, then ~/.hermes/.env.
  ANTHROPIC_API_KEY  [ANTHROPIC_BASE_URL, default https://api.anthropic.com]
  GEMINI_API_KEY     [GEMINI_BASE_URL, default https://generativelanguage.googleapis.com/v1beta]
  OPENAI_API_KEY     [OPENAI_BASE_URL, default https://api.openai.com/v1]
  OPENROUTER_API_KEY (model ids containing "/")
The OpenAI branch also serves any OpenAI-compatible server (OpenRouter, Ollama,
LM Studio) via OPENAI_BASE_URL.

Model aliases: opus, sonnet, gpt, gpt-mini, gpt55, gemini, flash, ox. An alias
resolves from env LLM_MODEL_<ALIAS> (dashes become underscores, e.g.
LLM_MODEL_GPT_MINI). Built-in defaults exist only for opus and sonnet. A full
model id passes through unchanged and is routed by substring.

Throttle: LLM_MIN_INTERVAL seconds between requests (default 0.4).

  from llm_client import chat
  txt = chat("summarize...", model="opus", max_tokens=2000)
"""
import os, time, json, ssl, urllib.request, urllib.error, random, http.client

ANTHROPIC, GOOGLE, OPENAI, OPENROUTER = "anthropic", "google", "openai", "openrouter"

# alias -> provider (fixed by the alias, never by the model id behind it)
ALIAS_PROVIDER = {
    "opus": ANTHROPIC, "sonnet": ANTHROPIC,
    "gpt": OPENAI, "gpt-mini": OPENAI, "gpt55": OPENAI,
    "gemini": GOOGLE, "flash": GOOGLE,
    "ox": OPENROUTER,
}
# built-in model ids; every other alias must come from LLM_MODEL_<ALIAS>
DEFAULT_MODELS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
}
KEY_VARS = {
    ANTHROPIC: "ANTHROPIC_API_KEY",
    GOOGLE: "GEMINI_API_KEY",
    OPENAI: "OPENAI_API_KEY",
    OPENROUTER: "OPENROUTER_API_KEY",
}
BASE_DEFAULTS = {
    ANTHROPIC: ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    GOOGLE: ("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
    OPENAI: ("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    OPENROUTER: (None, "https://openrouter.ai/api/v1"),
}


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


def _env(name):
    """Env var first, then ~/.hermes/.env. Empty string when unset."""
    return os.environ.get(name, "").strip() or _from_hermes_env(name)


def _alias_env_name(alias):
    return "LLM_MODEL_" + alias.upper().replace("-", "_")


def _provider(model):
    """Provider for an alias or a full model id."""
    if model in ALIAS_PROVIDER:
        return ALIAS_PROVIDER[model]
    low = model.lower()
    if "/" in low:
        return OPENROUTER
    if "claude" in low or "anthropic" in low:
        return ANTHROPIC
    if "gemini" in low:
        return GOOGLE
    return OPENAI


def _model_id(model):
    """Concrete model id: alias -> env LLM_MODEL_<ALIAS> / built-in default;
    anything else passes through unchanged."""
    if model not in ALIAS_PROVIDER:
        return model
    var = _alias_env_name(model)
    mid = _env(var) or DEFAULT_MODELS.get(model, "")
    if not mid:
        raise RuntimeError(
            f"model alias '{model}' has no default - set {var} to a model id "
            f"(or pass a full model id).")
    return mid


def _key(provider):
    var = KEY_VARS[provider]
    k = _env(var)
    if not k:
        raise RuntimeError(f"{var} not set - export it or put it in ~/.hermes/.env.")
    return k


def has_credentials(model="opus"):
    """True if the key and model id for `model` are configured (no network)."""
    try:
        _key(_provider(model))
        _model_id(model)
        return True
    except RuntimeError:
        return False


def _base(provider):
    var, default = BASE_DEFAULTS[provider]
    return ((os.environ.get(var, "").strip() if var else "") or default).rstrip("/")


def _msgs(prompt, system):
    return ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]


def _build_request(provider, mid, prompt, max_tokens=2000, system=None,
                   thinking=None, image=None):
    """Pure request builder (no network). Returns (url, headers, payload).
    image=(b64, media_type) is anthropic-only. Raises RuntimeError on a missing key."""
    key = _key(provider)
    if provider == OPENROUTER:
        payload = {"model": mid, "max_tokens": max_tokens, "messages": _msgs(prompt, system)}
        if thinking:
            payload["reasoning"] = {"effort": thinking}
        return (_base(provider) + "/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload)
    if provider == ANTHROPIC:
        if image:
            content = [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": image[1], "data": image[0]}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        payload = {"model": mid, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": content}]}
        if system:
            payload["system"] = system
        if thinking:
            effort_map = {"high": "high", "xhigh": "xhigh", "max": "max"}
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}
            payload["output_config"] = {"effort": effort_map.get(thinking, "xhigh")}
        return (_base(provider) + "/v1/messages",
                {"x-api-key": key, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
                payload)
    if provider == GOOGLE:
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if thinking:
            tbud = {"high": 16384, "xhigh": 32768, "max": 65000}.get(thinking, 24576)
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": tbud}
        return (_base(provider) + f"/models/{mid}:generateContent",
                {"x-goog-api-key": key, "Content-Type": "application/json"},
                payload)
    # OpenAI wants max_completion_tokens, NOT max_tokens.
    payload = {"model": mid, "max_completion_tokens": max_tokens,
               "messages": _msgs(prompt, system)}
    if thinking:
        payload["reasoning_effort"] = "high"
    return (_base(provider) + "/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            payload)


_ctx = ssl.create_default_context()

# --- throttle: minimal spacing between requests (safe default) ---------------
MIN_INTERVAL = float(os.environ.get("LLM_MIN_INTERVAL", "0.4"))
_last_call = [0.0]


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last_call[0] = time.time()


def _parse(provider, d, model, max_tokens):
    if provider == ANTHROPIC:
        return "".join(b.get("text", "") for b in d.get("content", []))
    if provider == GOOGLE:
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


def _call(provider, build, model, max_tokens, max_retries, label):
    """POST with retry/backoff. `build` is a zero-arg callable returning
    (url, headers, payload); it is called again after a 401/403 so a rotated
    key is picked up."""
    url, headers, payload = build()
    body = json.dumps(payload).encode()
    for attempt in range(max_retries):
        _throttle()
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=_ctx, timeout=420)
            d = json.loads(resp.read())
            return _parse(provider, d, model, max_tokens)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529):
                ra = e.headers.get("Retry-After") or e.headers.get("retry-after")
                wait = float(ra) if (ra and ra.isdigit()) else min(60, (2 ** attempt) + random.random())
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                # key may have rotated during a long run -> reload + retry.
                new_headers = build()[1]
                if new_headers != headers:
                    headers = new_headers
                    time.sleep(min(30, (2 ** attempt) + random.random()))
                    continue
                raise
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.RemoteDisconnected, http.client.IncompleteRead):
            time.sleep(min(30, (2 ** attempt) + random.random()))
            continue
    raise RuntimeError(f"{label}() failed after {max_retries} attempts (model={model})")


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
    provider = _provider(model)
    mid = _model_id(model)
    build = lambda: _build_request(provider, mid, prompt, max_tokens, system, thinking)
    return _call(provider, build, model, max_tokens, max_retries, "chat")


def chat_vision(prompt, image_b64, media_type="image/jpeg", model="opus",
                max_tokens=300, system=None, max_retries=6):
    """Vision call: text + one base64 image via the Anthropic API.
    Mirrors the anthropic branch of chat(); forces Opus/Sonnet (vision-capable)."""
    if _provider(model) != ANTHROPIC:
        model = "opus"
    mid = _model_id(model)
    build = lambda: _build_request(ANTHROPIC, mid, prompt, max_tokens, system,
                                   None, (image_b64, media_type))
    return _call(ANTHROPIC, build, model, max_tokens, max_retries, "chat_vision")


if __name__ == "__main__":
    import sys
    print(chat(sys.argv[1] if len(sys.argv) > 1 else "say ok", model="opus", max_tokens=50))