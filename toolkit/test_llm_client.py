#!/usr/bin/env python3
"""test_llm_client.py - offline unit test for llm_client (no network, no keys).

Covers alias resolution from env, missing-key errors, provider routing and the
request shape built by the pure `_build_request`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client as lc  # noqa: E402

lc._from_hermes_env = lambda key: ""   # never read the real ~/.hermes/.env

VARS = ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
        "ANTHROPIC_BASE_URL", "GEMINI_BASE_URL", "OPENAI_BASE_URL"] + \
       [lc._alias_env_name(a) for a in lc.ALIAS_PROVIDER]


def clean():
    for v in VARS:
        os.environ.pop(v, None)


def raises(fn, needle):
    try:
        fn()
    except RuntimeError as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError(f"no RuntimeError containing {needle!r}")


def main():
    clean()
    # --- alias resolution ---
    assert lc._model_id("opus") == "claude-opus-5-5"
    assert lc._model_id("sonnet") == "claude-sonnet-5-5"
    os.environ["LLM_MODEL_OPUS"] = "my-opus"
    assert lc._model_id("opus") == "my-opus"
    raises(lambda: lc._model_id("gpt-mini"), "LLM_MODEL_GPT_MINI")
    for a in ("gpt", "gpt55", "gemini", "flash", "ox"):
        raises(lambda a=a: lc._model_id(a), lc._alias_env_name(a))
    os.environ["LLM_MODEL_GPT_MINI"] = "some-mini"
    assert lc._model_id("gpt-mini") == "some-mini"
    assert lc._model_id("claude-x-1") == "claude-x-1"   # full id passes through

    # --- provider routing ---
    P = lc._provider
    assert [P(a) for a in ("opus", "sonnet")] == ["anthropic"] * 2
    assert [P(a) for a in ("gemini", "flash")] == ["google"] * 2
    assert [P(a) for a in ("gpt", "gpt-mini", "gpt55")] == ["openai"] * 3
    assert P("ox") == "openrouter"
    assert P("claude-opus-5-5") == "anthropic"
    assert P("gemini-9-pro") == "google"
    assert P("vendor/some-model") == "openrouter"
    assert P("gpt-9") == "openai"

    # --- missing key ---
    clean()
    raises(lambda: lc._build_request("anthropic", "m", "hi"), "ANTHROPIC_API_KEY")
    raises(lambda: lc._build_request("google", "m", "hi"), "GEMINI_API_KEY")
    raises(lambda: lc._build_request("openai", "m", "hi"), "OPENAI_API_KEY")
    raises(lambda: lc._build_request("openrouter", "m", "hi"), "OPENROUTER_API_KEY")
    assert not lc.has_credentials("opus")
    os.environ["ANTHROPIC_API_KEY"] = "k-a"
    assert lc.has_credentials("opus")
    assert not lc.has_credentials("gpt")      # no key and no model id

    # --- request shapes ---
    url, h, p = lc._build_request("anthropic", "claude-opus-5-5", "hi", 77, "sys", "high")
    assert url == "https://api.anthropic.com/v1/messages"
    assert h["x-api-key"] == "k-a" and h["anthropic-version"] == "2023-06-01"
    assert p["model"] == "claude-opus-5-5" and p["max_tokens"] == 77 and p["system"] == "sys"
    assert p["messages"] == [{"role": "user", "content": "hi"}]
    assert p["thinking"]["type"] == "adaptive" and p["output_config"] == {"effort": "high"}
    os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:9/"
    assert lc._build_request("anthropic", "m", "hi")[0] == "http://localhost:9/v1/messages"
    _, _, p = lc._build_request("anthropic", "m", "look", 10, None, None, ("QUJD", "image/png"))
    assert p["messages"][0]["content"][0]["source"]["data"] == "QUJD"
    assert p["messages"][0]["content"][1] == {"type": "text", "text": "look"}

    os.environ["GEMINI_API_KEY"] = "k-g"
    url, h, p = lc._build_request("google", "gemini-9", "hi", 50, "sys", "max")
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-9:generateContent"
    assert h["x-goog-api-key"] == "k-g"
    assert p["generationConfig"]["maxOutputTokens"] == 50
    assert p["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 65000}
    assert p["systemInstruction"] == {"parts": [{"text": "sys"}]}

    os.environ["OPENAI_API_KEY"] = "k-o"
    url, h, p = lc._build_request("openai", "gpt-9", "hi", 30, "sys", "high")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert h["Authorization"] == "Bearer k-o"
    assert p["max_completion_tokens"] == 30 and "max_tokens" not in p
    assert p["messages"][0] == {"role": "system", "content": "sys"}
    assert p["reasoning_effort"] == "high"
    os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
    assert lc._build_request("openai", "m", "hi")[0] == "http://localhost:11434/v1/chat/completions"

    os.environ["OPENROUTER_API_KEY"] = "k-r"
    url, h, p = lc._build_request("openrouter", "vendor/m", "hi", 20, None, "high")
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert h["Authorization"] == "Bearer k-r" and p["reasoning"] == {"effort": "high"}
    assert p["max_tokens"] == 20

    clean()
    print("llm_client OK")


if __name__ == "__main__":
    main()