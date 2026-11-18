import json

import pytest

from corelata.config import StructuredOutput
from corelata.llm.payload import render_input
from corelata.llm.types import ChatMessage, ChatRequest, TransientBackendError
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.synthetic import synthetic_response

PING = {"task": "ping"}


def _req(payload: dict) -> ChatRequest:
    return ChatRequest(
        model="fake-model",
        messages=[
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content=render_input(payload)),
        ],
        schema_name="X",
        json_schema={},
        structured_output=StructuredOutput.JSON_SCHEMA,
    )


async def test_answers_synthetically_and_records_requests():
    backend = FakeBackend()
    resp = await backend.chat(_req(PING))
    assert json.loads(resp.content) == {"ok": True}
    assert len(backend.requests) == 1
    assert await backend.list_models() == ["fake-model"]


async def test_scripted_items_are_consumed_in_order_per_task():
    backend = FakeBackend()
    backend.script("ping", "not json", TransientBackendError("busy"))
    assert (await backend.chat(_req(PING))).content == "not json"
    with pytest.raises(TransientBackendError):
        await backend.chat(_req(PING))
    # script exhausted -> synthetic again
    assert json.loads((await backend.chat(_req(PING))).content) == {"ok": True}


async def test_aclose_marks_closed():
    backend = FakeBackend()
    await backend.aclose()
    assert backend.closed is True


def test_synthetic_unknown_task():
    with pytest.raises(ValueError, match="unknown task 'nope'"):
        synthetic_response({"task": "nope"})
