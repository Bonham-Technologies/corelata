from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from corelata.config import (
    CONFIG_ENV,
    ConfigError,
    CorelataConfig,
    EvidenceQuotes,
    StructuredOutput,
    config_hash,
    default_config_path,
    load_config,
    validate_config,
)
from corelata.ingest.ocr import OcrSettings
from tests.conftest import BASE_CONFIG


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_defaults(make_config):
    cfg = make_config()
    assert cfg.models["model-a"].structured_output is StructuredOutput.JSON_SCHEMA
    assert cfg.retry.max_attempts == 3
    assert cfg.standards.default_pack == "icd203-base"
    assert cfg.standards.default_profile is None
    assert cfg.pipeline.max_iterations == 2
    assert cfg.pipeline.digest_threshold_tokens == 6000
    assert cfg.pipeline.gate_unit_budget_tokens == 12000
    assert cfg.audit.store_llm_io is True
    assert cfg.roles.profiler is None
    assert cfg.integrations.coglossa is None
    assert cfg.database.url_env == "CORELATA_DATABASE_URL"


def test_all_roles_lists_configured_roles(make_config):
    cfg = make_config(roles={**BASE_CONFIG["roles"], "profiler": {"model": "model-b"}})
    assert cfg.roles.all_roles() == [
        ("gate", "model-a"),
        ("writer", "model-a"),
        ("conveyor", "model-b"),
        ("auditor", "model-b"),
        ("profiler", "model-b"),
    ]


def test_render_cache_mb_defaults_to_64_and_may_be_zero():
    from corelata.config import ApiConfig

    assert ApiConfig().render_cache_mb == 64
    assert ApiConfig(render_cache_mb=0).render_cache_mb == 0  # 0 turns the cache off
    with pytest.raises(ValidationError):
        ApiConfig(render_cache_mb=-1)


def test_job_retention_days_defaults_to_30_and_must_be_positive():
    from corelata.config import WorkerConfig

    assert WorkerConfig().job_retention_days == 30
    with pytest.raises(ValidationError):
        WorkerConfig(job_retention_days=0)


def test_discovery_deadline_defaults_to_ten_minutes_and_is_at_least_one():
    from corelata.config import WorkerConfig

    assert WorkerConfig().discovery_deadline_s == 600
    assert WorkerConfig(discovery_deadline_s=60).discovery_deadline_s == 60
    with pytest.raises(ValidationError, match="greater than or equal to 60"):
        WorkerConfig(discovery_deadline_s=59.9)


def test_discovery_start_deadline_defaults_to_an_hour_and_is_at_least_one_minute():
    from corelata.config import WorkerConfig

    assert WorkerConfig().discovery_start_deadline_s == 3600
    assert WorkerConfig(discovery_start_deadline_s=60).discovery_start_deadline_s == 60
    with pytest.raises(ValidationError, match="greater than or equal to 60"):
        WorkerConfig(discovery_start_deadline_s=59.9)


def test_valid_config_has_no_issues(make_config):
    assert validate_config(make_config()) == []


def test_unknown_backend_and_model_are_errors(make_config):
    cfg = make_config(models={"model-a": {"backend": "nope", "context_window": 8192}})
    messages = [i.message for i in validate_config(cfg) if i.level == "error"]
    assert any("unknown backend 'nope'" in m for m in messages)
    assert any("role 'conveyor' references unknown model 'model-b'" in m for m in messages)


def test_missing_api_key_env_is_error(make_config, monkeypatch):
    monkeypatch.delenv("CORELATA_TEST_KEY", raising=False)
    cfg = make_config(
        backends={"fake": {"base_url": "http://x/v1", "api_key_env": "CORELATA_TEST_KEY"}}
    )
    messages = [i.message for i in validate_config(cfg)]
    assert any("CORELATA_TEST_KEY is not set" in m for m in messages)


def test_missing_packs_dir_is_error(make_config, tmp_path):
    cfg = make_config(standards={"packs_dir": str(tmp_path / "nope")})
    messages = [i.message for i in validate_config(cfg)]
    assert any("packs_dir" in m and "not found" in m for m in messages)


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="chunking"):
        load_config(_write(tmp_path, {**BASE_CONFIG, "chunking": {}}))


