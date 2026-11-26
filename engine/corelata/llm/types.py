"""The Backend protocol: the only way Corelata talks to models."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from corelata.config import StructuredOutput


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    schema_name: str
    json_schema: dict[str, Any]
    structured_output: StructuredOutput
    temperature: float = 0.2
    max_tokens: int | None = None
    # the model's `request_extra`, merged into the request body as given (CRL-140)
    extra: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    content: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int = 0
    # what the server returned beside the content as the model's reasoning (CRL-140)
    reasoning: str | None = None


class BackendError(Exception):
    """A model call failed."""


class TransientBackendError(BackendError):
    """Worth retrying: timeouts, connection failures, HTTP 429 and 5xx."""


class PermanentBackendError(BackendError):
    """Retrying the same request will not help."""


class ContextOverflowError(PermanentBackendError):
    """The prompt exceeded the model's context window."""


class OutputTruncatedError(PermanentBackendError):
    """The model stopped because it hit its output token limit."""


class Backend(Protocol):
    name: str

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    async def list_models(self) -> list[str]: ...

    async def aclose(self) -> None: ...


# The request was too big for the model: the caller should send less (spec §7.2).
OVERSIZE_ERRORS: tuple[type[Exception], ...] = (ContextOverflowError, OutputTruncatedError)
