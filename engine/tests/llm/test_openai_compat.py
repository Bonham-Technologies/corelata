import asyncio
import json

import httpx
import pytest

from corelata.config import StructuredOutput
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.types import (
    ChatMessage,
    ChatRequest,
    ContextOverflowError,
    OutputTruncatedError,
    PermanentBackendError,
    TransientBackendError,
)

_SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "string", "default": "x"}},
    "required": ["a"],
}


def _req(mode: StructuredOutput = StructuredOutput.JSON_SCHEMA, max_tokens=None) -> ChatRequest:
    return ChatRequest(
        model="m1",
        messages=[ChatMessage(role="user", content="hi")],
        schema_name="Out",
        json_schema=_SCHEMA,
        structured_output=mode,
        max_tokens=max_tokens,
    )


def _ok(content="{}", finish="stop", usage=True) -> httpx.Response:
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]
    }
    if usage:
        body["usage"] = {"prompt_tokens": 5, "completion_tokens": 7}
    return httpx.Response(200, json=body)


def _backend(handler, **kw) -> OpenAICompatBackend:
    return OpenAICompatBackend("gpu-a", "http://x/v1", transport=httpx.MockTransport(handler), **kw)


async def test_chat_posts_openai_payload_with_json_schema():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _ok('{"a": 1}')

    backend = _backend(handler, api_key="k")
    resp = await backend.chat(_req(max_tokens=64))
    assert seen["url"] == "http://x/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "Out",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
    sent = seen["body"]["response_format"]["json_schema"]["schema"]
    assert sent["required"] == ["a", "b"]
    assert "default" not in sent["properties"]["b"]
    assert seen["body"]["max_tokens"] == 64
    assert resp.content == '{"a": 1}'
    assert (resp.tokens_in, resp.tokens_out) == (5, 7)
    await backend.aclose()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(StructuredOutput.JSON_OBJECT, {"type": "json_object"}), (StructuredOutput.NONE, None)],
)
async def test_chat_response_format_modes(mode, expected):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _ok(usage=False)

    resp = await _backend(handler).chat(_req(mode))
    assert seen["body"].get("response_format") == expected
    assert "max_tokens" not in seen["body"]
    assert resp.tokens_in is None


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_statuses_are_transient(status):
    backend = _backend(lambda r: httpx.Response(status, text="busy"))
    with pytest.raises(TransientBackendError, match=f"HTTP {status}"):
        await backend.chat(_req())


async def test_context_overflow_is_detected():
    msg = {"error": {"message": "This model's maximum context length is 8192 tokens"}}
    backend = _backend(lambda r: httpx.Response(400, json=msg))
    with pytest.raises(ContextOverflowError):
        await backend.chat(_req())


async def test_other_client_errors_are_permanent():
    backend = _backend(lambda r: httpx.Response(404, text="model not found"))
    with pytest.raises(PermanentBackendError, match="HTTP 404"):
        await backend.chat(_req())


async def test_timeout_and_connection_errors_are_transient():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TransientBackendError, match="timeout"):
        await _backend(timeout).chat(_req())
    with pytest.raises(TransientBackendError, match="ConnectError"):
        await _backend(refused).chat(_req())


async def test_an_unreachable_server_is_named_in_the_error():
    """What a run's error says when the model server is down (CRL-1 D2)."""

    def unresolved(request):
        raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution", request=request)

    backend = OpenAICompatBackend(
        "demo",
        "http://user:secret@fake-openai:8000/v1/",
        transport=httpx.MockTransport(unresolved),
    )
    with pytest.raises(TransientBackendError) as raised:
        await backend.chat(_req())
    assert str(raised.value) == (
        "demo: model server unreachable (http://fake-openai:8000/v1): "
        "ConnectError: [Errno -3] Temporary failure in name resolution"
    )
    with pytest.raises(TransientBackendError, match=r"^demo: model server unreachable \("):
        await backend.list_models()  # every request through the backend names it

    def reset(request):  # another transport error keeps its plain message
        raise httpx.ReadError("connection reset", request=request)

    with pytest.raises(TransientBackendError) as raised:
        await _backend(reset).chat(_req())
    assert str(raised.value) == "gpu-a: ReadError: connection reset"


@pytest.mark.parametrize(
    ("base_url", "shown"),
    [
        ("http://user:secret@fake-openai:8000/v1/", "http://fake-openai:8000/v1"),
        ("http://h/v1?key=abc", "http://h/v1"),
        ("http://h/v1/?key=abc#frag", "http://h/v1"),
        ("http://h:8000", "http://h:8000"),
    ],
)
async def test_the_shown_server_has_no_credentials_query_fragment_or_slash(base_url, shown):
    def unresolved(request):
        raise httpx.ConnectError("refused", request=request)

    backend = OpenAICompatBackend("demo", base_url, transport=httpx.MockTransport(unresolved))
    with pytest.raises(TransientBackendError) as raised:
        await backend.chat(_req())
    assert str(raised.value) == f"demo: model server unreachable ({shown}): ConnectError: refused"
    await backend.aclose()


async def test_truncated_output_raises():
    with pytest.raises(OutputTruncatedError):
        await _backend(lambda r: _ok(finish="length")).chat(_req())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    ],
)
async def test_malformed_responses_are_permanent(response):
    with pytest.raises(PermanentBackendError):
        await _backend(lambda r: response).chat(_req())


async def test_list_models():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    assert await _backend(handler).list_models() == ["a", "b"]


async def test_list_models_malformed_and_errors():
    with pytest.raises(PermanentBackendError):
        await _backend(lambda r: httpx.Response(200, json={"nope": 1})).list_models()
    with pytest.raises(TransientBackendError):
        await _backend(lambda r: httpx.Response(502, text="bad gateway")).list_models()


async def test_concurrency_is_limited():
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _ok()

    backend = _backend(handler, max_concurrency=2)
    await asyncio.gather(*(backend.chat(_req()) for _ in range(6)))
    assert peak == 2


@pytest.mark.parametrize(
    "usage",
    [
        "oops",
        ["x"],
        {"prompt_tokens": "5", "completion_tokens": None},
        {"prompt_tokens": True, "completion_tokens": 1.5},
    ],
)
async def test_malformed_usage_becomes_none(usage):
    body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": usage}
    resp = await _backend(lambda r: httpx.Response(200, json=body)).chat(_req())
    assert resp.tokens_in is None and resp.tokens_out is None
