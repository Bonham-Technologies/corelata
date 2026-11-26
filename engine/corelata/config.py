"""corelata.yaml: the single file that adapts Corelata to a deployment (spec §11)."""

import hashlib
import json
import os
import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from corelata.ingest.ocr import OcrSettings

CONFIG_ENV = "CORELATA_CONFIG"
ROLE_NAMES = ("gate", "writer", "conveyor", "auditor", "profiler")


def default_config_path() -> Path:
    """`--config`'s default: $CORELATA_CONFIG (the container images set it), else
    ./corelata.yaml."""
    return Path(os.environ.get(CONFIG_ENV) or "corelata.yaml")


class ConfigError(Exception):
    """Configuration is invalid; the message is safe to show to an operator."""


class StructuredOutput(StrEnum):
    JSON_SCHEMA = "json_schema"  # server enforces the schema (vLLM/Ollama/TGI guided decoding)
    JSON_OBJECT = "json_object"  # server guarantees JSON; schema is described in the prompt
    NONE = "none"  # plain text; schema described in the prompt and JSON extracted


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_base_url(
    value: str,
    *,
    paths: str,
    example: str,
    wrong_path: Callable[[str], str | None],
    http_only: bool = True,
) -> str:
    """The checks a base URL that Corelata adds request paths to must pass (CRL-39, CRL-55):
    a URL that parses, http:// or https:// with a host (`http_only`), no query or fragment, and
    a path that does not already name what Corelata adds (`wrong_path` gives the reason for a
    path, or None). `paths` names those request paths and `example` the accepted shape."""
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError on a port that is not a number
    except ValueError as e:
        raise ValueError(f"is not a valid URL ({e}): write it as {example}") from None
    if http_only and (parts.scheme not in ("http", "https") or not parts.hostname):
        raise ValueError(f"must be an http:// or https:// URL with a host, such as {example}")
    # httpx joins the request path after the query: http://h/v1?key=abc/chat/completions
    # (CRL-39, R-M17-3)
    if "?" in value or "#" in value:
        raise ValueError(
            "must not contain a query string (?...) or a fragment (#...): Corelata adds the "
            f"request path ({paths}) to base_url, so it would land inside the query. Write the "
            f"server's address and path only, such as {example}, and give a key with "
            "api_key_env (the name of an environment variable that holds it)"
        )
    if reason := wrong_path(parts.path.rstrip("/")):
        raise ValueError(f"{reason}: Corelata adds {paths} to it. Write it as {example}")
    return value


_BACKEND_PATHS = ("/chat/completions", "/models")


class BackendConfig(_Strict):
    kind: str = "openai_compat"
    base_url: str
    api_key_env: str | None = None
    max_concurrency: int = Field(4, ge=1)
    timeout_s: float = Field(120.0, gt=0)

    @field_validator("base_url")
    @classmethod
    def _a_server_address(cls, value: str, info: ValidationInfo) -> str:
        # a plugin kind (corelata.backends) owns its URL's scheme and path; the query rule holds
        # for every kind, as it did before CRL-55
        compat = info.data.get("kind", "openai_compat") == "openai_compat"
        return _check_base_url(
            value,
            paths=", ".join(_BACKEND_PATHS),
            example="http://models:8000/v1",
            http_only=compat,
            wrong_path=lambda path: (
                "must not end in a request path"
                if compat and path.endswith(_BACKEND_PATHS)
                else None
            ),
        )


