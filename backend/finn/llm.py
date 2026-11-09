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
import threading
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
# Free tier, verified 2026-11-09: each Gemini model has its own ~20 requests/day and ~15/minute quota, so tiers list
# several models to spread load. gemini-2.5-* returns 404 for new keys; pro models have no free quota; 3.7/3.8-flash and
# flash-latest timed out on every call.
TIERS = {
    # short inputs, high volume: classification fallback, one-liners, profile extraction
    # Groq (verified 2026-11-09): Llama models retired; gpt-oss-120b/20b and qwen3.8-27b at 1,000 req/day, 8k tokens/min.
    "fast": [("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-3.1-flash-lite"),
             ("gemini", "gemini-flash-lite-latest"), ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
             ("openai", "gpt-4o-mini"), ("ollama", "gemma3:4b")],
    # whole documents (~20k tokens): transcript guidance extraction
    "long": [("gemini", "gemini-3.5-flash"), ("gemini", "gemini-3-flash-preview"), ("gemini", "gemini-3.5-flash-lite"),
             ("openai", "gpt-4o-mini"), ("ollama", "gemma3:4b")],
    # reasoning over extracted JSON: promise-ledger verdicts, bull/bear
    "reason": [("gemini", "gemini-3.5-flash"), ("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3-flash-preview"),
               ("groq", "qwen/qwen3.8-27b"), ("openai", "gpt-4o-mini"),
               ("gemini", "gemini-3.5-flash-lite"),  # last resort: weaker, but the validators still apply
               ("ollama", "gemma3:4b")],
}
# second-model check of claims against their cited evidence: Groq first (large daily quota, different from the writer)
TIERS["verify"] = [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3-flash-preview"), ("groq", "qwen/qwen3.8-27b"), ("groq", "openai/gpt-oss-20b"),
                   ("gemini", "gemini-3.5-flash-lite"), ("openai", "gpt-4o-mini"), ("ollama", "gemma3:4b")]
EFFORT = {"fast": "low", "long": "low", "reason": "medium", "verify": "low"}
TIMEOUT = {"fast": 40, "long": 120, "reason": 150, "verify": 90}
MIN_GAP = {"gemini": 4.5, "groq": 2.0}  # seconds between calls to one model — stays under per-minute limits
TPM_CAP = {"groq": 8000}  # tokens/minute on the free tier; prompt + completion of one call must fit inside it

# Unavailable models are benched: 404 (retired) for a day, quota 429s until the server's retryDelay, timeouts 15 min.
_benched: dict[str, float] = {}
_last_call: dict[str, float] = {}
_pace_lock = threading.Lock()


def _bench(name: str, seconds: float) -> None:
    """Remember an unavailable model here and in the DB, so the API, CLI and cron all skip it."""
    _benched[name] = time.time() + seconds
    kv_set(f"bench:{name}", _benched[name])


def _bench_until(name: str) -> float:
    if name not in _benched:
        _benched[name] = float(kv_get(f"bench:{name}") or 0)
    return _benched[name]


def _is_benched(name: str) -> bool:
    return _bench_until(name) > time.time()


def _pace(provider: str, name: str) -> None:
    gap = MIN_GAP.get(provider, 0)
    with _pace_lock:
        wait = _last_call.get(name, 0) + gap - time.time()
        _last_call[name] = time.time() + max(0, wait)
    if wait > 0:
        time.sleep(wait)


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



def _candidates(tier: str) -> list[tuple[str, str, str]]:
    out = []
    for provider, model in TIERS[tier]:
        if key := _key(provider):
            out.append((provider, os.getenv(f"FINN_MODEL_{provider.upper()}_{tier.upper()}", model), key))
    return out


def _cache_key(model: str, system: str, user: str) -> str:
    return "llm:" + hashlib.sha256(json.dumps([model, system, user]).encode()).hexdigest()