def test_load_resolves_relative_paths(tmp_path):
    (tmp_path / "packs").mkdir()
    (tmp_path / "prompts").mkdir()
    data = {**BASE_CONFIG, "standards": {"packs_dir": "packs"}, "prompts_dir": "prompts"}
    cfg, issues = load_config(_write(tmp_path, data))
    assert cfg.standards.packs_dir == (tmp_path / "packs").resolve()
    assert cfg.prompts_dir == (tmp_path / "prompts").resolve()
    assert cfg.storage.path.is_absolute()
    assert issues == []


def test_load_errors_are_one_line(tmp_path):
    path = _write(tmp_path, {**BASE_CONFIG, "models": {}})
    with pytest.raises(ConfigError) as e:
        load_config(path)
    message = str(e.value)
    assert "\n" not in message and "unknown model" in message and "more problem" in message


def test_load_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_load_invalid_yaml(tmp_path):
    path = tmp_path / "corelata.yaml"
    path.write_text("backends: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_load_non_mapping(tmp_path):
    path = tmp_path / "corelata.yaml"
    path.write_text("- a\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_config_hash_ignores_operational_sections(make_config):
    a = make_config()
    b = make_config(
        api={"web_dir": None},
        worker={"concurrency": 7},
        auth={"mode": "none", "logout_url": "/oauth2/sign_out"},  # M18: operational too
    )
    c = make_config(pipeline={"max_iterations": 3})
    assert config_hash(a) == config_hash(b)
    assert config_hash(a) != config_hash(c)
    assert len(config_hash(a)) == 16


def test_null_section_means_defaults(make_config):
    cfg = make_config(database=None, storage=None, worker=None, api=None, auth=None)
    assert cfg.worker.concurrency == 2


def test_default_config_path(monkeypatch):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert default_config_path() == Path("corelata.yaml")
    monkeypatch.setenv(CONFIG_ENV, "/etc/corelata.yaml")
    assert default_config_path() == Path("/etc/corelata.yaml")


BASE_URL_REFUSED = (
    "backends.fake.base_url: Value error, must not contain a query string (?...) or a fragment "
    "(#...): Corelata adds the request path (/chat/completions, /models) to base_url, so it "
    "would land inside the query. Write the server's address and path only, such as "
    "http://models:8000/v1, and give a key with api_key_env (the name of an environment "
    "variable that holds it)"
)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://h/v1?key=abc",
        "http://h/v1?",
        "http://h/v1#models",
        "http://h:8000/v1/?api-version=1",
    ],
)
def test_a_base_url_with_a_query_or_a_fragment_is_refused(tmp_path, base_url):
    path = _write(tmp_path, {**BASE_CONFIG, "backends": {"fake": {"base_url": base_url}}})
    with pytest.raises(ConfigError) as refused:
        load_config(path)
    assert str(refused.value) == f"{path}: {BASE_URL_REFUSED}"


@pytest.mark.parametrize("base_url", ["http://h/v1", "http://h:8000/v1/", "https://u:p@h/v1"])
def test_a_plain_base_url_is_accepted(make_config, base_url):
    assert make_config(backends={"fake": {"base_url": base_url}}).backends["fake"].base_url == (
        base_url
    )


def test_auth_header_must_be_http_token(make_config):
    with pytest.raises(ValueError, match="HTTP header name"):
        make_config(auth={"mode": "trusted_header", "header": "bad header"})


def test_example_config_loads():
    cfg, issues = load_config(Path(__file__).parents[1] / "corelata.example.yaml")
    assert cfg.standards.default_pack == "icd203-base" and issues == []
    assert cfg.worker.discovery_start_deadline_s == 3600  # both limits are written out
    assert cfg.worker.discovery_deadline_s == 600


