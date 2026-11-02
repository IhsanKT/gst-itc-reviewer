"""LLM access: prompt rendering, the OpenRouter client, the on-disk cache and the deterministic mock."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMRequest:
    """Everything one call needs. Real clients read `messages`; the mock reads the structured fields."""
    messages: list[dict]
    response_format: dict
    run_index: int
    prompt_version: str
    rule_pack_version: str
    lines: list[dict] = field(default_factory=list)
    profile: dict = field(default_factory=dict)
    allowed_ids: list[str] = field(default_factory=list)


class LLMError(RuntimeError):
    """The call failed after all retries. The caller records it; it never becomes a label."""
