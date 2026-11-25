import asyncio
import json

import httpx
import pytest
import yaml
from sqlalchemy.engine import make_url

from corelata.cli import main
from corelata.config import StructuredOutput, load_config
from corelata.doctor import (
    AUDIT_PROBE_CLAIMS,
    AUDIT_PROBE_DRAFT,
    AUDIT_PROBE_QUOTES,
    AUDIT_PROBE_SYSTEM,
    AUDIT_PROBE_UNITS,
    ERROR_CHARS,
    PING_SCHEMA,
    PROBE_PAYLOAD,
    PROBE_SYSTEM,
    audit_probe_input,
    run_doctor,
)
from corelata.ingest import ocr
from corelata.llm.agent import AgentRunner, CallLog
from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.payload import parse_input, render_input
from corelata.llm.schema import strict_json_schema
from corelata.llm.types import (
    ChatMessage,
    ChatResponse,
    ContextOverflowError,
    OutputTruncatedError,
    PermanentBackendError,
    TransientBackendError,
)
from corelata.prompts.library import PromptLibrary
from corelata.quotes import quote_found
from corelata.schema import CheckStatus, GateVerdict
from corelata.stages.audit import auditor_payload
from corelata.stages.audit_schema import audit_output_type
from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, load_pack
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.testing.postgres import create_test_database, drop_test_database
from corelata.testing.synthetic import chat_completion, synthetic_response


def _config(tmp_path, server_url, **extra):
    cfg = {
        "backends": {"local": {"base_url": server_url, "max_concurrency": 2, "timeout_s": 5}},
        "models": {"fake-model": {"backend": "local", "context_window": 4096}},
        "roles": {r: {"model": "fake-model"} for r in ("gate", "writer", "conveyor", "auditor")},
        "storage": {"path": str(tmp_path / "files")},
        **extra,
    }
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _by_name(report):
    return {c.name: c for c in report.checks}


@pytest.fixture
def server():
    with FakeOpenAIServer() as srv:
        yield srv


async def test_a_healthy_installation(tmp_path, server, monkeypatch, pg_url):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    report = await run_doctor(_config(tmp_path, server.base_url))
    checks = _by_name(report)
    assert report.ok
    for name in (
        "config",
        "prompts",
        "pack",
        "pack names",
        "backend local",
        "model fake-model",
        "model fake-model auditor schema",
        "database",
        "storage",
    ):
        assert checks[name].status is CheckStatus.PASS, (name, checks[name])
    assert checks["backend local"].message == "serves 1 model; fake-model → fake-model found"
    assert "icd203-base" in checks["pack"].message
    assert checks["model fake-model"].message == (
        "test completion succeeded; json_schema output works (GateVerdict)"
    )
    assert checks["model fake-model auditor schema"].message == (
        "json_schema output works (AuditByRule, 17 rules)"
    )
    names = [c.name for c in report.checks]
    assert names.index("model fake-model auditor schema") == names.index("model fake-model") + 1
    assert "0010" in checks["database"].message
    assert f":{make_url(pg_url).password}@" not in checks["database"].message  # redacted


async def test_model_not_served(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(
        tmp_path,
        server.base_url,
        models={"big": {"backend": "local", "name": "other-model", "context_window": 4096}},
        roles={r: {"model": "big"} for r in ("gate", "writer", "conveyor", "auditor")},
    )
    report = await run_doctor(path)
    check = _by_name(report)["model big"]
    assert check.status is CheckStatus.FAIL and "not served" in check.message
    assert check.fix == "set models.big.name to a served id; see the server's model list"
    assert _by_name(report)["database"].status is CheckStatus.WARN
    assert "set CORELATA_DATABASE_URL" in _by_name(report)["database"].fix
    assert not report.ok


async def test_unreachable_backend(tmp_path):
    report = await run_doctor(_config(tmp_path, "http://127.0.0.1:9/v1"))
    check = _by_name(report)["backend local"]
    assert check.status is CheckStatus.FAIL and "fake-model" not in check.message
    assert "model fake-model" not in _by_name(report)


async def test_no_probe_skips_the_test_completions(tmp_path, server):
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.PASS and check.message == "served"
    assert "model fake-model auditor schema" not in _by_name(report)
    assert server.requests == []


async def test_failed_completion_is_reported(tmp_path, server):
    class Broken(FakeBackend):
        async def list_models(self):
            return ["fake-model"]

        async def chat(self, request):
            raise PermanentBackendError("quota")

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": Broken()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and "quota" in check.message
    assert "model fake-model auditor schema" not in _by_name(report)  # no probe after a failed ping


async def test_structured_output_not_honoured(tmp_path, server):
    class Prose(FakeBackend):
        async def list_models(self):
            return ["fake-model"]

        async def chat(self, request):
            from corelata.llm.types import ChatResponse

            return ChatResponse(content="Sure! Here you go.")

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": Prose()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and "did not return the requested JSON" in check.message
    assert check.fix == "set models.fake-model.structured_output to json_object or none"


async def test_database_states(tmp_path, server, monkeypatch, pg_admin):
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    db_check = _by_name(report)["database"]
    assert db_check.status is CheckStatus.FAIL and "secret" not in db_check.message
    url = create_test_database(pg_admin)
    try:
        monkeypatch.setenv("CORELATA_DATABASE_URL", url)
        report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
        assert _by_name(report)["database"].fix == "run corelata migrate"
    finally:
        drop_test_database(pg_admin, url)


async def test_a_backend_that_crashes_fails_only_its_check(tmp_path, server):
    class Crashing(FakeBackend):
        async def list_models(self):
            raise RuntimeError("kaput")

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": Crashing()}
    )
    checks = _by_name(report)
    assert checks["backend local"].status is CheckStatus.FAIL
    assert checks["backend local"].message == "internal error: RuntimeError: kaput"
    assert not report.ok
    assert "database" in checks and "storage" in checks


async def test_a_backend_that_fails_to_close_does_not_stop_the_others(tmp_path, server):
    class BadClose(FakeBackend):
        async def aclose(self):
            raise RuntimeError("cannot close")

    first, second = BadClose(), FakeBackend()
    report = await run_doctor(
        _config(tmp_path, server.base_url),
        probe=False,
        backends_factory=lambda cfg: {"a": first, "b": second},
    )
    assert second.closed
    assert "storage" in _by_name(report)


