import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from corelata.config import StructuredOutput
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.payload import render_input
from corelata.llm.types import (
    ChatMessage,
    ChatRequest,
    ContextOverflowError,
    OutputTruncatedError,
    PermanentBackendError,
)
from corelata.testing.fake_openai import FakeOpenAIServer

PING = {"task": "ping"}


def _req(content: str) -> ChatRequest:
    return ChatRequest(
        model="fake-model",
        messages=[ChatMessage(role="user", content=content)],
        schema_name="X",
        json_schema={},
        structured_output=StructuredOutput.JSON_SCHEMA,
    )


async def test_chat_and_models_over_http():
    with FakeOpenAIServer(models=("m1", "m2")) as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        resp = await backend.chat(_req(render_input(PING)))
        assert json.loads(resp.content) == {"ok": True}
        assert await backend.list_models() == ["m1", "m2"]
        assert server.requests[0]["model"] == "fake-model"
        await backend.aclose()


async def test_bad_requests_get_400_and_unknown_paths_404():
    with FakeOpenAIServer() as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        with pytest.raises(PermanentBackendError, match="HTTP 400"):
            await backend.chat(_req("no marker here"))
        await backend.aclose()
        async with httpx.AsyncClient() as client:
            assert (await client.get(server.base_url + "/nope")).status_code == 404
            assert (await client.post(server.base_url + "/nope", json={})).status_code == 404


def test_start_stop_idempotent():
    server = FakeOpenAIServer().start()
    assert server.base_url.startswith("http://127.0.0.1:")
    server.stop()
    server.stop()


async def test_context_window_ping_probe_and_length_finish():
    with FakeOpenAIServer(context_window=100) as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        ping = await backend.chat(_req(render_input(PING)))
        assert json.loads(ping.content) == {"ok": True}
        with pytest.raises(ContextOverflowError, match="maximum context length"):
            await backend.chat(_req(render_input({"task": "probe", "filler": "a " * 200})))
        one = _req(render_input(PING)).model_copy(update={"max_tokens": 1})
        with pytest.raises(OutputTruncatedError):
            await backend.chat(one)
        await backend.aclose()


def _post(url: str) -> None:
    httpx.post(
        f"{url}/chat/completions",
        json={
            "model": "fake-model",
            "messages": [{"role": "user", "content": render_input(PING)}],
        },
        timeout=10,
    ).raise_for_status()


def test_max_in_flight_counts_concurrent_requests():
    with FakeOpenAIServer(delay_s=0.3) as server:
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(lambda _: _post(server.base_url), range(3)))
        assert server.max_in_flight == 3


def test_max_in_flight_is_one_for_sequential_requests():
    with FakeOpenAIServer(delay_s=0.01) as server:
        for _ in range(3):
            _post(server.base_url)
        assert server.max_in_flight == 1


def test_the_fake_openai_server_can_forget_requests():
    server = FakeOpenAIServer(keep_requests=False).start()
    try:
        body = {
            "model": "fake-model",
            "messages": [{"role": "user", "content": render_input(PING)}],
        }
        with httpx.Client() as client:
            assert client.post(f"{server.base_url}/chat/completions", json=body).status_code == 200
        assert server.requests == []
    finally:
        server.stop()