def test_evidence_quotes_default_off_and_required_for_a_new_install():
    """CRL-93: an install upgraded without the key keeps its behaviour; the example config a
    new install starts from asks for quotes. Both settings shape output: config_hash names them."""
    pipeline = CorelataConfig.model_validate(BASE_CONFIG).pipeline
    assert pipeline.evidence_quotes is EvidenceQuotes.OFF and pipeline.quote_match_threshold == 1.0
    example = Path(__file__).parents[1] / "corelata.example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))["pipeline"]
    assert raw["evidence_quotes"] == "required" and raw["quote_match_threshold"] == 1.0
    hashes = {
        config_hash(CorelataConfig.model_validate({**BASE_CONFIG, "pipeline": pipeline}))
        for pipeline in (
            {},
            {"evidence_quotes": "required"},
            {"evidence_quotes": "optional"},
            {"quote_match_threshold": 0.9},
        )
    }
    assert len(hashes) == 4
    for bad in ({"evidence_quotes": "always"}, {"quote_match_threshold": 0.4}):
        with pytest.raises(ValidationError):
            CorelataConfig.model_validate({**BASE_CONFIG, "pipeline": bad})


def test_pipeline_digest_chunk_tokens_default_and_floor():
    assert CorelataConfig.model_validate(BASE_CONFIG).pipeline.digest_chunk_tokens == 4000
    with pytest.raises(ValidationError):
        CorelataConfig.model_validate({**BASE_CONFIG, "pipeline": {"digest_chunk_tokens": 10}})


def test_pipeline_writer_unit_budget_default_and_floor():
    assert CorelataConfig.model_validate(BASE_CONFIG).pipeline.writer_unit_budget_tokens == 16000
    with pytest.raises(ValidationError):
        CorelataConfig.model_validate(
            {**BASE_CONFIG, "pipeline": {"writer_unit_budget_tokens": 10}}
        )


@pytest.mark.parametrize("url", ["/logout", "https://idp.example/logout?x=1", "http://p/out"])
def test_logout_url_accepts_a_site_path_or_an_http_url(make_config, url):
    assert make_config(auth={"logout_url": url}).auth.logout_url == url


@pytest.mark.parametrize("url", ["javascript:alert(1)", "//evil.example", "data:text/html,x", ""])
def test_logout_url_refuses_anything_else(make_config, url):
    with pytest.raises(ValueError, match="site path starting with /"):
        make_config(auth={"logout_url": url})


def test_logout_url_defaults_to_none(make_config):
    assert make_config().auth.logout_url is None


@pytest.mark.parametrize(
    "url",
    [
        "/\\evil.example",  # a backslash is a slash to a browser
        "/\t/evil.example",  # the URL parser strips the tab: //evil.example
        "/\n/evil.example",
        "https://ok.example/ x",
        "/a\\b",
        "https://ok.example/\x00",
    ],
)
def test_logout_url_refuses_what_a_browser_reads_as_another_site(make_config, url):
    with pytest.raises(ValueError, match="site path starting with /"):
        make_config(auth={"logout_url": url})


# M19: storage.kind s3 (copied from Coglossa, spec §12.1)

S3_KEYS = ("CORELATA_S3_ACCESS_KEY_ID", "CORELATA_S3_SECRET_ACCESS_KEY")


def test_storage_kind_defaults_to_local_and_s3_is_accepted(make_config):
    assert make_config().storage.kind == "local"
    assert make_config(storage={"path": "/x"}).storage.kind == "local"
    cfg = make_config(storage={"kind": "s3", "bucket": "bkt", "endpoint_url": "https://e/s3"})
    assert (cfg.storage.kind, cfg.storage.bucket, cfg.storage.endpoint_url) == (
        "s3",
        "bkt",
        "https://e/s3",
    )
    assert cfg.storage.region == "us-east-1" and cfg.storage.prefix == ""
    assert (cfg.storage.access_key_id_env, cfg.storage.secret_access_key_env) == S3_KEYS


def test_s3_storage_rejects_unknown_fields_and_kinds(make_config):
    with pytest.raises(ValidationError):
        make_config(storage={"kind": "s3", "bucket": "bkt", "path": "/x"})
    with pytest.raises(ValidationError):
        make_config(storage={"kind": "s3"})  # a bucket is required
    with pytest.raises(ValidationError):
        make_config(storage={"kind": "gcs"})


