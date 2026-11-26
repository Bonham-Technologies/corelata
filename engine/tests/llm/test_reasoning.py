"""CRL-140: reasoning models. `request_extra` reaches the server as given, the model's reasoning
is kept with its call record when the model opts in, and a leading <think> block costs no repair
turn."""

import json
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import BaseModel, ValidationError

from corelata.config import (
    REASONING_MAX_CHARS,
    RESERVED_REQUEST_KEYS,
    ConfigError,
    config_hash,
    load_config,
)
from corelata.llm.agent import (
    AgentRunner,
    CallLog,
    build_request,
    extract_json,
    reply_reasoning,
    request_messages,
    split_think,
)
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.types import ChatResponse
from corelata.prompts.library import PromptLibrary
from corelata.schema import GateVerdict
from corelata.testing.fake_openai import FAKE_REASONING, FakeOpenAIServer
from corelata.trace import run_trace
from tests.conftest import BASE_CONFIG, build_config

PROMPTS = Path(__file__).parent.parent / "fixtures" / "prompts"


class Ping(BaseModel):
    ok: bool


def _model_cfg(**model):
    models = dict(BASE_CONFIG["models"])
    models["model-a"] = {**models["model-a"], **model}
    return build_config(models=models)


# --- config ----------------------------------------------------------------------------------


def test_the_reasoning_settings_are_off_by_default_and_leave_the_dump(make_config):
    model = make_config().models["model-a"]
    assert model.request_extra == {}
    assert model.store_reasoning is False
    assert model.reasoning_max_chars == REASONING_MAX_CHARS == 20000
    dumped = model.model_dump()
    assert not {"request_extra", "store_reasoning", "reasoning_max_chars"} & dumped.keys()


def test_request_extra_shapes_output_and_storing_reasoning_does_not(make_config):
    plain = config_hash(make_config())
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    assert config_hash(_model_cfg(request_extra=off)) != plain
    assert config_hash(_model_cfg(store_reasoning=True, reasoning_max_chars=10)) == plain


@pytest.mark.parametrize("key", sorted(RESERVED_REQUEST_KEYS))
def test_request_extra_refuses_the_keys_corelata_sets(tmp_path, key):
    data = {**BASE_CONFIG, "models": {**BASE_CONFIG["models"]}}
    data["models"]["model-a"] = {**data["models"]["model-a"], "request_extra": {key: 1}}
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(
        ConfigError, match=rf"models\.model-a\.request_extra: .*'{key}' cannot be sent"
    ):
        load_config(path)


def test_the_reserved_keys_are_every_key_the_client_sets():
    assert set(RESERVED_REQUEST_KEYS) == {
        "model",
        "messages",
        "response_format",
        "temperature",
        "max_tokens",
        "stream",
        # not sent by Corelata, but the client reads only the first choice's text
        "n",
        "tools",
        "tool_choice",
        "functions",
        "function_call",
    }


def test_request_extra_must_be_json_and_null_means_none(tmp_path):
    data = {**BASE_CONFIG, "models": {**BASE_CONFIG["models"]}}
    data["models"]["model-a"] = {**data["models"]["model-a"], "request_extra": None}
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load_config(path)[0].models["model-a"].request_extra == {}
    # YAML reads an unquoted date as a date, which no request body can carry
    path.write_text(
        yaml.safe_dump(data).replace("request_extra: null", "request_extra: {since: 2026-01-02}"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must hold JSON values only"):
        load_config(path)
    with pytest.raises(ValidationError, match="must hold JSON values only"):
        _model_cfg(request_extra={"x": float("nan")})


def test_reasoning_max_chars_is_at_least_one():
    with pytest.raises(ValidationError):
        _model_cfg(reasoning_max_chars=0)


# --- the request -----------------------------------------------------------------------------


async def _body_of(cfg, model_key="model-a") -> bytes:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        reply = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=reply)

    backend = OpenAICompatBackend("b", "http://x/v1", transport=httpx.MockTransport(handler))
    model = cfg.models[model_key]
    schema = Ping.model_json_schema()
    messages = request_messages("Say ok.", {"task": "ping"}, model, schema)
    await backend.chat(build_request(model_key, model, Ping, schema, messages))
    await backend.aclose()
    return seen[0]


async def test_without_request_extra_the_request_is_byte_identical_to_before(make_config):
    """Acceptance 5: the body a model without request_extra gets is the one sent before
    CRL-140, byte for byte: the same keys in the same order, nothing added."""
    cfg = make_config()
    model = cfg.models["model-a"]
    schema = Ping.model_json_schema()
    messages = request_messages("Say ok.", {"task": "ping"}, model, schema)
    before = {
        "model": "model-a",
        "messages": [m.model_dump() for m in messages],
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "Ping",
                "strict": True,
                "schema": {
                    "properties": {"ok": {"title": "Ok", "type": "boolean"}},
                    "required": ["ok"],
                    "title": "Ping",
                    "type": "object",
                    "additionalProperties": False,
                },
            },
        },
    }
    expected = httpx.Request("POST", "http://x/v1/chat/completions", json=before).content
    assert await _body_of(cfg) == expected