# CRL-140: the request body keys Corelata sets itself, which `request_extra` may not replace, and
# what to set instead. Replacing one would bypass the config (temperature, max_tokens) or break
# the call (model, messages, response_format, stream). The keys after them Corelata does not
# send, but the client reads the text of the first choice only: more choices would be paid for
# and dropped, and a tool call has no text to read.
RESERVED_REQUEST_KEYS: dict[str, str] = {
    "model": "Corelata sets it; set models.<key>.name",
    "messages": "Corelata sets it; the prompt is Corelata's",
    "response_format": "Corelata sets it; set models.<key>.structured_output",
    "temperature": "Corelata sets it; set models.<key>.temperature",
    "max_tokens": "Corelata sets it; set models.<key>.max_output_tokens",
    "stream": "Corelata sets it; Corelata reads one whole reply",
    "n": "Corelata reads one choice",
    "tools": "Corelata reads the reply's text, not tool calls",
    "tool_choice": "Corelata reads the reply's text, not tool calls",
    "functions": "Corelata reads the reply's text, not function calls",
    "function_call": "Corelata reads the reply's text, not function calls",
}
REASONING_MAX_CHARS = 20000


class ModelConfig(_Strict):
    backend: str
    name: str | None = None  # model id sent to the server; defaults to the config key
    context_window: int = Field(ge=2048)
    structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA
    bytes_per_token: float = Field(2.5, gt=0)  # conservative UTF-8 bytes per token estimate
    max_output_tokens: int | None = Field(None, ge=1)
    temperature: float = Field(0.2, ge=0)
    # CRL-140: keys merged into every chat request body as given, for a server's own options
    # (such as chat_template_kwargs: {enable_thinking: false}). They shape output, so they are
    # in config_hash; left out of the dump when empty, so an existing config's hash is unchanged.
    request_extra: dict[str, Any] = Field(default_factory=dict, exclude_if=lambda v: not v)
    # CRL-140: keep the model's reasoning (the server's `reasoning` or `reasoning_content`, or a
    # leading <think> block) with each call record, at most `reasoning_max_chars` characters of
    # it, when audit.store_llm_io is on too. Neither shapes output: config_hash leaves them out.
    store_reasoning: bool = Field(False, exclude_if=lambda v: v is False)
    reasoning_max_chars: int = Field(
        REASONING_MAX_CHARS, ge=1, exclude_if=lambda v: v == REASONING_MAX_CHARS
    )

    @field_validator("request_extra", mode="before")
    @classmethod
    def _null_extra(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("request_extra")
    @classmethod
    def _extra_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if key in RESERVED_REQUEST_KEYS:
                raise ValueError(
                    f"'{key}' cannot be sent from request_extra: {RESERVED_REQUEST_KEYS[key]}"
                )
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as e:
            raise ValueError(f"must hold JSON values only (strings, numbers, ...): {e}") from None
        return value


class RoleConfig(_Strict):
    model: str


class RolesConfig(_Strict):
    """Spec §4.4: one model per role. `profiler` is only used by `corelata profile extract`."""

    gate: RoleConfig
    writer: RoleConfig
    conveyor: RoleConfig
    auditor: RoleConfig
    profiler: RoleConfig | None = None
    # CRL-94: maps a finished report onto the report schema for a check run; unset, the
    # writer's model does it. Left out of the dump when unset, so `config_hash` is unchanged.
    structurer: RoleConfig | None = Field(None, exclude_if=lambda v: v is None)

    def all_roles(self) -> list[tuple[str, str]]:
        roles = [
            ("gate", self.gate.model),
            ("writer", self.writer.model),
            ("conveyor", self.conveyor.model),
            ("auditor", self.auditor.model),
        ]
        if self.profiler is not None:
            roles.append(("profiler", self.profiler.model))
        if self.structurer is not None:
            roles.append(("structurer", self.structurer.model))
        return roles

    def model_for(self, role: str) -> str:
        if role == "structurer" and self.structurer is None:
            return self.writer.model
        return dict(self.all_roles())[role]


class RetryConfig(_Strict):
    max_attempts: int = Field(4, ge=1)
    base_delay_s: float = Field(2.0, ge=0)
    max_delay_s: float = Field(60.0, ge=0)


class StandardsConfig(_Strict):
    """Spec §6: where customer packs live and which one a run uses by default."""

    packs_dir: Path | None = None  # None: only the packs built into the engine
    default_pack: str = "icd203-base"
    default_profile: str | None = None


class EvidenceQuotes(StrEnum):
    """How claims quote their evidence (CRL-93). `required`: every claim quotes each unit it
    cites (units of digested sources excepted); `optional`: a claim may quote; `off`: no quotes,
    the run is the one Corelata made before quotes existed. Any quote given is checked by the
    engine against its unit."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    OFF = "off"


class PriorJudgmentsConfig(_Strict):
    """CRL-97: the key judgments of the project's earlier accepted reports, which the writer and
    the auditor read so a report can say how its judgments stand against them (ICD 203
    D.6.e(7), `icd203.tc.7`). `max_reports: 0` reads none: the run is the one Corelata made
    before project memory existed. Unset in a config, 0: an upgraded install keeps its
    behaviour until it opts in; the example config a new install starts from says 3."""

    max_reports: int = Field(0, ge=0, le=20)  # the newest accepted reports, by acceptance
    # What their judgments may take of the writer's input; the oldest are left out first.
    budget_tokens: int = Field(2000, ge=100)


class PipelineConfig(_Strict):
    """Spec §7.2 and §7.4."""

    max_iterations: int = Field(2, ge=0, le=10)
    digest_threshold_tokens: int = Field(6000, ge=500)
    digest_chunk_tokens: int = Field(4000, ge=500)  # units per digest request, at most this many
    writer_unit_budget_tokens: int = Field(16000, ge=500)  # full-text units the writer sees
    gate_unit_budget_tokens: int = Field(12000, ge=500)
    # CRL-93. Unset in a config, `off`: an upgraded install keeps its behaviour; the example
    # config a new install starts from says `required`.
    evidence_quotes: EvidenceQuotes = EvidenceQuotes.OFF
    # The share of a quote's words that must match a run of the unit's words, in order; 1.0
    # (exact, after case, whitespace and punctuation are set aside) unless sources are noisy.
    quote_match_threshold: float = Field(1.0, ge=0.5, le=1.0)
    prior_judgments: PriorJudgmentsConfig = Field(default_factory=PriorJudgmentsConfig)


_TESSERACT_LANGUAGE = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class IngestConfig(_Strict):
    """Reading uploads (spec §5). `ocr: auto` reads a PDF's scanned pages (an image and no text
    layer) with Tesseract in the languages listed, in Tesseract's codes (eng, fra, deu, ...),
    each installed as a language pack; `off` refuses them with needs_ocr (CRL-95)."""

    ocr: Literal["off", "auto"] = "off"
    ocr_languages: list[str] = Field(default_factory=lambda: ["eng"], min_length=1)

    @field_validator("ocr", mode="before")
    @classmethod
    def _yaml_off(cls, value: Any) -> Any:
        return "off" if value is False else value  # YAML 1.1 reads a bare `off` as false

    @field_validator("ocr_languages")
    @classmethod
    def _language_codes(cls, value: list[str]) -> list[str]:
        for code in value:
            if not _TESSERACT_LANGUAGE.match(code):
                raise ValueError(
                    f"'{code}' is not a Tesseract language code (letters, digits and _, "
                    "such as eng or chi_sim)"
                )
        return value

    def ocr_settings(self) -> OcrSettings | None:
        return OcrSettings(languages=tuple(self.ocr_languages)) if self.ocr == "auto" else None


class AuditConfig(_Strict):
    store_llm_io: bool = True


class DatabaseConfig(_Strict):
    url_env: str = "CORELATA_DATABASE_URL"  # env var holding postgresql://user:pass@host:port/db

    def url(self) -> str | None:
        return os.environ.get(self.url_env) or None


class StorageConfig(_Strict):
    kind: Literal["local"] = "local"  # or "s3": S3StorageConfig
    path: Path = Path("/data/files")


class S3StorageConfig(_Strict):
    """Files in an S3-compatible bucket (Supabase Storage on the hosted demo; copied from
    Coglossa). The keys are read from the environment variables named here; they never go in
    the config file."""

    kind: Literal["s3"]
    endpoint_url: str | None = None  # None: AWS S3 itself
    region: str = "us-east-1"
    bucket: str = Field(min_length=3, max_length=63)
    prefix: str = ""  # keys go under this prefix, e.g. one bucket shared by several sites
    access_key_id_env: str = "CORELATA_S3_ACCESS_KEY_ID"
    secret_access_key_env: str = "CORELATA_S3_SECRET_ACCESS_KEY"


def _storage_kind(value: Any) -> str:
    if isinstance(value, dict):
        return value.get("kind", "local")
    return getattr(value, "kind", "local")


AnyStorageConfig = Annotated[
    Annotated[StorageConfig, Tag("local")] | Annotated[S3StorageConfig, Tag("s3")],
    Discriminator(_storage_kind),
]


class WorkerConfig(_Strict):
    # jobs one worker process executes at the same time: runs and discoveries share these slots
    # (a discovery is fetched first, R-M17-29)
    concurrency: int = Field(2, ge=1)
    # re-queue jobs of a worker silent this long; a run is minutes, not hours (spec §16)
    stalled_after_s: float = Field(900.0, ge=30)
    # closed jobs (failed, cancelled, aborted) older than this are deleted daily; the worker
    # deletes succeeded ones itself (CRL-10)
    job_retention_days: int = Field(30, ge=1)
    # the work limit: a discovery not ended this long after the worker claimed it is failed, by
    # the API's read, the worker or its sweep, whichever comes first (CRL-38, R-M17-1, R-M17-26)
    discovery_deadline_s: float = Field(600.0, ge=60)
    # the start limit: a discovery the worker has not claimed this long after it was created
    # (the worker stopped, or busy with runs) is failed the same way (R-M17-26)
    discovery_start_deadline_s: float = Field(3600.0, ge=60)
    # POSTed after each queued job, so an on-demand worker starts (the hosted demo, copied from
    # Coglossa, M19); unset: an always-on worker polls the queue
    kick_url: str | None = None
    kick_token_env: str | None = None  # sent as "Authorization: Bearer <value>"
    # more headers for the kick, each {header name: name of the variable holding its value},
    # e.g. a hosting platform's own access token
    extra_headers_env: dict[str, str] = Field(default_factory=dict)

    @field_validator("kick_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("must be an http:// or https:// URL")
        if value is not None and "@" in urlsplit(value).netloc:
            raise ValueError(
                "must not contain a user name or password (user:pass@): "
                "a credential would reach the logs; use kick_token_env or extra_headers_env"
            )
        return value

    @field_validator("kick_token_env")
    @classmethod
    def _kick_token_variable_named(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(
                "must name an environment variable (e.g. CORELATA_KICK_TOKEN), "
                "or be left out to send no token"
            )
        return value

    @field_validator("extra_headers_env")
    @classmethod
    def _header_names(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not _HTTP_TOKEN.fullmatch(name):
                raise ValueError(f"{name!r} is not an HTTP header name: {_HEADER_NAME_HELP}")
        return value


def env_headers(names: dict[str, str]) -> dict[str, str]:
    """{header: variable name} to {header: the variable's value}; validate_config has made
    sure each variable is set."""
    return {header: os.environ.get(var, "") for header, var in names.items()}


class ApiConfig(_Strict):
    max_upload_mb: int = Field(200, ge=1)
    progress_poll_s: float = Field(1.0, gt=0, le=60)
    # memory for claim-id re-renders (the review screen's report); 0 stores none (CRL-19)
    render_cache_mb: int = Field(64, ge=0)
    web_dir: Path | None = None


_HTTP_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_HEADER_NAME_HELP = "letters, digits and !#$%&'*+-.^_`|~, without spaces (e.g. Modal-Key)"


class AuthConfig(_Strict):
    """Spec §10.1. `none`: anyone who reaches the API may use it. `trusted_header`: a reverse
    proxy authenticates people and passes the user name in `header`."""

    mode: Literal["none", "trusted_header"] = "none"
    header: str = "X-Remote-User"
    # the proxy's own sign-out page: the web app's header shows "Sign out" and posts there
    # (copied from Coglossa, M18 spec §7.3); unset, no Sign out is shown
    logout_url: str | None = None
    # A secret the authenticating proxy adds to every request (header X-Corelata-Proxy-Secret);
    # requests without it are refused, /api/health excepted. For an API whose address is
    # reachable without the proxy, such as the hosted demo's (copied from Coglossa, M19).
    proxy_secret_env: str | None = None

    @field_validator("header")
    @classmethod
    def _http_token(cls, value: str) -> str:
        if not _HTTP_TOKEN.fullmatch(value):
            raise ValueError(
                "must be an HTTP header name: letters, digits and !#$%&'*+-.^_`|~, without "
                "spaces (e.g. X-Remote-User)"
            )
        return value

    @field_validator("proxy_secret_env")
    @classmethod
    def _secret_variable_named(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(
                "must name an environment variable (e.g. CORELATA_PROXY_SECRET), "
                "or be left out to turn the proxy secret off"
            )
        return value

    @field_validator("logout_url")
    @classmethod
    def _sign_out_target(cls, value: str | None) -> str | None:
        # the web app posts a form to it: a `javascript:` or `data:` value must not get through
        # A browser strips tab, CR and LF and reads `\` as `/`, so `/\x` and `/<tab>/x` would
        # both mean `//x`: refuse any backslash, whitespace or control character outright.
        if value is not None and not (
            not any(c == "\\" or c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in value)
            and (
                (value.startswith("/") and value[1:2] not in ("/", "\\"))
                or value.startswith(("http://", "https://"))
            )
        ):
            raise ValueError(
                "must be a site path starting with / (not //) or an http:// or https:// URL "
                "(e.g. /oauth2/sign_out)"
            )
        return value


class CoglossaIntegration(_Strict):
    """Spec §5.3: fetch a Coglossa run export by id instead of uploading it."""

    base_url: str
    api_key_env: str | None = None

    @field_validator("base_url")
    @classmethod
    def _coglossa_root(cls, value: str) -> str:
        # its API lives under /api: a base_url that already names it doubles it (CRL-55); a
        # reverse proxy's own prefix, such as https://gw/api/coglossa, is fine
        return _check_base_url(
            value,
            paths="/api/health and /api/runs/<id>/exports/json",
            example="http://coglossa-api:8080",
            wrong_path=lambda path: (
                "must be Coglossa's root URL, not a path of its API"
                if path.endswith(("/api", "/api/health")) or "/api/runs/" in path + "/"
                else None
            ),
        )


class IntegrationsConfig(_Strict):
    coglossa: CoglossaIntegration | None = None


class CorelataConfig(_Strict):
    backends: dict[str, BackendConfig]
    models: dict[str, ModelConfig]
    roles: RolesConfig
    retry: RetryConfig = Field(default_factory=RetryConfig)
    standards: StandardsConfig = Field(default_factory=StandardsConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    prompts_dir: Path | None = None
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: AnyStorageConfig = Field(default_factory=StorageConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)

    @field_validator(
        "standards",
        "pipeline",
        "ingest",
        "database",
        "storage",
        "worker",
        "api",
        "auth",
        "integrations",
        mode="before",
    )
    @classmethod
    def _null_section(cls, value: Any) -> Any:
        return {} if value is None else value


class ConfigIssue(BaseModel):
    level: Literal["error", "warning"]
    message: str


def validate_config(cfg: CorelataConfig) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []

    def add(level: Literal["error", "warning"], message: str) -> None:
        issues.append(ConfigIssue(level=level, message=message))

    for name, model in cfg.models.items():
        if model.backend not in cfg.backends:
            add("error", f"model '{name}' references unknown backend '{model.backend}'")
    for label, model_key in cfg.roles.all_roles():
        if model_key not in cfg.models:
            add("error", f"role '{label}' references unknown model '{model_key}'")
    for name, backend in cfg.backends.items():
        if backend.api_key_env and os.environ.get(backend.api_key_env) is None:
            add("error", f"backend '{name}': environment variable {backend.api_key_env} is not set")
    packs_dir = cfg.standards.packs_dir
    if packs_dir is not None and not packs_dir.is_dir():
        add("error", f"standards.packs_dir not found: {packs_dir}")
    coglossa = cfg.integrations.coglossa
    key_env = coglossa.api_key_env if coglossa is not None else None
    if key_env and os.environ.get(key_env) is None:
        add("error", f"integrations.coglossa: environment variable {key_env} is not set")
    if isinstance(cfg.storage, S3StorageConfig):
        for var in (cfg.storage.access_key_id_env, cfg.storage.secret_access_key_env):
            if not os.environ.get(var):
                add("error", f"storage: environment variable {var} is not set")
    if cfg.auth.proxy_secret_env is not None and not os.environ.get(cfg.auth.proxy_secret_env):
        add("error", f"auth: environment variable {cfg.auth.proxy_secret_env} is not set")
    for var in [cfg.worker.kick_token_env, *cfg.worker.extra_headers_env.values()]:
        if var and not os.environ.get(var):
            add("error", f"worker: environment variable {var} is not set")
    return issues


def _first_error(e: ValidationError) -> str:
    errors = e.errors()
    first = errors[0]
    where = ".".join(str(part) for part in first["loc"]) or "(top level)"
    return f"{where}: {first['msg']}{_more(len(errors) - 1)}"


def _more(count: int) -> str:
    return f" (and {count} more problem{'s' if count > 1 else ''})" if count else ""


def _resolve(base: Path, value: Path | None) -> Path | None:
    return None if value is None else (base / value).resolve()


def load_config(path: Path) -> tuple[CorelataConfig, list[ConfigIssue]]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping of sections")
    try:
        cfg = CorelataConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"{path}: {_first_error(e)}") from e
    # Relative paths are relative to the config file (spec §11).
    base = path.resolve().parent
    storage = cfg.storage
    if isinstance(storage, StorageConfig):
        storage = storage.model_copy(update={"path": (base / storage.path).resolve()})
    cfg = cfg.model_copy(
        update={
            "prompts_dir": _resolve(base, cfg.prompts_dir),
            "standards": cfg.standards.model_copy(
                update={"packs_dir": _resolve(base, cfg.standards.packs_dir)}
            ),
            "api": cfg.api.model_copy(update={"web_dir": _resolve(base, cfg.api.web_dir)}),
            "storage": storage,
        }
    )
    issues = validate_config(cfg)
    errors = [i.message for i in issues if i.level == "error"]
    if errors:
        raise ConfigError(f"{path}: {errors[0]}{_more(len(errors) - 1)}")
    return cfg, issues


# Operational sections: tuning the deployment never reads as a config change.
# `ingest` shapes sources, not runs: what OCR read is recorded on each source (CRL-95).
_OPERATIONAL_SECTIONS = {"database", "storage", "worker", "api", "auth", "integrations", "ingest"}
# What is kept of a model's reasoning is no output setting either (CRL-140).
_HASH_EXCLUDE: dict[str, Any] = {section: True for section in _OPERATIONAL_SECTIONS} | {
    "models": {"__all__": {"store_reasoning", "reasoning_max_chars"}}
}


def config_hash(cfg: CorelataConfig) -> str:
    """Identifies the settings that shape output; operational sections are excluded."""
    dump = cfg.model_dump_json(exclude=_HASH_EXCLUDE)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]