@pytest.mark.parametrize("missing", S3_KEYS)
def test_s3_storage_keys_must_be_set(tmp_path, monkeypatch, missing):
    for var in S3_KEYS:
        monkeypatch.setenv(var, "set")
    monkeypatch.setenv(missing, "")
    path = _write(tmp_path, {**BASE_CONFIG, "storage": {"kind": "s3", "bucket": "bkt"}})
    with pytest.raises(ConfigError, match=f"storage: environment variable {missing} is not set"):
        load_config(path)


def test_s3_storage_is_not_path_resolved_and_leaves_the_config_hash(tmp_path, monkeypatch):
    for var in S3_KEYS:
        monkeypatch.setenv(var, "set")
    local, _ = load_config(_write(tmp_path, BASE_CONFIG))
    s3, issues = load_config(
        _write(tmp_path, {**BASE_CONFIG, "storage": {"kind": "s3", "bucket": "bkt"}})
    )
    assert s3.storage.kind == "s3" and s3.storage.bucket == "bkt" and issues == []
    assert config_hash(s3) == config_hash(local)  # storage is operational


# M19: auth.proxy_secret_env (copied from Coglossa, spec §12.1)


def test_proxy_secret_is_off_by_default(make_config):
    assert make_config().auth.proxy_secret_env is None


def test_proxy_secret_env_must_be_set(tmp_path, monkeypatch):
    monkeypatch.delenv("CORELATA_PROXY_SECRET", raising=False)
    path = _write(tmp_path, {**BASE_CONFIG, "auth": {"proxy_secret_env": "CORELATA_PROXY_SECRET"}})
    with pytest.raises(ConfigError, match="auth: environment variable CORELATA_PROXY_SECRET"):
        load_config(path)
    monkeypatch.setenv("CORELATA_PROXY_SECRET", "")  # empty is as good as unset
    with pytest.raises(ConfigError, match="CORELATA_PROXY_SECRET is not set"):
        load_config(path)
    monkeypatch.setenv("CORELATA_PROXY_SECRET", "s" * 32)
    cfg, _ = load_config(path)
    assert cfg.auth.proxy_secret_env == "CORELATA_PROXY_SECRET"
    assert config_hash(cfg) == config_hash(load_config(_write(tmp_path, BASE_CONFIG))[0])


def test_an_empty_proxy_secret_name_is_refused_not_read_as_off(tmp_path):
    for name in ("", "  "):
        path = _write(tmp_path, {**BASE_CONFIG, "auth": {"proxy_secret_env": name}})
        with pytest.raises(ConfigError, match="auth.proxy_secret_env: .*must name an environment"):
            load_config(path)


# M19: worker.kick_url, kick_token_env, extra_headers_env (copied from Coglossa, spec §12.1)


def test_the_kick_is_off_by_default_and_its_url_must_be_http(make_config):
    worker = make_config().worker
    assert (worker.kick_url, worker.kick_token_env, worker.extra_headers_env) == (None, None, {})
    assert make_config(worker={"kick_url": "https://k/x"}).worker.kick_url == "https://k/x"
    with pytest.raises(ValidationError, match="must be an http:// or https:// URL"):
        make_config(worker={"kick_url": "ftp://k/x"})


def test_extra_header_names_must_be_http_tokens(make_config):
    with pytest.raises(ValidationError, match="'Modal Key' is not an HTTP header name"):
        make_config(worker={"extra_headers_env": {"Modal Key": "K"}})


