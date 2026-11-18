"""One agent call: prompt + JSON input -> validated Pydantic output (spec §4.5).

Flow: render prompt -> call backend (transient errors retried with backoff) -> extract JSON ->
validate (schema + optional semantic validator) -> on failure, one repair turn -> else
StructuredOutputError. Every backend attempt is recorded in the CallLog."""

import asyncio
import itertools
import json
import random
import re
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from corelata.config import CorelataConfig, ModelConfig, StructuredOutput
from corelata.llm.payload import render_input
from corelata.llm.retry import RetryPolicy, call_with_retry
from corelata.llm.types import Backend, BackendError, ChatMessage, ChatRequest
from corelata.prompts.library import PromptLibrary, RenderedPrompt
from corelata.schema import LLMCallRecord, Usage


class StructuredOutputError(Exception):
    def __init__(self, message: str, *, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


# A pydantic literal error listing more values than this is not repeated in a repair message.
MAX_LISTED_VALUES = 5

AGENT_FAILURES: tuple[type[Exception], ...] = (StructuredOutputError, BackendError)

_WHOLE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*)\n?```$", re.DOTALL | re.IGNORECASE)


def extract_json(content: str) -> str:
    """Pull the JSON object out of replies that wrap it in prose or Markdown fences."""
    text = content.strip()
    try:
        json.loads(text)
    except ValueError:
        pass
    else:
        return text  # already valid: never touch fences that live inside JSON strings
    fence = _WHOLE_FENCE_RE.match(text)
    if fence:
        return fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        return text[start : end + 1]
    return text


def _repair_message(errors: list[str]) -> str:
    bullets = "\n".join(f"- {e}" for e in errors[:20])
    return (
        "Your previous response was rejected. Fix every point below and return the complete "
        f"corrected JSON object only:\n{bullets}"
    )


def repair_messages(
    messages: list[ChatMessage], content: str, errors: list[str]
) -> list[ChatMessage]:
    """The one repair turn of a structured call: the first turn's messages, the rejected reply as
    the model sent it, and the rejection with every error. `AgentRunner.run` and `corelata
    doctor`'s probes both build it here, so a probe repairs exactly as a run does (R-M15-5)."""
    return [
        *messages,
        ChatMessage(role="assistant", content=content),
        ChatMessage(role="user", content=_repair_message(errors)),
    ]


def rejection_errors(error: ValidationError) -> list[str]:
    """A reply's validation errors as the repair turn lists them."""
    return [_describe(err) for err in error.errors()]


def request_messages(
    system: str, payload: dict[str, Any], model: ModelConfig, schema: dict[str, Any]
) -> list[ChatMessage]:
    """The first turn of a structured call: the system prompt and the input. A server that does
    not enforce the schema (`json_object`, `none`) gets it spelled out in the system prompt."""
    if model.structured_output is not StructuredOutput.JSON_SCHEMA:
        spelled = json.dumps(schema, ensure_ascii=False)
        system += f"\n\nRespond with one JSON object that matches this JSON Schema:\n{spelled}"
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=render_input(payload)),
    ]


def build_request(
    model_key: str,
    model: ModelConfig,
    output_type: type[BaseModel],
    schema: dict[str, Any],
    messages: list[ChatMessage],
    *,
    max_tokens: int | None = None,
) -> ChatRequest:
    """The request every structured call sends: each stage through `AgentRunner.run`, and
    `corelata doctor`'s probe (R-M12-3). The backend turns `json_schema` into the strict response
    format (`llm/schema.py`), so the probe and a run send the same schema. `max_tokens`
    overrides the model's `max_output_tokens`."""
    return ChatRequest(
        model=model.name or model_key,
        messages=messages,
        schema_name=output_type.__name__,
        json_schema=schema,
        structured_output=model.structured_output,
        temperature=model.temperature,
        max_tokens=model.max_output_tokens if max_tokens is None else max_tokens,
    )


@dataclass
class CallLog:
    store_io: bool = True
    records: list[LLMCallRecord] = field(default_factory=list)

    def add(self, record: LLMCallRecord) -> None:
        self.records.append(record)

    def usage(self) -> Usage:
        by_role: dict[str, dict[str, int]] = {}
        for r in self.records:
            d = by_role.setdefault(r.role, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
            d["calls"] += 1
            d["tokens_in"] += r.tokens_in or 0
            d["tokens_out"] += r.tokens_out or 0
        return Usage(
            calls=len(self.records),
            tokens_in=sum(d["tokens_in"] for d in by_role.values()),
            tokens_out=sum(d["tokens_out"] for d in by_role.values()),
            by_role=by_role,
        )


class AgentRunner:
    def __init__(
        self,
        cfg: CorelataConfig,
        backends: dict[str, Backend],
        prompts: PromptLibrary,
        log: CallLog,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.cfg = cfg
        self.log = log
        self.prompts = prompts
        self._backends = backends
        self._policy = RetryPolicy.from_config(cfg.retry)
        self._sleep = sleep
        self._rng = rng or random.Random()

    async def run[M: BaseModel](
        self,
        *,
        role: str,
        model_key: str,
        prompt_id: str,
        prompt_vars: dict[str, Any],
        payload: dict[str, Any],
        output_type: type[M],
        validate: Callable[[M], list[str]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> M:
        """A caller may send a stricter schema than the type it parses with (the writer's unit
        enum, R-M12-8): `schema` replaces `output_type`'s in the request and the system prompt."""
        model = self.cfg.models[model_key]
        backend = self._backends[model.backend]
        prompt = self.prompts.render(prompt_id, **prompt_vars)
        schema = schema if schema is not None else output_type.model_json_schema()
        messages = request_messages(prompt.text, payload, model, schema)
        content = ""
        errors: list[str] = []
        attempts = itertools.count(1)  # numbers every backend call of this run, repair included
        for _ in range(2):  # first attempt + one repair turn
            if errors:
                messages = repair_messages(messages, content, errors)
            request = build_request(model_key, model, output_type, schema, messages)
            content, record = await self._call(role, backend, request, prompt, attempts)
            result, errors = _parse(content, output_type, validate)
            if result is not None and not errors:
                return result
            # `ok` means "usable output": the backend call succeeded but its reply was rejected.
            record.ok = False
            record.error = f"invalid output: {'; '.join(errors[:3])}"
        raise StructuredOutputError(
            f"{role}: invalid output after repair: {'; '.join(errors[:5])}", raw=content
        )

    async def _call(
        self,
        role: str,
        backend: Backend,
        request: ChatRequest,
        prompt: RenderedPrompt,
        attempts: Iterator[int],
    ) -> tuple[str, LLMCallRecord]:
        last: LLMCallRecord

        async def once() -> str:
            nonlocal last
            attempt = next(attempts)
            try:
                resp = await backend.chat(request)
            except BackendError as e:
                self._record(role, backend, request, prompt, attempt, ok=False, error=str(e))
                raise
            last = self._record(
                role,
                backend,
                request,
                prompt,
                attempt,
                ok=True,
                latency_ms=resp.latency_ms,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                response=resp.content,
            )
            return resp.content

        content = await call_with_retry(once, self._policy, sleep=self._sleep, rng=self._rng)
        return content, last

    def _record(
        self,
        role: str,
        backend: Backend,
        request: ChatRequest,
        prompt: RenderedPrompt,
        attempt: int,
        *,
        ok: bool,
        error: str | None = None,
        latency_ms: int = 0,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        response: str | None = None,
    ) -> LLMCallRecord:
        store = self.log.store_io
        record = LLMCallRecord(
            role=role,
            backend=backend.name,
            model=request.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            attempt=attempt,
            ok=ok,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
            request={"messages": [m.model_dump() for m in request.messages]} if store else None,
            response=response if store else None,
        )
        self.log.add(record)
        return record


def _describe(err: Any) -> str:
    """One pydantic error as a repair line; a long enum is never listed in full (R-M11-7),
    whether it is a `Literal` (`literal_error`) or a hoisted `StrEnum` (`enum`, R-M12-1)."""
    where = ".".join(str(p) for p in err["loc"]) or "<root>"
    if err["type"] in ("literal_error", "enum"):
        values = re.findall(r"'([^']*)'", err["ctx"]["expected"])
        if len(values) > MAX_LISTED_VALUES:
            some = ", ".join(f"'{v}'" for v in values[:3])
            return f"{where}: use one of the values given in the input (such as {some})"
    return f"{where}: {err['msg']}"


def _parse[M: BaseModel](
    content: str, output_type: type[M], validate: Callable[[M], list[str]] | None
) -> tuple[M | None, list[str]]:
    try:
        obj = output_type.model_validate_json(extract_json(content))
    except ValidationError as e:
        return None, rejection_errors(e)
    return obj, (validate(obj) if validate else [])
