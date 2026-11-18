"""Records every layer shares: one model call, and usage totals (copied from Coglossa)."""

from typing import Any

from pydantic import BaseModel


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


class Usage(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    by_role: dict[str, dict[str, int]]
