"""OpenRouter through the OpenAI Python SDK, with a capped retry loop and exponential backoff on 429."""
from __future__ import annotations

import time

import openai

from itc.llm import LLMError, LLMRequest
from itc.llm.cache import DiskCache, cache_key


class OpenRouterLLM:
    def __init__(self, llm_cfg: dict, api_key: str, sleep=time.sleep):
        self.model_id = llm_cfg["model_id"]
        self.temperature = llm_cfg["temperature"]
        self.max_retries = llm_cfg["max_retries"]
        self.backoff = llm_cfg["backoff_base_seconds"]
        self.sleep = sleep
        self.calls = 0  # network requests actually sent, for the 50/day budget
        self.client = openai.OpenAI(
            base_url=llm_cfg["base_url"], api_key=api_key,
            timeout=llm_cfg["request_timeout_seconds"], max_retries=0,  # we own the retry policy
        )

    def _wait(self, attempt: int, err: Exception) -> float:
        retry_after = getattr(getattr(err, "response", None), "headers", {}).get("retry-after")
        try:
            return max(float(retry_after), self.backoff * 2**attempt) if retry_after else self.backoff * 2**attempt
        except ValueError:
            return self.backoff * 2**attempt

    def complete(self, req: LLMRequest) -> str:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self.calls += 1
                resp = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=req.messages,
                    temperature=self.temperature,
                    response_format=req.response_format,
                )
                text = resp.choices[0].message.content if resp.choices else None
                if not text:
                    raise LLMError("empty response")
                return text
            except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
                    openai.InternalServerError, LLMError) as err:
                last = err
                if attempt < self.max_retries:
                    self.sleep(self._wait(attempt, err))
            except openai.APIStatusError as err:  # 4xx other than 429: retrying will not help
                raise LLMError(f"HTTP {err.status_code}: {err.message}") from err
        raise LLMError(f"gave up after {self.max_retries + 1} attempts: {last}")


class CachedLLM:
    """Wraps any LLM with the disk cache. `hits` and `misses` are reported in the audit log."""

    def __init__(self, inner, cache: DiskCache):
        self.inner = inner
        self.cache = cache
        self.model_id = inner.model_id
        self.temperature = inner.temperature
        self.hits = 0
        self.misses = 0

    def complete(self, req: LLMRequest) -> str:
        key = cache_key(self.model_id, req.prompt_version, req.rule_pack_version, self.temperature,
                        req.messages, req.run_index)
        hit = self.cache.get(key)
        if hit is not None:
            self.hits += 1
            return hit["response_text"]
        self.misses += 1
        text = self.inner.complete(req)
        self.cache.put(key, {
            "model_id": self.model_id, "prompt_version": req.prompt_version,
            "rule_pack_version": req.rule_pack_version, "temperature": self.temperature,
            "run_index": req.run_index, "line_ids": [ln["line_id"] for ln in req.lines],
            "response_text": text,
        })
        return text


class OfflineLLM:
    """Live mode without an API key: serves the committed cache and fails clearly on a miss."""

    def __init__(self, model_id: str, temperature: float):
        self.model_id = model_id
        self.temperature = temperature
        self.calls = 0

    def complete(self, req: LLMRequest) -> str:
        raise LLMError("no cached response for this request and no OPENROUTER_API_KEY set")