async def test_request_extra_is_sent_verbatim_after_corelatas_keys():
    extra = {
        "chat_template_kwargs": {"enable_thinking": False},
        "top_p": 0.95,
        "reasoning_effort": "low",
    }
    body = json.loads(await _body_of(_model_cfg(request_extra=extra, max_output_tokens=300)))
    assert list(body) == [
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
        *extra,
    ]
    assert {k: body[k] for k in extra} == extra
    assert (body["temperature"], body["max_tokens"]) == (0.2, 300)


# --- the reply -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "reasoning"),
    [
        ({"reasoning": "because"}, "because"),
        ({"reasoning_content": "since"}, "since"),
        ({"reasoning": "first", "reasoning_content": "second"}, "first"),
        ({"reasoning": "  ", "reasoning_content": "second"}, "second"),
        ({"reasoning": None}, None),
        ({"reasoning": 3}, None),
        ({}, None),
    ],
)
async def test_the_client_reads_the_reasoning_field(message, reasoning):
    def handler(request: httpx.Request) -> httpx.Response:
        reply = {"message": {"content": "{}", **message}, "finish_reason": "stop"}
        return httpx.Response(200, json={"choices": [reply]})

    backend = OpenAICompatBackend("b", "http://x/v1", transport=httpx.MockTransport(handler))
    cfg = build_config()
    request = build_request("model-a", cfg.models["model-a"], Ping, {}, [])
    assert (await backend.chat(request)).reasoning == reasoning
    await backend.aclose()


@pytest.mark.parametrize(
    ("content", "reasoning", "rest"),
    [
        ('<think>\nuse {a} and {b}\n</think>\n\n{"ok": true}', "use {a} and {b}", '{"ok": true}'),
        ('  <THINK>x</THINK>{"ok": true}', "x", '{"ok": true}'),
        ('{"ok": true}', None, '{"ok": true}'),
        ('Sure. <think>x</think>{"ok": true}', None, 'Sure. <think>x</think>{"ok": true}'),
        ("<think>never closed {", None, "<think>never closed {"),
    ],
)
def test_split_think_takes_only_a_leading_block(content, reasoning, rest):
    got_reasoning, got_rest = split_think(content)
    assert got_reasoning == reasoning
    assert got_rest.strip() == rest.strip()


def test_extract_json_skips_a_leading_think_block_with_braces():
    content = '<think>The object is {"ok": false}? No: {ok}.</think>\n```json\n{"ok": true}\n```'
    assert extract_json(content) == '{"ok": true}'


def test_reply_reasoning_prefers_the_field_then_the_think_block():
    assert reply_reasoning(ChatResponse(content="<think>b</think>{}", reasoning="a")) == "a"
    assert reply_reasoning(ChatResponse(content="<think> b </think>{}")) == "b"
    assert reply_reasoning(ChatResponse(content="<think> </think>{}")) is None
    assert reply_reasoning(ChatResponse(content="{}")) is None


# --- the record and the trace ----------------------------------------------------------------


def _runner(cfg, backend, *, store_io=True) -> AgentRunner:
    async def no_sleep(_: float) -> None:
        return None

    return AgentRunner(
        cfg, {"fake": backend}, PromptLibrary(PROMPTS), CallLog(store_io=store_io), sleep=no_sleep
    )


async def _ping(runner):
    return await runner.run(
        role="gate",
        model_key="model-a",
        prompt_id="ping",
        prompt_vars={"product": "Corelata"},
        payload={"task": "ping"},
        output_type=Ping,
    )


@pytest.mark.parametrize("mode", ["reasoning", "reasoning_content", "think"])
async def test_a_reasoning_reply_parses_first_time_and_its_reasoning_is_stored(mode):
    """Acceptance 2 and 3, against the synthetic model over HTTP."""
    cfg = _model_cfg(store_reasoning=True)
    with FakeOpenAIServer(models=("model-a",), reasoning=mode) as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        runner = _runner(cfg, backend)
        assert (await _ping(runner)).ok is True
        await backend.aclose()
    [record] = runner.log.records  # no repair turn
    assert record.ok and record.attempt == 1
    assert record.reasoning == FAKE_REASONING
    assert record.reasoning_chars == len(FAKE_REASONING)
    assert record.model_dump(mode="json")["reasoning"] == FAKE_REASONING