async def test_the_storage_check_runs_off_the_event_loop(tmp_path, server, monkeypatch):
    on_loop: list[bool] = []

    class Watched:
        def check_writable(self) -> None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                on_loop.append(False)  # a worker thread: what we want
            else:
                on_loop.append(True)

    monkeypatch.setattr("corelata.doctor.build_storage", lambda cfg: Watched())
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    assert _by_name(report)["storage"].status is CheckStatus.PASS
    assert on_loop == [False]


async def test_config_prompts_and_pack_checks_run_off_the_event_loop(tmp_path, server, monkeypatch):
    """CRL-113: each reads files a customer may keep on a slow or network-mounted disk."""
    import corelata.doctor as doctor

    on_loop: dict[str, bool] = {}

    def watched(name, fn):
        def run(*args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                on_loop[name] = False  # a worker thread: what we want
            else:
                on_loop[name] = True
            return fn(*args, **kwargs)

        return run

    for name in ("load_config", "_prompts", "_pack", "_pack_names"):
        monkeypatch.setattr(doctor, name, watched(name, getattr(doctor, name)))
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    assert _by_name(report)["pack"].status is CheckStatus.PASS
    assert on_loop == {
        "load_config": False,
        "_prompts": False,
        "_pack": False,
        "_pack_names": False,
    }


async def test_storage_not_writable(tmp_path, server):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    path = _config(tmp_path, server.base_url, storage={"path": str(blocker / "sub")})
    report = await run_doctor(path, probe=False)
    assert _by_name(report)["storage"].status is CheckStatus.FAIL


async def test_pack_problems_are_reported(tmp_path, server):
    path = _config(tmp_path, server.base_url, standards={"default_profile": "nope"})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack"]
    assert check.status is CheckStatus.FAIL and "profile 'nope' not found" in check.message


async def test_invalid_config_stops_early(tmp_path):
    path = tmp_path / "corelata.yaml"
    path.write_text("backends: {}\nmodels: {}\n", encoding="utf-8")
    report = await run_doctor(path)
    assert [c.name for c in report.checks] == ["config"]
    assert report.checks[0].status is CheckStatus.FAIL and not report.ok


async def test_config_warnings_are_reported(tmp_path, server, monkeypatch):
    from corelata import doctor
    from corelata.config import ConfigIssue, load_config

    def with_warning(path):
        cfg, _ = load_config(path)
        return cfg, [ConfigIssue(level="warning", message="something to look at")]

    monkeypatch.setattr(doctor, "load_config", with_warning)
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    warn = [c for c in report.checks if c.name == "config" and c.status is CheckStatus.WARN]
    assert warn and warn[0].message == "something to look at" and report.ok


def test_cli_text_and_json(tmp_path, server, capsys, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url)
    assert main(["doctor", "--config", str(path), "--no-probe"]) == 0
    out = capsys.readouterr().out
    assert "PASS  backend local" in out and "WARN  database" in out
    assert "fix: set CORELATA_DATABASE_URL" in out
    assert main(["doctor", "--config", str(path), "--json", "--no-probe"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["checks"][0]["name"] == "config"
    bad = _config(tmp_path, "http://127.0.0.1:9/v1")
    assert main(["doctor", "--config", str(bad), "--no-probe"]) == 1


async def test_an_unexpected_error_fails_one_check_and_the_rest_still_run(
    tmp_path, server, monkeypatch
):
    def boom(*_a, **_k):
        raise RuntimeError("kaput")

    monkeypatch.setattr("corelata.doctor.load_run_pack", boom)
    monkeypatch.setattr("corelata.doctor.migration_state", boom)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:p@127.0.0.1:9/x")
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    checks = _by_name(report)
    assert checks["pack"].status is CheckStatus.FAIL
    assert checks["pack"].message == "internal error: RuntimeError: kaput"
    assert checks["database"].status is CheckStatus.FAIL and "kaput" in checks["database"].message
    assert checks["model fake-model"].status is CheckStatus.PASS
    assert checks["storage"].status is CheckStatus.PASS and not report.ok


async def test_coglossa_not_configured_is_a_pass(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.PASS and "not configured" in check.message


async def test_coglossa_reachable_and_unreachable(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(
        tmp_path, server.base_url, integrations={"coglossa": {"base_url": "http://coglossa.test"}}
    )
    ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok", "version": "1"}))
    report = await run_doctor(path, probe=True, coglossa_transport=ok)
    assert _by_name(report)["coglossa"].status is CheckStatus.PASS

    def down(request):
        raise httpx.ConnectError("refused")

    report = await run_doctor(path, probe=True, coglossa_transport=httpx.MockTransport(down))
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.FAIL and "cannot reach" in check.message
    report = await run_doctor(path, probe=False, coglossa_transport=httpx.MockTransport(down))
    assert _by_name(report)["coglossa"].status is CheckStatus.PASS  # no probe: configured only


async def test_coglossa_missing_key_variable_fails(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    monkeypatch.delenv("COGLOSSA_KEY", raising=False)
    path = _config(
        tmp_path,
        server.base_url,
        integrations={
            "coglossa": {"base_url": "http://coglossa.test", "api_key_env": "COGLOSSA_KEY"}
        },
    )
    report = await run_doctor(path, probe=False)
    # load_config rejects an unset key variable, so doctor reports it as the config failure.
    assert report.checks[0].name == "config" and report.checks[0].status is CheckStatus.FAIL
    assert "COGLOSSA_KEY" in report.checks[0].message


def _coglossa_config(tmp_path, server):
    return _config(
        tmp_path,
        server.base_url,
        integrations={
            "coglossa": {"base_url": "http://coglossa.test", "api_key_env": "COGLOSSA_KEY"}
        },
    )


async def test_coglossa_probe_sends_the_key_to_the_health_path(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    monkeypatch.setenv("COGLOSSA_KEY", "s3cret")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    path = _coglossa_config(tmp_path, server)
    report = await run_doctor(path, probe=True, coglossa_transport=httpx.MockTransport(handler))
    assert _by_name(report)["coglossa"].status is CheckStatus.PASS
    assert [r.url.path for r in seen] == ["/api/health"]
    assert seen[0].headers["Authorization"] == "Bearer s3cret"


async def test_coglossa_rejected_key_fails(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    monkeypatch.setenv("COGLOSSA_KEY", "wrong")
    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    report = await run_doctor(
        _coglossa_config(tmp_path, server), probe=True, coglossa_transport=transport
    )
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.FAIL and "rejected the key" in check.message
    assert "COGLOSSA_KEY" in check.message


async def test_coglossa_empty_key_variable_fails_without_a_request(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    monkeypatch.setenv("COGLOSSA_KEY", "")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200)

    report = await run_doctor(
        _coglossa_config(tmp_path, server),
        probe=True,
        coglossa_transport=httpx.MockTransport(handler),
    )
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.FAIL and "COGLOSSA_KEY is empty" in check.message
    assert calls == []


async def test_unaddressable_pack_directories_are_a_warning(tmp_path, server):
    packs = tmp_path / "packs"
    for name in ("Customer_A", "team-east", "2nd.draft"):
        (packs / name).mkdir(parents=True)
        (packs / name / "pack.yaml").write_text(
            yaml.safe_dump({"name": "team-east", "version": "1.0", "extends": "icd203-base"}),
            encoding="utf-8",
        )
    path = _config(tmp_path, server.base_url, standards={"packs_dir": str(packs)})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack names"]
    assert check.status is CheckStatus.WARN
    assert "2nd.draft, Customer_A" in check.message and "team-east" not in check.message
    assert "lowercase letters, digits and hyphens" in check.fix
    assert report.ok  # a warning does not fail the installation


async def test_over_long_pack_names_are_a_warning_with_the_shared_rules(tmp_path, server):
    assert PACK_NAME_MAX_LENGTH == 100  # the API route's max_length
    packs = tmp_path / "packs"
    too_long = "a" * (PACK_NAME_MAX_LENGTH + 1)
    for name in (too_long, "b" * PACK_NAME_MAX_LENGTH):
        (packs / name).mkdir(parents=True)
        (packs / name / "pack.yaml").write_text(
            yaml.safe_dump({"name": "x", "version": "1.0", "extends": "icd203-base"}),
            encoding="utf-8",
        )
    path = _config(tmp_path, server.base_url, standards={"packs_dir": str(packs)})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack names"]
    assert check.status is CheckStatus.WARN
    assert check.message == f"1 pack directory cannot be addressed through the API: {too_long}"
    assert PACK_NAME_PATTERN.pattern in check.fix
    assert f"at most {PACK_NAME_MAX_LENGTH} characters" in check.fix
    assert report.ok


ROLES = ("gate", "writer", "conveyor", "auditor")


def _one_model(tmp_path, server, name, **model):
    return _config(
        tmp_path,
        server.base_url,
        models={"m": {"backend": "local", "name": name, "context_window": 4096, **model}},
        roles={r: {"model": "m"} for r in ROLES},
    )


async def test_the_backend_check_counts_the_served_models_and_names_only_the_configured(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = [f"vendor{i}/model-{i}" for i in range(466)]
    served += ["openai/gpt-4.1-mini", "google/gemini-2.5-flash"]
    path = _config(
        tmp_path,
        server.base_url,
        models={
            "writer-model": {
                "backend": "local",
                "name": "openai/gpt-4.1-mini",
                "context_window": 4096,
            },
            "auditor-model": {
                "backend": "local",
                "name": "google/gemini-2.5-flash",
                "context_window": 4096,
            },
        },
        roles={
            "gate": {"model": "writer-model"},
            "writer": {"model": "writer-model"},
            "conveyor": {"model": "auditor-model"},
            "auditor": {"model": "auditor-model"},
        },
    )
    report = await run_doctor(
        path, probe=False, backends_factory=lambda cfg: {"local": FakeBackend(models=tuple(served))}
    )
    check = _by_name(report)["backend local"]
    assert check.status is CheckStatus.PASS
    assert check.message == (
        "serves 468 models; auditor-model → google/gemini-2.5-flash found; "
        "writer-model → openai/gpt-4.1-mini found"  # config order (the test's YAML sorts keys)
    )
    assert "vendor" not in check.message  # the served list is never printed


async def test_a_missing_model_suggests_at_most_five_served_ids_with_its_prefix(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = (
        "openai/o3",
        "openai/gpt-4.1-mini",
        "openai/gpt-4o",
        "openai/gpt-5",
        "openai/gpt-4.1",
        "openai/o4-mini",
        "google/gemini-2.5-flash",
        "phi4-mini:3.8b",
    )

    async def fix_for(name):
        report = await run_doctor(
            _one_model(tmp_path, server, name),
            probe=False,
            backends_factory=lambda cfg: {"local": FakeBackend(models=served)},
        )
        assert _by_name(report)["backend local"].message == f"serves 8 models; m → {name} missing"
        check = _by_name(report)["model m"]
        assert check.status is CheckStatus.FAIL
        assert check.message == f"'{name}' is not served by backend local"
        return check.fix

    assert await fix_for("openai/gpt-4.1-mni") == (
        "set models.m.name to a served id, such as: openai/gpt-4.1, openai/gpt-4.1-mini, "
        "openai/gpt-4o, openai/gpt-5, openai/o3"
    )
    assert await fix_for("phi4-mini") == "set models.m.name to a served id, such as: phi4-mini:3.8b"
    assert await fix_for("mistral-small") == (
        "set models.m.name to a served id; see the server's model list"
    )


async def test_the_suggestions_ignore_case_and_keep_their_order(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = ("Qwen/Qwen3-32B-Instruct", "qwen/qwen3-8b", "QWEN/qwq-32b", "openai/gpt-4o")

    async def fix_for(name):
        report = await run_doctor(
            _one_model(tmp_path, server, name),
            probe=False,
            backends_factory=lambda cfg: {"local": FakeBackend(models=served)},
        )
        return _by_name(report)["model m"].fix

    expected = (
        "set models.m.name to a served id, such as: QWEN/qwq-32b, Qwen/Qwen3-32B-Instruct, "
        "qwen/qwen3-8b"  # sorted as before (R-M12-2): by code point, so capitals first
    )
    assert await fix_for("qwen/qwen3-32b") == expected
    assert await fix_for("QWEN/Qwen3-32b") == expected
    assert await fix_for("OpenAI/gpt-4.1") == (
        "set models.m.name to a served id, such as: openai/gpt-4o"
    )


async def test_a_base_url_with_a_query_fails_the_config_check(tmp_path, server):
    path = _config(tmp_path, server.base_url + "?key=abc")
    report = await run_doctor(path)
    [check] = report.checks
    assert check.name == "config" and check.status is CheckStatus.FAIL and not report.ok
    assert "backends.local.base_url: Value error, must not contain a query string" in check.message
    assert "give a key with api_key_env" in check.message


async def test_the_structured_probe_sends_the_gate_verdict_schema_a_run_sends(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url))
    assert _by_name(report)["model fake-model"].status is CheckStatus.PASS
    probe = server.requests[1]  # the ping, the gate probe, then the auditor probe
    response_format = probe["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "GateVerdict"
    assert response_format["json_schema"]["schema"] == strict_json_schema(
        GateVerdict.model_json_schema()
    )
    assert "max_tokens" not in probe  # the model sets none, as in a run
    assert [m["content"] for m in probe["messages"]] == [PROBE_SYSTEM, render_input(PROBE_PAYLOAD)]
    assert len(PROBE_SYSTEM.splitlines()) == 2


def _is_strict(node) -> bool:
    """OpenAI's strict subset: every object lists every property as required and forbids extra
    properties, and no node carries a default."""
    if isinstance(node, list):
        return all(_is_strict(n) for n in node)
    if not isinstance(node, dict):
        return True
    if "default" in node:
        return False
    props = node.get("properties")
    if isinstance(props, dict) and (
        node.get("additionalProperties") is not False
        or node.get("required") != list(props)
        or not all(_is_strict(p) for p in props.values())
    ):
        return False
    return all(_is_strict(v) for k, v in node.items() if k != "properties")


def _strict_openai(request: httpx.Request) -> httpx.Response:
    """A server that validates `json_schema` response formats as OpenAI does (CRL-27)."""
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"object": "list", "data": [{"id": "fake-model"}]})
    body = json.loads(request.content)
    response_format = body.get("response_format") or {}
    if response_format.get("type") == "json_schema":
        spec = response_format["json_schema"]
        if not _is_strict(spec["schema"]):
            message = (
                f"Invalid schema for response_format '{spec['name']}': In context=(), "
                "'required' is required to be supplied and to be an array including every key "
                "in properties. " + "Missing a key. " * 30
            )
            error = {"error": {"code": "invalid_json_schema", "message": message}}
            return httpx.Response(400, json=error)
    content = json.dumps(synthetic_response(parse_input(body["messages"])))
    return httpx.Response(200, json=chat_completion(content))


def _strict_backend() -> OpenAICompatBackend:
    return OpenAICompatBackend(
        "local", "http://strict.test/v1", transport=httpx.MockTransport(_strict_openai)
    )


async def test_against_a_strict_server_the_probe_passes_exactly_when_a_gate_call_does(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url)
    cfg, _ = load_config(path)

    async def gate_call() -> GateVerdict:
        backend = _strict_backend()
        runner = AgentRunner(cfg, {"local": backend}, PromptLibrary(), CallLog())
        try:
            return await runner.run(
                role="gate",
                model_key="fake-model",
                prompt_id="gate",
                prompt_vars={"mode": "verify", "tone": ""},
                payload=PROBE_PAYLOAD,
                output_type=GateVerdict,
            )
        finally:
            await backend.aclose()

    def doctor():
        return run_doctor(path, backends_factory=lambda c: {"local": _strict_backend()})

    assert isinstance(await gate_call(), GateVerdict)
    checks = _by_name(await doctor())
    check = checks["model fake-model"]
    assert check.status is CheckStatus.PASS, check
    assert checks["model fake-model auditor schema"].status is CheckStatus.PASS  # strict as well

    # CRL-27: when the stages sent a schema the server rejects, the ping probe still passed
    # (its schema has no optional field); the GateVerdict probe fails together with the run.
    monkeypatch.setattr("corelata.llm.openai_compat.strict_json_schema", lambda schema: schema)
    assert _is_strict(PING_SCHEMA)
    with pytest.raises(PermanentBackendError, match="invalid_json_schema"):
        await gate_call()
    checks = _by_name(await doctor())
    assert checks["model fake-model auditor schema"].status is CheckStatus.FAIL
    check = checks["model fake-model"]
    assert check.status is CheckStatus.FAIL
    head = "test completion succeeded; json_schema request failed: "
    assert check.message.startswith(head + "local: HTTP 400: ")
    assert "invalid_json_schema" in check.message and check.message.endswith("…")
    assert len(check.message) == len(head) + ERROR_CHARS  # the server's text, cut to 200
    assert check.fix == "set models.fake-model.structured_output to json_object or none"


async def test_json_that_is_not_a_gate_verdict_fails_the_probe(tmp_path, server):
    class OkOnly(FakeBackend):
        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(content='{"ok": true}')

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": OkOnly()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message.endswith(
        "the server did not return the requested JSON (json_schema), even after one repair "
        "turn: not a GateVerdict: supported: Field required"
    )
    assert check.fix == "set models.fake-model.structured_output to json_object or none"
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == (
        "the server did not return the requested JSON (json_schema), even after one repair "
        "turn: not an AuditByRule: findings: Field required"
    )
    assert audit.fix == "set models.fake-model.structured_output to json_object or none"


async def test_a_probe_cut_at_max_tokens_says_to_raise_the_limit(tmp_path, server):
    path = _config(
        tmp_path,
        server.base_url,
        models={"fake-model": {"backend": "local", "context_window": 4096, "max_output_tokens": 1}},
    )
    checks = _by_name(await run_doctor(path))  # the fake cuts max_tokens=1
    check = checks["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message == (
        "test completion succeeded; the GateVerdict reply was cut at max_tokens=1"
    )
    assert check.fix == (
        "raise models.fake-model.max_output_tokens or unset it: a GateVerdict needs about 150 "
        "tokens plus any reasoning the model emits first"
    )
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "the AuditByRule reply was cut at max_tokens=1"
    assert audit.fix == (
        "raise models.fake-model.max_output_tokens or unset it: an AuditByRule needs about 60 "
        "tokens per rule (17 here) plus any reasoning the model emits first"
    )


async def test_the_probe_sends_no_cap_when_the_model_has_none(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = FakeBackend()
    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": backend}
    )
    assert _by_name(report)["model fake-model"].status is CheckStatus.PASS
    ping, gate, audit = backend.requests
    assert gate.schema_name == "GateVerdict" and gate.max_tokens is None
    assert audit.schema_name == "AuditByRule" and audit.max_tokens is None


async def test_a_json_object_model_that_returns_the_wrong_json_is_told_to_use_none(tmp_path):
    class OkOnly(FakeBackend):
        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(content='{"ok": true}')

    path = _config(
        tmp_path,
        "http://unused.test/v1",
        models={
            "fake-model": {
                "backend": "local",
                "context_window": 4096,
                "structured_output": "json_object",
            }
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": OkOnly()})
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.fix == (
        "set models.fake-model.structured_output to none, or pick a model that follows a "
        "JSON schema"
    )


async def test_a_model_served_as_latest_counts_as_found(tmp_path, server):
    path = _config(
        tmp_path,
        server.base_url,
        models={"m": {"backend": "local", "name": "phi4-mini", "context_window": 4096}},
        roles={r: {"model": "m"} for r in ("gate", "writer", "conveyor", "auditor")},
    )
    served = FakeBackend(models=("phi4-mini:latest",))
    report = await run_doctor(path, probe=False, backends_factory=lambda cfg: {"local": served})
    checks = _by_name(report)
    assert checks["backend local"].message == "serves 1 model; m → phi4-mini found"
    assert checks["model m"].status is CheckStatus.PASS and checks["model m"].message == "served"


def _most_properties(node) -> int:
    """The largest `properties` object anywhere in a JSON schema."""
    if isinstance(node, list):
        return max((_most_properties(n) for n in node), default=0)
    if not isinstance(node, dict):
        return 0
    own = len(node["properties"]) if isinstance(node.get("properties"), dict) else 0
    return max([own, *(_most_properties(v) for v in node.values())])


class SchemaSizeLimit(FakeBackend):
    """A server that rejects a `json_schema` request whose largest object has more than `limit`
    properties, as some servers limit schema size (CRL-31)."""

    limit = 10

    async def chat(self, request):
        if request.structured_output is StructuredOutput.JSON_SCHEMA:
            size = _most_properties(request.json_schema)
            if size > self.limit:
                self.requests.append(request)
                raise PermanentBackendError(
                    f"local: HTTP 400: response_format schema has an object with {size} "
                    f"properties; at most {self.limit} are supported"
                )
        return await super().chat(request)


async def test_a_schema_size_limit_fails_the_auditor_probe_and_not_the_gate_probe(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    assert len(GateVerdict.model_json_schema()["properties"]) <= SchemaSizeLimit.limit
    path = _config(tmp_path, server.base_url)
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": SchemaSizeLimit()})
    checks = _by_name(report)
    gate = checks["model fake-model"]
    assert gate.status is CheckStatus.PASS
    assert gate.message == "test completion succeeded; json_schema output works (GateVerdict)"
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL and not report.ok
    assert audit.message == (
        "json_schema request failed: local: HTTP 400: response_format schema has an object "
        "with 17 properties; at most 10 are supported"
    )
    assert audit.fix == "set models.fake-model.structured_output to json_object or none"
    path = _config(  # the fix works: json_object sends no schema for the server to reject
        tmp_path,
        server.base_url,
        models={
            "fake-model": {
                "backend": "local",
                "context_window": 4096,
                "structured_output": "json_object",
            }
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": SchemaSizeLimit()})
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.PASS
    assert audit.message == "json_object output works (AuditByRule, 17 rules)"


async def test_long_listing_and_ping_errors_are_cut_to_error_chars(tmp_path, server):
    long = "upstream says: " + "y" * 5000

    class Unlisted(FakeBackend):
        async def list_models(self):
            raise TransientBackendError(long)

    class Unanswering(FakeBackend):
        async def chat(self, request):
            raise PermanentBackendError(long)

    path = _config(tmp_path, server.base_url)
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": Unlisted()})
    check = _by_name(report)["backend local"]
    assert check.message == "unreachable: " + long[: ERROR_CHARS - 1] + "…"
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": Unanswering()})
    check = _by_name(report)["model fake-model"]
    assert check.message == "test completion failed: " + long[: ERROR_CHARS - 1] + "…"
    assert check.fix == "check the model id and server logs"


async def test_the_auditor_probe_sends_the_by_rule_schema_a_run_sends(
    tmp_path, server, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url))
    assert _by_name(report)["model fake-model auditor schema"].status is CheckStatus.PASS
    ping, gate, audit = server.requests
    assert gate["response_format"]["json_schema"]["name"] == "GateVerdict"
    pack = load_pack("icd203-base")
    refs = [u["ref"] for u in AUDIT_PROBE_UNITS]
    want = audit_output_type(pack, refs, AUDIT_PROBE_CLAIMS).model_json_schema()
    response_format = audit["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "AuditByRule"
    assert response_format["json_schema"]["schema"] == strict_json_schema(want)
    assert len(want["$defs"]["AuditFindings"]["required"]) == 17  # one property per rule
    assert "max_tokens" not in audit  # the model sets none, as in a run
    payload = auditor_payload(
        pack, AUDIT_PROBE_DRAFT, AUDIT_PROBE_UNITS, PROBE_PAYLOAD["value_statement"]
    )
    assert [m["content"] for m in audit["messages"]] == [AUDIT_PROBE_SYSTEM, render_input(payload)]
    assert len(AUDIT_PROBE_SYSTEM.splitlines()) == 2
    cited = sorted({r for c in AUDIT_PROBE_DRAFT.claims for r in c.evidence})
    assert cited == refs and [c.id for c in AUDIT_PROBE_DRAFT.claims] == AUDIT_PROBE_CLAIMS


async def test_with_evidence_quotes_the_auditor_probe_sends_quotes_a_run_sends(
    tmp_path, server, monkeypatch
):
    """CRL-93: the probe's draft quotes its units and each cited unit carries its quotes, the
    shape `stages.audit.cited_unit_payload` gives a run; the synthetic model still passes."""
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url, pipeline={"evidence_quotes": "required"})
    report = await run_doctor(path)
    assert _by_name(report)["model fake-model auditor schema"].status is CheckStatus.PASS
    audit = server.requests[-1]
    draft, units = audit_probe_input(True)
    assert all(len(c.quotes) == 1 for c in draft.claims)
    assert [u["quotes"] for u in units] == [
        [{"claim_id": "c1", "text": AUDIT_PROBE_QUOTES["c1"]["text"]}],
        [{"claim_id": "c2", "text": AUDIT_PROBE_QUOTES["c2"]["text"]}],
    ]
    for c in draft.claims:  # the probe's quotes are faithful: the engine would pass them
        unit = next(u for u in units if u["ref"] == c.evidence[0])
        assert quote_found(c.quotes[0].text, unit["text"])
    payload = auditor_payload(
        load_pack("icd203-base"), draft, units, PROBE_PAYLOAD["value_statement"]
    )
    assert audit["messages"][1]["content"] == render_input(payload)
    assert audit_probe_input(False) == (AUDIT_PROBE_DRAFT, AUDIT_PROBE_UNITS)


async def test_only_the_auditors_model_gets_the_auditor_probe(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(
        tmp_path,
        server.base_url,
        models={
            "a": {"backend": "local", "context_window": 4096},
            "b": {"backend": "local", "context_window": 4096},
        },
        roles={
            "gate": {"model": "a"},
            "writer": {"model": "a"},
            "conveyor": {"model": "a"},
            "auditor": {"model": "b"},
        },
    )
    backend = FakeBackend(models=("a", "b"))
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": backend})
    names = [c.name for c in report.checks if c.name.startswith("model ")]
    assert names == ["model a", "model b", "model b auditor schema"]
    assert [r.schema_name for r in backend.requests if r.model == "b"] == [
        "Ping",
        "GateVerdict",
        "AuditByRule",
    ]


async def test_a_none_model_gets_the_auditor_probe_with_the_schema_in_the_prompt(tmp_path):
    backend = FakeBackend()
    path = _config(
        tmp_path,
        "http://unused.test/v1",
        models={
            "fake-model": {"backend": "local", "context_window": 4096, "structured_output": "none"}
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": backend})
    checks = _by_name(report)
    assert checks["model fake-model"].message == "test completion succeeded"  # no gate probe
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.PASS
    assert audit.message == "none output works (AuditByRule, 17 rules)"
    ping, probe = backend.requests
    assert probe.schema_name == "AuditByRule" and probe.structured_output is StructuredOutput.NONE
    assert "matches this JSON Schema" in probe.messages[0].content
    assert '"AuditFindings"' in probe.messages[0].content


async def test_a_none_model_that_returns_the_wrong_json_is_told_to_pick_another(tmp_path):
    class OkOnly(FakeBackend):
        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(content='{"ok": true}')

    path = _config(
        tmp_path,
        "http://unused.test/v1",
        models={
            "fake-model": {"backend": "local", "context_window": 4096, "structured_output": "none"}
        },
    )
    report = await run_doctor(path, backends_factory=lambda cfg: {"local": OkOnly()})
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == (
        "the server did not return the requested JSON (none), even after one repair turn: "
        "not an AuditByRule: findings: Field required"
    )
    assert audit.fix == "pick a model that follows a JSON schema given in the prompt"


async def test_a_pack_that_does_not_load_fails_the_auditor_probe(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url, standards={"default_profile": "nope"})
    report = await run_doctor(path)
    audit = _by_name(report)["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message.startswith("cannot build the AuditByRule schema: ")
    assert "profile 'nope' not found" in audit.message
    assert audit.fix == "fix the pack check first"
    assert _by_name(report)["model fake-model"].status is CheckStatus.PASS


def _failing_auditor_probe(error):
    class Failing(FakeBackend):
        async def chat(self, request):
            if request.schema_name == "AuditByRule":
                self.requests.append(request)
                raise error
            return await super().chat(request)

    return Failing()


async def _auditor_checks(tmp_path, error, **model):
    cfg = {"backend": "local", "context_window": 4096, **model}
    path = _config(tmp_path, "http://unused.test/v1", models={"fake-model": cfg})
    backend = _failing_auditor_probe(error)
    return _by_name(await run_doctor(path, backends_factory=lambda c: {"local": backend}))


async def test_a_timeout_on_the_auditor_probe_points_at_the_server_and_the_timeout(tmp_path):
    checks = await _auditor_checks(tmp_path, TransientBackendError("local: timed out"))
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "json_schema request failed: local: timed out"
    assert audit.fix == "check the server logs; on a timeout raise backends.local.timeout_s"
    assert checks["model fake-model"].status is CheckStatus.PASS  # the gate line is unaffected


async def test_a_context_overflow_on_the_auditor_probe_points_at_the_context(tmp_path):
    checks = await _auditor_checks(tmp_path, ContextOverflowError("local: context too long"))
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "json_schema request failed: local: context too long"
    assert audit.fix == (
        "the request exceeds the model's context: raise the server's context length, "
        "or set models.fake-model.context_window to the server's real length; json_schema "
        "sends the schema out of band, json_object and none spell it into the prompt"
    )
    assert len(audit.fix) < 260
    assert checks["model fake-model"].status is CheckStatus.PASS


async def test_a_rejection_on_a_json_object_model_does_not_tell_it_to_set_json_object(tmp_path):
    checks = await _auditor_checks(
        tmp_path, PermanentBackendError("local: HTTP 400: no"), structured_output="json_object"
    )
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "json_object request failed: local: HTTP 400: no"
    assert audit.fix == "check the model id and server logs"


async def test_a_reply_cut_by_the_servers_default_limit_does_not_blame_a_cap(tmp_path):
    checks = await _auditor_checks(tmp_path, OutputTruncatedError("local: length"))
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.FAIL
    assert audit.message == "the AuditByRule reply was cut by the server's default output limit"
    assert audit.fix == (
        "set models.fake-model.max_output_tokens above the server's default: an AuditByRule "
        "needs about 60 tokens per rule (17 here) plus any reasoning the model emits first"
    )


# ---------------------------------------------------------------- the repair turn (R-M15-5)


class RepairOnce(FakeBackend):
    """A model whose first structured reply is `first` and whose repaired reply is `repaired`
    (the synthetic answer by default); the test completion is answered as usual."""

    def __init__(self, first: str = '{"ok": true}', repaired: str | BaseException | None = None):
        super().__init__()
        self.first, self.repaired = first, repaired

    async def chat(self, request):
        if request.schema_name == "Ping":
            return await super().chat(request)
        self.requests.append(request)
        if not any(m.role == "assistant" for m in request.messages):
            return ChatResponse(content=self.first)
        if isinstance(self.repaired, BaseException):
            raise self.repaired
        if self.repaired is not None:
            return ChatResponse(content=self.repaired)
        payload = parse_input([m.model_dump() for m in request.messages])
        return ChatResponse(content=json.dumps(synthetic_response(payload)))


def _json_object_config(tmp_path):
    model = {"backend": "local", "context_window": 4096, "structured_output": "json_object"}
    return _config(tmp_path, "http://unused.test/v1", models={"fake-model": model})


async def test_a_model_that_needs_one_repair_turn_warns_and_doctor_still_passes(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce()
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    checks = _by_name(report)
    check = checks["model fake-model"]
    assert check.status is CheckStatus.WARN and report.ok  # WARN never fails doctor
    assert check.message == (
        "test completion succeeded; json_object output works after one repair turn (GateVerdict)"
    )
    assert check.fix == (
        "nothing to change for a run, which repairs the reply the same way; every structured "
        "call on models.fake-model may cost a second request"
    )
    audit = checks["model fake-model auditor schema"]
    assert audit.status is CheckStatus.WARN
    assert audit.message == "json_object output works after one repair turn (AuditByRule, 17 rules)"
    sent = [r.schema_name for r in backend.requests]
    assert sent == ["Ping", "GateVerdict", "GateVerdict", "AuditByRule", "AuditByRule"]


async def test_the_probes_repair_turn_is_the_one_a_run_sends(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _json_object_config(tmp_path)
    cfg, _ = load_config(path)
    run_backend = RepairOnce()
    runner = AgentRunner(cfg, {"local": run_backend}, PromptLibrary(), CallLog())
    await runner.run(
        role="gate",
        model_key="fake-model",
        prompt_id="gate",
        prompt_vars={"mode": "verify", "tone": ""},
        payload=PROBE_PAYLOAD,
        output_type=GateVerdict,
    )
    probe_backend = RepairOnce()
    await run_doctor(path, backends_factory=lambda c: {"local": probe_backend})
    run_first, run_repair = run_backend.requests
    probe_first, probe_repair = [
        r for r in probe_backend.requests if r.schema_name == "GateVerdict"
    ]
    # the run's prompt is the gate template, the probe's its own; the repair turn is the same
    assert run_repair.messages[2:] == probe_repair.messages[2:]
    assert probe_repair.messages[:2] == probe_first.messages
    assert probe_repair.messages[2] == ChatMessage(role="assistant", content='{"ok": true}')
    assert probe_repair.messages[3].content.startswith("Your previous response was rejected.")
    assert probe_repair.model_copy(update={"messages": []}) == probe_first.model_copy(
        update={"messages": []}
    )  # the same schema, mode and limits: only the turn differs


async def test_a_repaired_reply_that_is_still_wrong_fails_and_cites_its_own_error(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce(repaired='{"supported": true}')
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and not report.ok
    assert check.message.endswith(
        "the server did not return the requested JSON (json_object), even after one repair "
        "turn: not a GateVerdict: substance: Field required"  # the repaired reply's first error
    )
    assert check.fix == (
        "set models.fake-model.structured_output to none, or pick a model that follows a "
        "JSON schema"
    )


async def test_a_backend_error_on_the_repair_turn_fails_with_its_cause(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce(repaired=TransientBackendError("local: timed out"))
    report = await run_doctor(
        _json_object_config(tmp_path), backends_factory=lambda cfg: {"local": backend}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message == (
        "test completion succeeded; json_object request failed on the repair turn: local: timed out"
    )
    assert check.fix == "check the server logs; on a timeout raise backends.local.timeout_s"
    assert [r.schema_name for r in backend.requests].count("GateVerdict") == 2  # no third try


def _json_schema_config(tmp_path):
    model = {"backend": "local", "context_window": 4096, "structured_output": "json_schema"}
    return _config(tmp_path, "http://unused.test/v1", models={"fake-model": model})


# json_schema is the mode where this matters: its first-turn fix for a rejected request is
# "set structured_output to json_object or none", which would blame a schema the server has
# just accepted. json_object's first-turn fix is already the generic one.
@pytest.mark.parametrize(
    ("config", "mode"),
    [(_json_schema_config, "json_schema"), (_json_object_config, "json_object")],
)
async def test_a_permanent_error_on_the_repair_turn_says_which_turn_and_does_not_blame_the_schema(
    tmp_path, monkeypatch, config, mode
):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    backend = RepairOnce(repaired=PermanentBackendError("local: HTTP 400: bad history"))
    report = await run_doctor(config(tmp_path), backends_factory=lambda cfg: {"local": backend})
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL
    assert check.message == (
        f"test completion succeeded; {mode} request failed on the repair turn: "
        "local: HTTP 400: bad history"
    )
    assert check.fix == "check the model id and server logs"


async def test_the_fake_server_can_play_a_model_that_needs_a_repair_turn(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    with FakeOpenAIServer(needs_repair=True) as srv:
        report = await run_doctor(_config(tmp_path, srv.base_url))
        checks = _by_name(report)
        assert report.ok
        assert checks["model fake-model"].message == (
            "test completion succeeded; json_schema output works after one repair turn "
            "(GateVerdict)"
        )
        assert checks["model fake-model auditor schema"].status is CheckStatus.WARN
        firsts = [r for r in srv.requests if len(r["messages"]) == 2]
        repairs = [r for r in srv.requests if len(r["messages"]) == 4]
        assert len(firsts) == 3 and len(repairs) == 2  # the ping needs no repair


# M19: the hosted demo's storage (spec §12.1)


@pytest.fixture
def s3_env(monkeypatch, hermetic_aws):
    import boto3
    from moto import mock_aws

    monkeypatch.setenv("CORELATA_S3_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("CORELATA_S3_SECRET_ACCESS_KEY", "test-secret")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="corelata-files")
        yield


async def test_s3_storage_writable(tmp_path, server, s3_env):
    storage = {"kind": "s3", "bucket": "corelata-files", "prefix": "demo"}
    report = await run_doctor(_config(tmp_path, server.base_url, storage=storage), probe=False)
    check = _by_name(report)["storage"]
    assert check.status is CheckStatus.PASS
    assert check.message == "s3://corelata-files/demo is writable"


async def test_s3_storage_missing_bucket(tmp_path, server, s3_env):
    storage = {"kind": "s3", "bucket": "no-such-bucket", "endpoint_url": None}
    report = await run_doctor(_config(tmp_path, server.base_url, storage=storage), probe=False)
    check = _by_name(report)["storage"]
    assert check.status is CheckStatus.FAIL
    assert check.message.startswith("storage bucket no-such-bucket at AWS S3 is not writable")
    assert check.fix == "fix storage (bucket, endpoint_url, keys)"


async def test_the_proxy_secret_line_only_when_it_is_set(tmp_path, server, monkeypatch):
    plain = _by_name(await run_doctor(_config(tmp_path, server.base_url), probe=False))
    assert "auth" not in plain
    monkeypatch.setenv("CORELATA_PROXY_SECRET", "s" * 32)
    path = _config(tmp_path, server.base_url, auth={"proxy_secret_env": "CORELATA_PROXY_SECRET"})
    check = _by_name(await run_doctor(path, probe=False))["auth"]
    assert check.status is CheckStatus.PASS
    assert check.message == (
        "requests without the X-Corelata-Proxy-Secret header (CORELATA_PROXY_SECRET) are "
        "refused, /api/health excepted"
    )


async def test_the_worker_line_only_with_a_kick_url_which_is_never_called(tmp_path, server):
    plain = _by_name(await run_doctor(_config(tmp_path, server.base_url), probe=False))
    assert "worker" not in plain
    # an address nothing answers: the line passes without a request (a kick starts a worker)
    path = _config(tmp_path, server.base_url, worker={"kick_url": "https://kick.invalid/"})
    check = _by_name(await run_doctor(path))["worker"]
    assert check.status is CheckStatus.PASS
    assert check.message == "kicks https://kick.invalid/ when a job is queued"


async def test_local_storage_names_its_path(tmp_path, server):
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    check = _by_name(report)["storage"]
    assert check.message == f"{(tmp_path / 'files').resolve()} is writable"


async def test_s3_probe_left_behind_is_a_warning_naming_the_key(
    tmp_path, server, s3_env, monkeypatch
):
    from botocore.exceptions import ClientError

    from corelata.storage import S3Storage

    def refuse(**kw):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObject")

    storage = {"kind": "s3", "bucket": "corelata-files", "prefix": "demo"}
    real = S3Storage.check_writable

    def stuck(self):
        monkeypatch.setattr(self._s3, "delete_object", refuse)
        real(self)

    monkeypatch.setattr(S3Storage, "check_writable", stuck)
    report = await run_doctor(_config(tmp_path, server.base_url, storage=storage), probe=False)
    check = _by_name(report)["storage"]
    assert check.status is CheckStatus.WARN
    assert "demo/.corelata-check-" in check.message and " by hand" in check.fix


# ---------------------------------------------------------------- ingest.ocr (CRL-95)


def _tesseract(monkeypatch, *, installed=True, version="5.3.0", languages=("eng", "osd")):
    def langs():
        if isinstance(languages, Exception):
            raise languages
        return sorted(languages)

    monkeypatch.setattr(ocr, "tesseract_path", lambda: "/usr/bin/tesseract" if installed else None)
    monkeypatch.setattr(ocr, "tesseract_version", lambda: version)
    monkeypatch.setattr(ocr, "installed_languages", langs)


@pytest.mark.parametrize(
    ("ingest", "tesseract", "status", "message"),
    [
        ({}, {}, "pass", "ingest.ocr is off; tesseract 5.3.0 with languages eng"),
        ({}, {"installed": False}, "pass", "ingest.ocr is off; tesseract is not installed"),
        (
            {"ocr": "auto", "ocr_languages": ["eng"]},
            {},
            "pass",
            "ingest.ocr is auto (eng); tesseract 5.3.0 with languages eng",
        ),
        (
            {"ocr": "auto"},
            {"installed": False},
            "warn",
            "ingest.ocr is auto but tesseract is not installed: uploads with scanned PDF pages "
            "will be refused",
        ),
        (
            {"ocr": "auto", "ocr_languages": ["eng", "fra", "deu"]},
            {"languages": ("osd",)},
            "warn",
            "ingest.ocr is auto but tesseract 5.3.0 with languages none lacks eng, fra, deu: "
            "uploads with scanned PDF pages will be refused",
        ),
        (
            {"ocr": "auto"},
            {"languages": ocr.OcrError("tesseract failed: exit 1")},
            "warn",
            "tesseract is installed but does not run: tesseract failed: exit 1",
        ),
    ],
)
async def test_doctor_reports_ocr(
    tmp_path, server, monkeypatch, ingest, tesseract, status, message
):
    """AC5: an OCR line (binary found, languages), and a warning when ocr: auto has no binary."""
    _tesseract(monkeypatch, **tesseract)
    report = await run_doctor(_config(tmp_path, server.base_url, ingest=ingest), probe=False)
    check = _by_name(report)["ocr"]
    assert (check.status.value, check.message) == (status, message)
    assert (check.fix == "") is (status == "pass")
    if status == "warn":
        assert "operator guide, Scanned PDFs" in check.fix


async def test_the_ocr_check_runs_off_the_event_loop(tmp_path, server, monkeypatch):
    on_loop: list[bool] = []

    def where():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            on_loop.append(False)
        else:
            on_loop.append(True)
        return None

    monkeypatch.setattr(ocr, "tesseract_path", where)
    await run_doctor(_config(tmp_path, server.base_url), probe=False)
    assert on_loop == [False]
