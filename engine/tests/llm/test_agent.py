import json

import pytest
from pydantic import BaseModel

from corelata.config import StructuredOutput
from corelata.llm.agent import (
    StructuredOutputError,
    _repair_message,
    build_request,
    extract_json,
    request_messages,
)
from corelata.llm.payload import render_input
from corelata.llm.types import PermanentBackendError, TransientBackendError


class Ping(BaseModel):
    ok: bool


PAYLOAD = {"task": "ping"}


async def _run(runner, **kw):
    args = dict(
        role="gate",
        model_key="model-a",
        prompt_id="ping",
        prompt_vars={"product": "Corelata"},
        payload=PAYLOAD,
        output_type=Ping,
    )
    args.update(kw)
    return await runner.run(**args)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('Sure!\n```json\n{"a": 1}\n```\nDone.', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Here you go: {"a": {"b": 2}} hope it helps', '{"a": {"b": 2}}'),
        ("no json at all", "no json at all"),
        ('{"t": "run:\\n```bash\\nls\\n```"}', '{"t": "run:\\n```bash\\nls\\n```"}'),
    ],
)
def test_extract_json(content, expected):
    assert extract_json(content) == expected


async def test_success_records_call(make_runner, fake_backend):
    runner = make_runner()
    out = await _run(runner)
    assert out.ok is True
    [rec] = runner.log.records
    assert (rec.role, rec.backend, rec.model, rec.prompt_id, rec.prompt_version) == (
        "gate",
        "fake",
        "model-a",
        "ping",
        1,
    )
    assert rec.ok and rec.attempt == 1 and rec.tokens_in == 10
    assert rec.request["messages"][1]["content"].startswith("INPUT_JSON:")
    assert "Corelata" in rec.request["messages"][0]["content"]
    assert fake_backend.requests[0].schema_name == "Ping"


async def test_store_io_false_omits_request_and_response(make_runner):
    runner = make_runner(store_io=False)
    await _run(runner)
    [rec] = runner.log.records
    assert rec.request is None and rec.response is None


async def test_json_object_mode_describes_schema_in_prompt(make_runner, make_config, fake_backend):
    cfg = make_config(
        models={
            "model-a": {"backend": "fake", "context_window": 32768, "structured_output": "none"},
            "model-b": {"backend": "fake", "context_window": 32768},
        }
    )
    await _run(make_runner(cfg))
    assert "JSON Schema" in fake_backend.requests[0].messages[0].content


async def test_invalid_output_is_repaired_once(make_runner, fake_backend):
    fake_backend.script("ping", "garbage")
    runner = make_runner()
    out = await _run(runner)
    assert out.ok is True
    assert len(runner.log.records) == 2
    assert runner.log.records[0].ok is False
    repair = fake_backend.requests[1].messages
    assert [m.role for m in repair] == ["system", "user", "assistant", "user"]
    assert repair[3].content.startswith("Your previous response was rejected.")


async def test_two_invalid_outputs_fail(make_runner, fake_backend):
    fake_backend.script("ping", "garbage", json.dumps({"ok": "not-a-bool"}))
    with pytest.raises(StructuredOutputError, match="gate: invalid output after repair"):
        await _run(make_runner())


async def test_semantic_validator_errors_trigger_repair(make_runner, fake_backend):
    fake_backend.script("ping", json.dumps({"ok": False}))
    runner = make_runner()
    out = await _run(runner, validate=lambda p: [] if p.ok else ["ok must be true"])
    assert out.ok is True
    assert "ok must be true" in fake_backend.requests[1].messages[3].content


async def test_transient_errors_are_retried(make_runner, fake_backend):
    fake_backend.script("ping", TransientBackendError("boom"))
    runner = make_runner()
    out = await _run(runner)
    assert out.ok is True
    assert [r.ok for r in runner.log.records] == [False, True]


async def test_permanent_errors_propagate(make_runner, fake_backend):
    fake_backend.script("ping", PermanentBackendError("nope"))
    with pytest.raises(PermanentBackendError):
        await _run(make_runner())


async def test_usage_totals_by_role(make_runner):
    runner = make_runner()
    await _run(runner)
    await _run(runner, role="writer")
    usage = runner.log.usage()
    assert usage.calls == 2 and usage.tokens_in == 20
    assert set(usage.by_role) == {"gate", "writer"}


def test_the_repair_message_is_an_instruction_with_every_point():
    assert _repair_message(["first", "second"]) == (
        "Your previous response was rejected. Fix every point below and return the complete "
        "corrected JSON object only:\n- first\n- second"
    )
    assert _repair_message([str(i) for i in range(25)]).count("\n- ") == 20


def test_a_long_enum_error_is_not_listed_in_full_in_a_repair_message():
    from typing import Literal

    from corelata.llm.agent import _parse

    class Pick(BaseModel):
        ref: Literal[tuple(f"src1/u{i}" for i in range(50))]
        small: Literal["a", "b"]

    _, errors = _parse('{"ref": "nope", "small": "z"}', Pick, None)
    assert errors == [
        "ref: use one of the values given in the input (such as 'src1/u0', 'src1/u1', 'src1/u2')",
        "small: Input should be 'a' or 'b'",
    ]


def test_a_long_str_enum_error_is_collapsed_like_a_literal():
    from enum import StrEnum

    from corelata.llm.agent import _parse

    Ref = StrEnum("Ref", [(f"v{i}", f"src1/u{i}") for i in range(50)])

    class Cite(BaseModel):
        refs: list[Ref]

    _, errors = _parse('{"refs": ["src1"]}', Cite, None)
    assert errors == [
        "refs.0: use one of the values given in the input (such as 'src1/u0', 'src1/u1', 'src1/u2')"
    ]


def test_request_messages_spell_out_the_schema_only_when_the_server_does_not_enforce_it(
    make_config,
):
    model = make_config().models["model-a"]  # json_schema by default
    schema = Ping.model_json_schema()
    enforced = request_messages("sys", PAYLOAD, model, schema)
    assert [(m.role, m.content) for m in enforced] == [
        ("system", "sys"),
        ("user", render_input(PAYLOAD)),
    ]
    loose = model.model_copy(update={"structured_output": StructuredOutput.JSON_OBJECT})
    assert request_messages("sys", PAYLOAD, loose, schema)[0].content == (
        "sys\n\nRespond with one JSON object that matches this JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


async def test_run_sends_the_request_build_request_makes(make_runner, fake_backend):
    runner = make_runner()
    await _run(runner)
    sent = fake_backend.requests[0]
    model = runner.cfg.models["model-a"]
    schema = Ping.model_json_schema()
    assert sent == build_request("model-a", model, Ping, schema, sent.messages)
    assert sent.messages == request_messages(sent.messages[0].content, PAYLOAD, model, schema)
    capped = build_request("model-a", model, Ping, schema, sent.messages, max_tokens=7)
    assert (capped.max_tokens, capped.schema_name, capped.json_schema) == (7, "Ping", schema)


async def test_run_sends_the_given_schema_and_parses_with_the_type(make_runner, fake_backend):
    stricter = {"title": "Ping", "type": "object", "properties": {"ok": {"enum": [True]}}}
    runner = make_runner()
    out = await _run(runner, schema=stricter)
    sent = fake_backend.requests[0]
    assert sent.json_schema == stricter and sent.schema_name == "Ping"
    assert type(out) is Ping  # parsed with output_type, not with the schema
    loose = runner.cfg.models["model-a"].model_copy(
        update={"structured_output": StructuredOutput.JSON_OBJECT}
    )
    assert json.dumps(stricter) in request_messages("s", PAYLOAD, loose, stricter)[0].content