async def test_a_runs_trace_keeps_the_reasoning_and_its_view_leaves_it_out(run, fake_backend):
    """Acceptance 2: trace.json (the RunRecord) carries it; the Process tab's view does not."""
    real = fake_backend.chat

    async def reasoning_chat(request):
        return (await real(request)).model_copy(update={"reasoning": "weighing the units"})

    fake_backend.chat = reasoning_chat
    cfg = build_config(
        models={
            "model-a": {"backend": "fake", "context_window": 32768, "store_reasoning": True},
            "model-b": {"backend": "fake", "context_window": 32768},
        }
    )
    rec = await run(cfg=cfg)
    by_role = {c.role: c for c in rec.llm_calls}
    assert by_role["gate"].reasoning == "weighing the units"  # model-a opted in
    assert by_role["auditor"].reasoning is None  # model-b did not
    dumped = json.loads(rec.model_dump_json())["llm_calls"]
    assert dumped[0]["reasoning"] == "weighing the units" and dumped[0]["reasoning_chars"] == 18
    assert all("reasoning" not in c.model_dump() for c in run_trace(rec).calls)


async def test_reasoning_is_cut_to_the_cap_and_its_length_kept(fake_backend):
    cfg = _model_cfg(store_reasoning=True, reasoning_max_chars=10)
    fake_backend.script("ping", "<think>" + "x" * 25 + '</think>{"ok": true}')
    runner = _runner(cfg, fake_backend)
    await _ping(runner)
    [record] = runner.log.records
    assert record.reasoning == "x" * 10 and record.reasoning_chars == 25


async def test_reasoning_is_not_stored_unless_the_model_opts_in(fake_backend):
    """Owner's ruling: storing reasoning is opt-in per model; the <think> block is skipped
    either way."""
    fake_backend.script("ping", '<think>{maybe}</think>{"ok": true}')
    runner = _runner(build_config(), fake_backend)
    assert (await _ping(runner)).ok is True
    [record] = runner.log.records
    assert record.reasoning is None and record.reasoning_chars is None
    assert "reasoning" not in record.model_dump(mode="json")  # traces read as before
    assert record.response == '<think>{maybe}</think>{"ok": true}'  # as the model sent it


async def test_reasoning_is_not_stored_when_llm_io_is_not(fake_backend):
    fake_backend.script("ping", '<think>why</think>{"ok": true}')
    runner = _runner(_model_cfg(store_reasoning=True), fake_backend, store_io=False)
    await _ping(runner)
    [record] = runner.log.records
    assert record.reasoning is None and record.request is None


async def test_a_reply_without_reasoning_stores_none(fake_backend):
    runner = _runner(_model_cfg(store_reasoning=True), fake_backend)
    await _ping(runner)
    [record] = runner.log.records
    assert record.reasoning is None and "reasoning_chars" not in record.model_dump()


async def test_thinking_turned_off_through_request_extra_reaches_the_server():
    """Qwen3's switch, sent the way an operator configures it."""
    cfg = _model_cfg(
        store_reasoning=True, request_extra={"chat_template_kwargs": {"enable_thinking": False}}
    )
    with FakeOpenAIServer(models=("model-a",), reasoning="reasoning") as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        runner = _runner(cfg, backend)
        await _ping(runner)
        await backend.aclose()
        assert server.requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert runner.log.records[0].reasoning is None


async def test_the_gate_parses_a_think_reply_from_the_synthetic_model_first_time():
    """A real stage schema (GateVerdict) through the fake server's <think> mode."""
    cfg = build_config()
    with FakeOpenAIServer(models=("model-a",), reasoning="think") as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        model = cfg.models["model-a"]
        schema = GateVerdict.model_json_schema()
        payload = {
            "task": "gate",
            "value_statement": "Varna expanded.",
            "digests": [],
            "units": [{"ref": "s/u1", "text": "Varna expanded.", "locator": "p1", "source": "s"}],
        }
        messages = request_messages("Judge.", payload, model, schema)
        resp = await backend.chat(build_request("model-a", model, GateVerdict, schema, messages))
        await backend.aclose()
    assert resp.content.startswith("<think>")
    GateVerdict.model_validate_json(extract_json(resp.content))