def chat_json(task: str, tier: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.1,
              max_wait: float = 90):
    """Return parsed JSON from the best candidate of `tier` that can answer now.

    Candidates are walked in quality order: a model's cached answer is used if it has one (free); a benched model is
    skipped; otherwise the model is called. So a weaker model's cached answer is only reused while every stronger model
    is unavailable — it never shadows a better live model. If every candidate is benched only briefly (per-minute
    limits), wait up to `max_wait` seconds instead of failing.
    """
    cands = _candidates(tier)
    errors: list[str] = []
    deadline = time.time() + max_wait
    while True:
        for provider, model, key in cands:
            if hit := kv_get(_cache_key(model, system, user)):  # empty answers are never cached
                _log(task=task, provider=provider, model=model, cache_hit=True)
                return hit
            if _is_benched(f"{provider}:{model}"):
                continue
            if provider in TPM_CAP and (len(system) + len(user)) / 3.2 + 800 > TPM_CAP[provider]:
                continue  # prompt can't fit the provider's per-minute token window at all
            out = _call(task, tier, provider, model, key, system, user, max_tokens, temperature, errors)
            if out is not None:
                return out
        soonest = min((_bench_until(f"{p}:{m}") for p, m, _ in cands), default=0)
        if not cands or soonest - time.time() > deadline - time.time() or soonest <= time.time():
            break
        print(f"[llm] {task}: all {tier} models briefly rate-limited; waiting {soonest - time.time():.0f}s", file=sys.stderr)
        time.sleep(max(1.0, soonest - time.time() + 1))
    raise LLMUnavailable(f"no {tier} model succeeded: " + ("; ".join(errors) or "no API key configured"))


def _call(task, tier, provider, model, key, system, user, max_tokens, temperature, errors):
    name = f"{provider}:{model}"
    base = PROVIDERS[provider][0]
    # Long documents push the instructions out of a model's attention; repeat them after the document.
    content = user if len(user) < 15000 else f"{user}\n\n---\nINSTRUCTIONS (repeated):\n{system}\nReply with the JSON only."
    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    if provider != "ollama":
        body["response_format"] = {"type": "json_object"}
    if (provider == "groq" and "gpt-oss" in model) or (provider == "gemini" and "-3" in model):
        body["reasoning_effort"] = EFFORT[tier]
    if provider in TPM_CAP:  # the requested completion counts against the per-minute window too
        room = int(TPM_CAP[provider] - (len(system) + len(content)) / 3.0 - 200)
        body["max_tokens"] = max(400, min(max_tokens, room))
    for attempt in range(3):  # retries on the same model for overload (503) or malformed output
        _pace(provider, name)
        t0 = time.time()
        try:
            r = httpx.post(base + "/chat/completions", json=body, timeout=TIMEOUT[tier],
                           headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 404:
                _bench(name, 86400)
            elif r.status_code == 429:
                # quotas say when they reset — Gemini: "retryDelay": "65477s"; Groq: "try again in 7.5s" / "in 2m3s"
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                g = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", r.text)
                wait = int(m.group(1)) if m else (int(g.group(1) or 0) * 3600 + int(g.group(2) or 0) * 60 + float(g.group(3))) if g else 60
                _bench(name, min(wait + 1, 86400))
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            data = r.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise RuntimeError(f"truncated at max_tokens={max_tokens}")
            out = _parse_json(choice["message"].get("content") or "")
            if not out:
                raise RuntimeError("empty JSON")
        except httpx.TimeoutException:
            _bench(name, 900)  # overloaded: stop waiting on it for a while
            err = f"timeout after {TIMEOUT[tier]}s"
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
        else:
            usage = data.get("usage") or {}
            _log(task=task, provider=provider, model=model, ms=int((time.time() - t0) * 1000),
                 tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0))
            kv_set(_cache_key(model, system, user), out)
            return out
        _log(task=task, provider=provider, model=model, ms=int((time.time() - t0) * 1000), ok=False)
        errors.append(f"{provider}/{model}#{attempt + 1}: {err}")
        print(f"[llm] {task} {provider}/{model} attempt {attempt + 1} failed: {err.splitlines()[0]}", file=sys.stderr)
        if _is_benched(name) or (err.startswith("HTTP 4") and "429" not in err):
            return None
        if attempt == 1 and "HTTP 503" not in err:
            return None  # malformed output twice: move on; only overload earns a third try
        time.sleep(5 + 10 * attempt)
    return None