def test_the_kick_variables_must_be_set(tmp_path, monkeypatch):
    monkeypatch.setenv("KICK_TOKEN", "t")
    monkeypatch.setenv("PLATFORM_KEY", "k")
    monkeypatch.delenv("PLATFORM_SECRET", raising=False)
    worker = {
        "kick_url": "https://k/",
        "kick_token_env": "KICK_TOKEN",
        "extra_headers_env": {"Modal-Key": "PLATFORM_KEY", "Modal-Secret": "PLATFORM_SECRET"},
    }
    path = _write(tmp_path, {**BASE_CONFIG, "worker": worker})
    with pytest.raises(ConfigError, match="worker: environment variable PLATFORM_SECRET") as e:
        load_config(path)
    assert "PLATFORM_KEY" not in str(e.value) and "KICK_TOKEN" not in str(e.value)
    monkeypatch.delenv("KICK_TOKEN")
    with pytest.raises(ConfigError, match="KICK_TOKEN is not set .and 1 more problem"):
        load_config(path)
    monkeypatch.setenv("KICK_TOKEN", "t")
    monkeypatch.setenv("PLATFORM_SECRET", "s")
    cfg, _ = load_config(path)
    assert cfg.worker.extra_headers_env == worker["extra_headers_env"]
    assert config_hash(cfg) == config_hash(load_config(_write(tmp_path, BASE_CONFIG))[0])


def test_an_empty_kick_token_name_is_refused_not_read_as_off(make_config):
    for name in ("", "  "):
        with pytest.raises(ValidationError, match="must name an environment variable"):
            make_config(worker={"kick_url": "https://k/", "kick_token_env": name})


def test_the_kick_url_may_not_carry_a_credential(make_config):
    for url in ("https://user:pass@k/x", "http://token@k/"):
        with pytest.raises(ValidationError, match="must not contain a user name or password"):
            make_config(worker={"kick_url": url})
    assert make_config(worker={"kick_url": "https://k/x?a=b@c"}).worker.kick_url


def _with_coglossa(base_url: str) -> dict:
    return {**BASE_CONFIG, "integrations": {"coglossa": {"base_url": base_url}}}


@pytest.mark.parametrize(
    ("base_url", "reason"),
    [
        ("coglossa-api:8080", "must be an http:// or https:// URL"),
        ("ftp://coglossa/", "must be an http:// or https:// URL"),
        ("http:///api", "must be an http:// or https:// URL"),
        ("http://coglossa:8080?x=1", "must not contain a query string"),
        ("http://coglossa:8080/#frag", "must not contain a query string"),
        ("http://coglossa:8080/api", "must be Coglossa's root URL"),
        ("http://coglossa:8080/api/health", "must be Coglossa's root URL"),
        ("http://coglossa:8080/api/runs/r1/exports/json", "must be Coglossa's root URL"),
        ("http://[bad]", "is not a valid URL"),
        ("http://coglossa:abc", "is not a valid URL"),
    ],
)
def test_a_wrong_coglossa_base_url_is_refused_with_its_field_path(tmp_path, base_url, reason):
    """CRL-55: the Coglossa URL is checked as a backend's is, and named by its field path."""
    path = _write(tmp_path, _with_coglossa(base_url))
    with pytest.raises(ConfigError) as refused:
        load_config(path)
    message = str(refused.value)
    assert message.startswith(f"{path}: integrations.coglossa.base_url: Value error, {reason}")
    assert "http://coglossa-api:8080" in message  # the accepted shape, as an example


@pytest.mark.parametrize(
    "base_url",
    [
        "http://coglossa-api:8080",
        "http://coglossa:8080/",
        "https://u:p@h/coglossa",
        "http://h/apis",
    ],
)
def test_a_root_coglossa_base_url_is_accepted(tmp_path, base_url):
    cfg, _ = load_config(_write(tmp_path, _with_coglossa(base_url)))
    assert cfg.integrations.coglossa.base_url == base_url


@pytest.mark.parametrize(
    ("base_url", "reason"),
    [
        ("models:8000/v1", "must be an http:// or https:// URL"),
        ("http://h:8000/v1/chat/completions", "must not end in a request path"),
        ("http://h:8000/v1/models/", "must not end in a request path"),
        ("http://[::1", "is not a valid URL"),
    ],
)
def test_a_backend_base_url_without_a_scheme_or_ending_in_a_request_path_is_refused(
    tmp_path, base_url, reason
):
    path = _write(tmp_path, {**BASE_CONFIG, "backends": {"fake": {"base_url": base_url}}})
    with pytest.raises(ConfigError, match=f"backends.fake.base_url: Value error, {reason}"):
        load_config(path)


