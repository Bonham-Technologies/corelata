"""Records every layer shares: one model call, and usage totals (copied from Coglossa)."""

from typing import Any

from pydantic import BaseModel, Field


class LLMCallRecord(BaseModel):
    role: str
    backend: str
    model: str
    prompt_id: str
    prompt_version: int
    attempt: int
    ok: bool
    latency_ms: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    request: dict[str, Any] | None = None  # only when audit.store_llm_io
    response: str | None = None  # only when audit.store_llm_io
    # CRL-140: the model's reasoning, cut to models.<key>.reasoning_max_chars, and its whole
    # length; only when the model's store_reasoning and audit.store_llm_io are both on and the
    # reply had some. Left out of the dump when absent, so other traces read as before.
    reasoning: str | None = Field(None, exclude_if=lambda v: v is None)
    reasoning_chars: int | None = Field(None, exclude_if=lambda v: v is None)


class Usage(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    by_role: dict[str, dict[str, int]]
