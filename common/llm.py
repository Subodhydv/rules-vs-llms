"""Minimal Gemini client shared by both projects.

* REST call to the Gemini API (no SDK dependency), JSON output, temperature 0 by default.
* Every response is cached on disk under .llm_cache/ keyed by (model, prompt, temperature, variant).
  Committing the cache makes every reported number reproducible without spending quota again.
  The cache stores the original latency and token usage, so replayed runs report the real figures.
* Client-side rate limiting (free tier) and a hard per-run call budget.
* Cost is computed from token usage at the paid-tier list price (free tier costs $0, but the paid price
  is what matters at 100,000 users).

Environment:
  GEMINI_API_KEY   required for live calls
  GEMINI_MODEL     default gemini-2.5-flash
  GEMINI_RPM       requests/minute to stay under (default 8)
  LLM_MAX_CALLS    hard cap on live calls per process (default 400)
  LLM_OFFLINE=1    never call the API; use cache only
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".llm_cache"

# USD per 1M tokens (input, output incl. thinking), paid tier, from https://ai.google.dev/pricing (read 2026-11-15)
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
}
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class LLMUnavailable(RuntimeError):
    """No key, offline mode with a cache miss, or the call budget is exhausted."""


@dataclass
class LLMResponse:
    text: str
    data: object
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cached: bool
    cost_usd: float
    error: str | None = None
    raw: dict = field(default_factory=dict)


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = PRICES.get(model, PRICES["gemini-2.5-flash"])
    return in_tok / 1e6 * pin + out_tok / 1e6 * pout


def _extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise
        return json.loads(text[start:text.rfind("}" if text[start] == "{" else "]") + 1])


class GeminiClient:
    _last_call = 0.0
    live_calls = 0

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL
        self.key = os.environ.get("GEMINI_API_KEY")
        self.offline = os.environ.get("LLM_OFFLINE") == "1"
        self.rpm = float(os.environ.get("GEMINI_RPM", "8"))
        self.max_calls = int(os.environ.get("LLM_MAX_CALLS", "400"))
        CACHE_DIR.mkdir(exist_ok=True)

    @property
    def can_call_live(self) -> bool:
        return bool(self.key) and not self.offline

    def _key(self, prompt, system, temperature, variant):
        h = hashlib.sha256(json.dumps([self.model, system, prompt, temperature, variant]).encode()).hexdigest()
        return CACHE_DIR / f"{h[:2]}" / f"{h}.json"

    def has_cached(self, prompt, system=None, temperature=0.0, variant=0) -> bool:
        return self._key(prompt, system, temperature, variant).exists()

    def generate_json(self, prompt: str, system: str | None = None, temperature: float = 0.0,
                      variant: int = 0, max_output_tokens: int = 8192) -> LLMResponse:
        """variant > 0 forces a fresh call for repeat/determinism tests while still caching it."""
        path = self._key(prompt, system, temperature, variant)
        if path.exists():
            rec = json.loads(path.read_text())
            return self._to_response(rec, cached=True)
        if not self.can_call_live:
            raise LLMUnavailable("no GEMINI_API_KEY (or LLM_OFFLINE=1) and no cached response")
        if GeminiClient.live_calls >= self.max_calls:
            raise LLMUnavailable(f"LLM_MAX_CALLS={self.max_calls} reached")
        rec = self._call(prompt, system, temperature, max_output_tokens)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(rec, indent=1))
        return self._to_response(rec, cached=False)

    def _call(self, prompt, system, temperature, max_output_tokens) -> dict:
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json",
                                     "maxOutputTokens": max_output_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        for attempt in range(6):
            wait = 60.0 / self.rpm - (time.time() - GeminiClient._last_call)
            if wait > 0:
                time.sleep(wait)
            GeminiClient._last_call = time.time()
            t0 = time.perf_counter()
            resp = requests.post(url, params={"key": self.key}, json=body, timeout=180)
            latency = (time.perf_counter() - t0) * 1000
            if resp.status_code in (429, 500, 503):
                delay = 2 ** attempt * 5
                m = re.search(r'"retryDelay":\s*"(\d+)s"', resp.text)
                if m:
                    delay = int(m.group(1)) + 1
                time.sleep(min(delay, 120))
                continue
            resp.raise_for_status()
            GeminiClient.live_calls += 1
            data = resp.json()
            return {"model": self.model, "response": data, "latency_ms": latency,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
        raise LLMUnavailable(f"Gemini kept returning {resp.status_code}: {resp.text[:200]}")

    def _to_response(self, rec: dict, cached: bool) -> LLMResponse:
        data = rec["response"]
        usage = data.get("usageMetadata", {})
        in_tok = usage.get("promptTokenCount", 0)
        out_tok = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        text, parsed, err = "", None, None
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            parsed = _extract_json(text)
        except Exception as e:  # malformed / truncated / blocked output is a measured failure, not a crash
            err = f"{type(e).__name__}: {e}"
        return LLMResponse(text, parsed, rec["model"], in_tok, out_tok, rec["latency_ms"], cached,
                           cost_usd(rec["model"], in_tok, out_tok), err, data)


def llm_status() -> str:
    c = GeminiClient()
    if c.can_call_live:
        return f"live ({c.model})"
    n = sum(1 for _ in CACHE_DIR.rglob("*.json")) if CACHE_DIR.exists() else 0
    return f"offline (cache entries: {n})"
