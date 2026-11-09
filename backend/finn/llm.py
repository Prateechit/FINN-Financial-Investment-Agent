"""Provider-agnostic LLM router.

Every provider speaks the OpenAI chat-completions dialect, so routing is just (base_url, key, model).
Tasks ask for a *tier*; the router walks that tier's candidates and skips providers without a key or
that fail (rate limit, outage). Responses are cached by a hash of (model, messages) and every call is
logged to llm_calls so cost and cache-hit rate are visible.
"""
import hashlib
import json
import os
import re
import sys
import time

import httpx

from .db import LLMCall, kv_get, kv_set, session

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "ollama": (os.getenv("OLLAMA_URL", "http://localhost:11434") + "/v1", None),
}

# Ordered candidates per tier. Override any model with env FINN_MODEL_<PROVIDER>_<TIER>.
# Free-tier availability verified 2026-11-09: gemini-2.5-* returns 404 for new keys; pro models have no free quota;
# 3.7/3.8-flash and flash-latest timed out on every call. Candidates are tried in order, so newer models can be listed ahead of proven ones.
TIERS = {
    # short inputs, high volume: classification fallback, one-liners, profile extraction
    "fast": [("groq", "llama-3.1-8b-instant"), ("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-flash-lite-latest"),
             ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"), ("openai", "gpt-4o-mini"), ("ollama", "gemma3:4b")],
    # whole documents (~20k tokens): transcript guidance extraction
    "long": [("gemini", "gemini-3.5-flash"), ("gemini", "gemini-3.5-flash-lite"),
             ("openai", "gpt-4o-mini"), ("ollama", "gemma3:4b")],
    # reasoning over extracted JSON: promise-ledger verdicts, bull/bear
    "reason": [("gemini", "gemini-3.5-flash"), ("groq", "openai/gpt-oss-120b"), ("groq", "llama-3.3-70b-versatile"), ("openai", "gpt-4o-mini"),
               ("gemini", "gemini-3.5-flash-lite"),  # last resort: weaker, but the validators still apply
               ("ollama", "gemma3:4b")],
}
EFFORT = {"fast": "low", "long": "low", "reason": "medium"}
TIMEOUT = {"fast": 40, "long": 120, "reason": 150}

# Models that 404 (retired) are skipped for the process lifetime; quota-exhausted ones for 10 minutes.
_benched: dict[str, float] = {}


class LLMUnavailable(RuntimeError):
    pass


def _key(provider: str) -> str | None:
    env = PROVIDERS[provider][1]
    if env is None:
        return "ollama" if os.getenv("FINN_USE_OLLAMA") == "1" else None
    return os.getenv(env)


def available() -> dict:
    return {t: [f"{p}:{os.getenv(f'FINN_MODEL_{p.upper()}_{t.upper()}', m)}" for p, m in c if _key(p)] for t, c in TIERS.items()}


def _log(**kw):
    try:
        with session() as s:
            s.add(LLMCall(**kw))
    except Exception:
        pass


def _parse_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    # raw_decode takes the first complete JSON value and ignores anything a model appends after it
    return json.JSONDecoder().raw_decode(text[start:])[0]


def chat_json(task: str, tier: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.1):
    """Return parsed JSON from the first working candidate of `tier`."""
    errors = []
    for provider, model in TIERS[tier]:
        key = _key(provider)
        if not key:
            continue
        model = os.getenv(f"FINN_MODEL_{provider.upper()}_{tier.upper()}", model)
        if _benched.get(f"{provider}:{model}", 0) > time.time():
            continue
        ck = "llm:" + hashlib.sha256(json.dumps([model, system, user]).encode()).hexdigest()
        if hit := kv_get(ck):  # empty answers are never cached
            _log(task=task, provider=provider, model=model, cache_hit=True)
            return hit
        base = PROVIDERS[provider][0]
        # Long documents push the instructions out of a model's attention; repeat them after the document.
        content = user if len(user) < 15000 else f"{user}\n\n---\nINSTRUCTIONS (repeated):\n{system}\nReply with the JSON only."
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        if provider != "ollama":
            body["response_format"] = {"type": "json_object"}
        if (provider == "groq" and "gpt-oss" in model) or (provider == "gemini" and "-3" in model):
            body["reasoning_effort"] = EFFORT[tier]
        out = None
        for attempt in range(3):  # retries on the same model for overload (503) or malformed output
            t0 = time.time()
            try:
                r = httpx.post(base + "/chat/completions", json=body, timeout=TIMEOUT[tier],
                               headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 404:
                    _benched[f"{provider}:{model}"] = time.time() + 86400
                elif r.status_code == 429 and "quota" in r.text.lower():
                    _benched[f"{provider}:{model}"] = time.time() + 600
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
                data = r.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise RuntimeError(f"truncated at max_tokens={max_tokens}")
                out = _parse_json(choice["message"].get("content") or "")
                if not out:
                    raise RuntimeError("empty JSON")
                break
            except httpx.TimeoutException:
                _benched[f"{provider}:{model}"] = time.time() + 900  # overloaded: stop waiting on it for a while
                err = f"timeout after {TIMEOUT[tier]}s"
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            out = None
            _log(task=task, provider=provider, model=model, ms=int((time.time() - t0) * 1000), ok=False)
            errors.append(f"{provider}/{model}#{attempt + 1}: {err}")
            print(f"[llm] {task} {provider}/{model} attempt {attempt + 1} failed: {err}", file=sys.stderr)
            if _benched.get(f"{provider}:{model}", 0) > time.time() or err.startswith("HTTP 4") and "429" not in err:
                break
            if attempt == 1 and "HTTP 503" not in err:
                break  # malformed output twice: move on; only overload earns a third try
            time.sleep(5 + 10 * attempt)
        if out is None:
            continue
        usage = data.get("usage") or {}
        _log(task=task, provider=provider, model=model, ms=int((time.time() - t0) * 1000),
             tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0))
        kv_set(ck, out)
        return out
    raise LLMUnavailable(f"no {tier} model succeeded: " + ("; ".join(errors) or "no API key configured"))