def test_a_plugin_backend_keeps_its_own_scheme_but_not_a_query(tmp_path, make_config):
    """A corelata.backends plugin kind owns its URL's scheme and path; the query rule holds."""
    plugin = {"kind": "grpc", "base_url": "grpc://x/chat/completions"}
    assert make_config(backends={"fake": plugin}).backends["fake"].base_url == plugin["base_url"]
    path = _write(
        tmp_path,
        {**BASE_CONFIG, "backends": {"fake": {"kind": "grpc", "base_url": "grpc://x?k=1"}}},
    )
    with pytest.raises(ConfigError, match="backends.fake.base_url: Value error, must not contain"):
        load_config(path)


def test_ingest_ocr_is_off_by_default_and_auto_gives_its_languages(make_config):
    """CRL-95: OCR is opt-in; auto reads scanned pages in the configured languages."""
    cfg = make_config()
    assert cfg.ingest.ocr == "off" and cfg.ingest.ocr_languages == ["eng"]
    assert cfg.ingest.ocr_settings() is None
    auto = make_config(ingest={"ocr": "auto", "ocr_languages": ["eng", "chi_sim"]})
    assert auto.ingest.ocr_settings() == OcrSettings(languages=("eng", "chi_sim"))
    assert make_config(ingest=None).ingest.ocr == "off"


def test_ingest_ocr_off_written_bare_in_yaml_reads_as_off(tmp_path):
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(BASE_CONFIG) + "ingest:\n  ocr: off\n", encoding="utf-8")
    cfg, _ = load_config(path)
    assert cfg.ingest.ocr == "off"
    path.write_text(yaml.safe_dump(BASE_CONFIG) + "ingest:\n  ocr: on\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"ingest\.ocr: Input should be 'off' or 'auto'"):
        load_config(path)


@pytest.mark.parametrize("languages", [[], ["eng+fra"], ["../x"], ["e ng"]])
def test_ingest_ocr_languages_are_tesseract_codes(make_config, languages):
    with pytest.raises(ValidationError, match="ocr_languages"):
        make_config(ingest={"ocr": "auto", "ocr_languages": languages})


def test_ingest_leaves_the_config_hash(make_config):
    """What OCR read is recorded on each source; the run's settings hash does not change."""
    assert config_hash(make_config()) == config_hash(make_config(ingest={"ocr": "auto"}))


def test_deploy_configs_load_with_their_ocr_settings():
    deploy = Path(__file__).parents[2] / "deploy" / "config"
    example, demo = (
        CorelataConfig.model_validate(yaml.safe_load((deploy / name).read_text(encoding="utf-8")))
        for name in ("corelata.example.yaml", "corelata.demo.yaml")
    )
    assert example.ingest.ocr == "off" and demo.ingest.ocr == "auto"


def test_prior_judgments_default_and_bounds():
    """CRL-97: unset, project memory is off (`max_reports: 0`), so an upgraded install keeps its
    behaviour; the example config a new install starts from turns it on with three reports in
    2000 tokens. The settings shape output, so they are in config_hash."""
    from corelata.config import config_hash
    from tests.conftest import build_config

    cfg = build_config()
    assert cfg.pipeline.prior_judgments.max_reports == 0
    assert cfg.pipeline.prior_judgments.budget_tokens == 2000
    on = build_config(pipeline={"prior_judgments": {"max_reports": 3}})
    assert on.pipeline.prior_judgments.max_reports == 3
    assert config_hash(on) != config_hash(cfg)
    example_path = Path(__file__).parents[1] / "corelata.example.yaml"
    example = yaml.safe_load(example_path.read_text(encoding="utf-8"))["pipeline"]
    assert example["prior_judgments"] == {"max_reports": 3, "budget_tokens": 2000}
    for bad in ({"max_reports": -1}, {"max_reports": 21}, {"budget_tokens": 99}, {"x": 1}):
        with pytest.raises(ValidationError):
            build_config(pipeline={"prior_judgments": bad})
