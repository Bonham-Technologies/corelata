"""Adapter for any OpenAI-compatible server: vLLM, Ollama, TGI, llama.cpp, LM Studio."""

import asyncio
import time
from typing import Any

import httpx

from corelata.config import StructuredOutput
from corelata.llm.schema import strict_json_schema
from corelata.llm.types import (
    ChatRequest,
    ChatResponse,
    ContextOverflowError,
    OutputTruncatedError,
    PermanentBackendError,
    TransientBackendError,
)

_OVERFLOW_MARKERS = (
    "context length",
    "context_length",
    "maximum context",
    "context window",
    "too many tokens",
    "prompt is too long",
)


class OpenAICompatBackend:
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        api_key: str | None = None,
        max_concurrency: int = 4,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=timeout_s,
            transport=transport,
        )
        self._sem = asyncio.Semaphore(max_concurrency)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        async with self._sem:
            started = time.monotonic()
            resp = await self._send("POST", "chat/completions", json=_payload(request))
            latency_ms = int((time.monotonic() - started) * 1000)
        return _parse_chat(self.name, resp, latency_ms)

    async def list_models(self) -> list[str]:
        resp = await self._send("GET", "models")
        try:
            return [m["id"] for m in resp.json()["data"]]
        except (ValueError, KeyError, TypeError) as e:
            raise PermanentBackendError(f"{self.name}: malformed /models response") from e

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise TransientBackendError(f"{self.name}: timeout calling {path}") from e
        except httpx.ConnectError as e:
            # down, not listening, or a name that does not resolve: say which server (CRL-1 D2)
            raise TransientBackendError(
                f"{self.name}: model server unreachable ({_shown(self._client.base_url)}): "
                f"{type(e).__name__}: {e}"
            ) from e
        except httpx.TransportError as e:
            raise TransientBackendError(f"{self.name}: {type(e).__name__}: {e}") from e
        _raise_for_status(self.name, resp)
        return resp


def _shown(url: httpx.URL) -> str:
    """The server's URL for an error message: no credentials, query, fragment or trailing slash."""
    bare = url.copy_with(username=None, password=None, query=None, fragment=None)
    return str(bare).rstrip("/")


def _payload(request: ChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "temperature": request.temperature,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.structured_output is StructuredOutput.JSON_SCHEMA:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.schema_name,
                "strict": True,
                "schema": strict_json_schema(request.json_schema),
            },
        }
    elif request.structured_output is StructuredOutput.JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _raise_for_status(name: str, resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    body = resp.text[:500]
    message = f"{name}: HTTP {resp.status_code}: {body}"
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientBackendError(message)
    if any(marker in body.lower() for marker in _OVERFLOW_MARKERS):
        raise ContextOverflowError(message)
    raise PermanentBackendError(message)


def _parse_chat(name: str, resp: httpx.Response, latency_ms: int) -> ChatResponse:
    try:
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise PermanentBackendError(f"{name}: malformed chat completion response") from e
    if choice.get("finish_reason") == "length":
        raise OutputTruncatedError(f"{name}: output truncated (finish_reason=length)")
    if not isinstance(content, str):
        raise PermanentBackendError(f"{name}: chat completion has no text content")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return ChatResponse(
        content=content,
        tokens_in=_count(usage.get("prompt_tokens")),
        tokens_out=_count(usage.get("completion_tokens")),
        latency_ms=latency_ms,
    )


def _count(value: object) -> int | None:
    """A token count, or None when a server reports something that is not an integer."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
