"""Disk cache and the OpenRouter client's retry policy, with the network replaced by a fake."""
from types import SimpleNamespace

import httpx
import openai
import pytest

from itc.config import load_config
from itc.llm import LLMError, LLMRequest
from itc.llm.cache import DiskCache, cache_key
from itc.llm.client import CachedLLM, OfflineLLM, OpenRouterLLM

CFG = load_config()["llm"]


def req(run_index=0, content="hello"):
    return LLMRequest(messages=[{"role": "user", "content": content}], response_format={"type": "json_object"},
                      run_index=run_index, prompt_version="classify_v1", rule_pack_version="2026.11.0",
                      lines=[{"line_id": "L1"}])


def http_error(cls, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    return cls("err", response=response, body=None)


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))])


def client_with(outcomes):
    sleeps = []
    llm = OpenRouterLLM(CFG, api_key="test-key", sleep=sleeps.append)
    fake = FakeCompletions(outcomes)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return llm, fake, sleeps


def test_cache_key_changes_with_every_component():
    base = ("m", "p1", "v1", 0.3, [{"c": 1}], 0)
    k = cache_key(*base)
    for i, alt in enumerate(["m2", "p2", "v2", 0.4, [{"c": 2}], 1]):
        changed = list(base)
        changed[i] = alt
        assert cache_key(*changed) != k


def test_success_sends_pinned_model_and_temperature():
    llm, fake, _ = client_with(['{"lines": []}'])
    assert llm.complete(req()) == '{"lines": []}'
    assert fake.kwargs[0]["model"] == CFG["model_id"] and fake.kwargs[0]["temperature"] == CFG["temperature"]


def test_backoff_on_429_then_success():
    llm, _, sleeps = client_with([http_error(openai.RateLimitError, 429)] * 2 + ["ok"])
    assert llm.complete(req()) == "ok"
    assert sleeps == [CFG["backoff_base_seconds"], CFG["backoff_base_seconds"] * 2]
    assert llm.calls == 3


def test_retries_are_capped():
    llm, _, sleeps = client_with([http_error(openai.RateLimitError, 429)] * (CFG["max_retries"] + 1))
    with pytest.raises(LLMError, match="gave up"):
        llm.complete(req())
    assert len(sleeps) == CFG["max_retries"]


def test_client_error_is_not_retried():
    llm, _, sleeps = client_with([http_error(openai.BadRequestError, 400)])
    with pytest.raises(LLMError, match="HTTP 400"):
        llm.complete(req())
    assert sleeps == []


def test_empty_response_is_retried():
    llm, _, _ = client_with(["", "ok"])
    assert llm.complete(req()) == "ok"


def test_cached_llm_second_call_costs_nothing(tmp_path):
    llm, fake, _ = client_with(["first"])
    cached = CachedLLM(llm, DiskCache(tmp_path))
    assert cached.complete(req()) == "first"
    assert cached.complete(req()) == "first"
    assert len(fake.kwargs) == 1 and cached.hits == 1 and cached.misses == 1


def test_cache_separates_runs(tmp_path):
    llm, fake, _ = client_with(["run0", "run1"])
    cached = CachedLLM(llm, DiskCache(tmp_path))
    assert cached.complete(req(0)) == "run0"
    assert cached.complete(req(1)) == "run1"


def test_offline_serves_cache_and_fails_clearly_on_miss(tmp_path):
    llm, _, _ = client_with(["stored"])
    CachedLLM(llm, DiskCache(tmp_path)).complete(req())
    offline = CachedLLM(OfflineLLM(CFG["model_id"], CFG["temperature"]), DiskCache(tmp_path))
    assert offline.complete(req()) == "stored"
    with pytest.raises(LLMError, match="no OPENROUTER_API_KEY"):
        offline.complete(req(content="different"))
