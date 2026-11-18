# Corelata M1 (engine + CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `corelata run` takes source files plus a value statement and, against an OpenAI-compatible model (or the built-in fake), produces an ICD 203-shaped report, a Markdown render and a full trace JSON, through gate → writer → conveyor → auditor with one bounded loop.

**Architecture:** A single Python package `corelata` under `engine/`. Coglossa's foundation modules (config skeleton, LLM layer, prompt library, test fakes) are copied and renamed per spec §4.3. New modules: `standards/` (pack loader + ICD 203 base pack), `ingest/units.py` + `ingest/coglossa.py` (source units, Coglossa export adapter), `schema/` (report, gate, audit, digest, run record), `stages/` (one module per role), `pipeline.py` (state machine and loop), `render/markdown.py`, `cli.py`. No database, no API, no web in M1: `corelata run` executes in-process and writes a directory.

**Tech Stack:** Python 3.12+, uv, hatchling, pydantic v2, jinja2, httpx, pyyaml, python-docx, lxml, pdfminer.six; pytest, pytest-asyncio, pytest-cov, hypothesis, ruff.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (cite sections as §N in docstrings)

**Coglossa source for copied modules:** `$COGLOSSA`, which this plan assumes is `$HOME/Downloads/coglossa` (the private repo github.com/Bonham-Technologies/coglossa checked out at its current main). Every task that copies says exactly which files.

## Global Constraints

- `requires-python = ">=3.12"`; ruff `line-length = 100`, `target-version = "py312"`, `select = ["E", "F", "I", "B", "UP", "SIM"]` (spec §4.1, copied from Coglossa).
- pytest: `asyncio_mode = "auto"`, `filterwarnings = ["error"]`, `--cov=corelata --cov-branch --cov-fail-under=95` (spec §13).
- All config and pack models are strict pydantic: `model_config = ConfigDict(extra="forbid")` (spec §6, §11).
- Product name is parameterised: env prefix `CORELATA_`, entry-point group `corelata.backends`, config env `CORELATA_CONFIG` (spec §4.3 rule 1).
- Copied modules change only by rename and deletion. Every other change is recorded in `docs/m1-followups.md` under **Divergences from Coglossa** with a one-line reason; improvements worth sending back are tagged **backport** (spec §4.3 rules 2–3).
- The auditor's output type has no report field (spec §8.2, invariant 4).
- The engine never imports anything from Coglossa at runtime (spec §2.2, Coglossa hook row).
- API keys come from environment variables named in config, never from config values (spec §11).
- No model weights, no GPU code (spec §4.2).
- Commit after every task with a conventional-commit message; CI (`.github/workflows/ci.yml`, engine job) must be green before merge (user rule, 2026-10-12).

## Review Focus

1. **Empty or whitespace-only value statement.** `corelata run --statement "  "` must exit 2 with a usage message before any model call. Test in Task 16.
2. **Source with no usable text** (an HTML file of only navigation, a TXT of scene breaks). The run must stop at ingest with the file name in the error, never reach the gate. Test in Task 8 (registry) and Task 14 (pipeline refuses an empty source list).
3. **Two sources with the same file name.** Source ids must stay unique (`src1`, `src2`) and both appear in the report's sources section with distinct hash prefixes. Test in Task 9.
4. **Writer cites a unit ref that does not exist.** The semantic validator rejects it, the repair turn runs, and if the model persists the run ends `failed` with the `StructuredOutputError` text in the trace, not a traceback. Test in Task 12.
5. **A profile disables or overrides a rule id that does not exist**, or two packs in an `extends` chain define the same rule id. `load_pack` raises `PackError` naming the id. Test in Task 6.

---

## File structure

```
engine/
  pyproject.toml                       package metadata, pytest/ruff/coverage config
  corelata.example.yaml                documented example config
  corelata/
    __init__.py                        __version__
    text.py                            clean_text (copied)
    config.py                          CorelataConfig and sections (copied skeleton, new sections)
    schema/
      __init__.py                      re-exports
      common.py                        LLMCallRecord, Usage (copied from Coglossa schema/report.py)
      document.py                      Block, BlockKind, Provenance, SourceDocument (copied)
      source.py                        SourceKind, SourceUnit, Source, unit_ref/split_ref
      report.py                        Confidence, ClaimKind, Claim, ReportBody, Report, ReportStatus, ReportMetadata
      gate.py                          Substance, GateVerdict, CandidateStatement, DiscoveryResult
      digest.py                        DigestSection, DigestOutput, Digest
      audit.py                         Verdict, FindingOut, AuditOutput, Finding
      run.py                           RunState, StageResult, DraftRecord, RunRecord
      export.py                        JSON Schema export (copied pattern)
    llm/                               types, payload, retry, openai_compat, registry, agent (copied)
    prompts/
      library.py                       PromptLibrary (copied)
      check.py                         validate_prompts for Corelata roles
      templates/<role>/v1.j2           gate, discover, digest, writer, conveyor, auditor
    standards/
      schema.py                        Severity, Checkability, RouteTo, Rule, Template, Lexicon, Profile, PackMeta, ResolvedPack
      loader.py                        load_pack, validate_pack, pack_hash, PackError
      packs/icd203-base/               pack.yaml, template.yaml, lexicon.yaml, rules/*.yaml
    ingest/
      base.py, txt.py, markdown.py, docx.py, html.py, pdf.py   (copied)
      tabular.py                       JsonIngestor, CsvIngestor
      registry.py                      copied, minus epub, plus tabular
      units.py                         units_from_document, make_source, UnitIndex
      coglossa.py                      load_coglossa_export
      vendor/coglossa-report-1.schema.json
    stages/
      context.py                       StageContext, StageError, estimate_tokens, model_for
      digest.py                        run_digests
      gate.py                          run_gate, run_discovery, select_units
      write.py                         run_writer, report_validator
      convey.py                        run_conveyor
      audit.py                         run_auditor, decide_next
    pipeline.py                        RunOptions, run_report, discover
    render/markdown.py                 render_markdown
    cli.py                             run, discover, pack, fake-openai
    testing/
      synthetic.py                     deterministic responder per role
      fake_backend.py                  (copied)
      fake_openai.py                   (copied)
      pdf.py                           make_pdf (copied, tests only)
      sources.py                       text_source(): build a Source from strings for tests
  tests/                               mirrors corelata/
Makefile                               lint, fmt, test-engine, schema
.github/workflows/ci.yml               engine job
.gitignore
docs/m1-followups.md                   Divergences from Coglossa, Spec deviations, Later
```

---

### Task 1: Repository scaffold, package, lint and CI

**Files:**
- Create: `engine/pyproject.toml`, `engine/corelata/__init__.py`, `engine/corelata/text.py`, `engine/tests/__init__.py`, `engine/tests/test_version.py`, `engine/tests/test_text.py`, `Makefile`, `.gitignore`, `.github/workflows/ci.yml`, `docs/m1-followups.md`
- Copy: `$COGLOSSA/engine/coglossa/text.py` → `engine/corelata/text.py`

**Interfaces:**
- Produces: `corelata.__version__: str`, `corelata.text.clean_text(text: str) -> str`.

- [ ] **Step 1: Create the package files**

`engine/pyproject.toml`:

```toml
[project]
name = "corelata"
version = "0.1.0"
description = "Standards-enforced intelligence report production with a full trace"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.9,<3",
  "httpx>=0.27,<1",
  "pyyaml>=6.0",
  "jinja2>=3.1",
  "python-docx>=1.2,<2",
  "lxml>=5.2,<7",
  "pdfminer.six>=20240706",
]

[project.scripts]
corelata = "corelata.cli:main"

[project.entry-points."corelata.backends"]
[project.entry-points."corelata.ingestors"]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-cov>=5.0",
  "hypothesis>=6.112",
  "ruff>=0.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["corelata"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
filterwarnings = ["error"]
addopts = "--cov=corelata --cov-branch --cov-report=term-missing --cov-fail-under=95"

[tool.coverage.run]
branch = true
source = ["corelata"]

[tool.coverage.report]
exclude_also = [
  "if TYPE_CHECKING:",
  "if __name__ == .__main__.:",
  "^\\s*\\.\\.\\.$",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
```

`engine/corelata/__init__.py`:

```python
"""Corelata: standards-enforced intelligence report production with a full trace."""

__version__ = "0.1.0"
```

Copy and trim `text.py` (keep only `clean_text`; Coglossa's `clean_guide`/`_clean` are translation-specific):

```bash
COGLOSSA=$HOME/Downloads/coglossa
cp $COGLOSSA/engine/coglossa/text.py engine/corelata/text.py
```

Then edit `engine/corelata/text.py` so it reads exactly:

```python
"""Text that every layer can store and export: XML 1.0 (DOCX) and Postgres refuse some
characters that documents, model replies and pasted edits can carry."""

import re

_LINE_BREAKS = str.maketrans({"\x0b": "\n", "\x0c": "\n"})  # vertical tab, form feed
# NUL and the other C0 controls except tab, line feed and carriage return; the two
# non-characters U+FFFE and U+FFFF; lone surrogates.
_ILLEGAL = re.compile("[\x00-\x08\x0e-\x1f￾￿\ud800-\udfff]")


def clean_text(text: str) -> str:
    """`text` with vertical tabs and form feeds as line breaks and every character XML 1.0
    forbids removed; tabs, line feeds and carriage returns stay."""
    return _ILLEGAL.sub("", text.translate(_LINE_BREAKS))
```

`engine/tests/__init__.py`: empty file.

- [ ] **Step 2: Write the failing tests**

`engine/tests/test_version.py`:

```python
import tomllib
from pathlib import Path

import corelata


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert corelata.__version__ == pyproject["project"]["version"]
```

`engine/tests/test_text.py`:

```python
import pytest

from corelata.text import clean_text


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("plain", "plain"),
        ("a\x00b", "ab"),
        ("a\x0cb", "a\nb"),
        ("tab\tand\nnewline\r", "tab\tand\nnewline\r"),
        ("\ud800x", "x"),
    ],
)
def test_clean_text(raw, cleaned):
    assert clean_text(raw) == cleaned
```

- [ ] **Step 3: Install and run; verify the environment works**

```bash
cd engine && uv sync --all-groups && uv run pytest -p no:cacheprovider --no-cov -q
```

Expected: 6 passed.

- [ ] **Step 4: Makefile, .gitignore, CI, followups**

`Makefile` (repo root):

```make
.PHONY: test test-engine lint fmt schema

test: test-engine

test-engine:
	cd engine && uv run pytest

lint:
	cd engine && uv run ruff check . && uv run ruff format --check .

fmt:
	cd engine && uv run ruff format . && uv run ruff check --fix .

schema:
	cd engine && uv run python -m corelata.schema.export ../schema
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.coverage
coverage.xml
.pytest_cache/
.ruff_cache/
.hypothesis/
corelata-out/
dist/
```

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  engine:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: engine
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

`docs/m1-followups.md`:

```markdown
# M1 follow-ups

## Divergences from Coglossa

- `text.py`: dropped `clean_guide`/`_clean` (translation-guide specific).

## Spec deviations

(none yet)

## Should fix soon

(none yet)

## Later

(none yet)
```

- [ ] **Step 5: Lint, test, commit**

```bash
make lint && make test-engine
git add -A && git commit -m "feat(engine): package scaffold, clean_text, CI"
```

Expected: ruff clean; pytest passes with coverage ≥ 95% (only `text.py` and `__init__.py` are measured).

---

### Task 2: Configuration (`config.py`)

**Files:**
- Create: `engine/corelata/config.py`, `engine/tests/conftest.py`, `engine/tests/test_config.py`
- Copy from: `$COGLOSSA/engine/coglossa/config.py` (structure and helpers)

**Interfaces:**
- Produces: `CorelataConfig`, `BackendConfig`, `ModelConfig`, `RoleConfig`, `RolesConfig` (fields `gate`, `writer`, `conveyor`, `auditor`, `profiler: RoleConfig | None`; method `all_roles() -> list[tuple[str, str]]`), `RetryConfig`, `StandardsConfig(packs_dir: Path | None, default_pack: str, default_profile: str | None)`, `PipelineConfig(max_iterations: int, digest_threshold_tokens: int, gate_unit_budget_tokens: int)`, `AuditConfig`, `DatabaseConfig`, `StorageConfig`, `WorkerConfig`, `ApiConfig`, `AuthConfig`, `CoglossaIntegration`, `IntegrationsConfig`, `StructuredOutput`, `ConfigError`, `ConfigIssue`, `validate_config(cfg) -> list[ConfigIssue]`, `load_config(path) -> tuple[CorelataConfig, list[ConfigIssue]]`, `config_hash(cfg) -> str`, `default_config_path() -> Path`, `CONFIG_ENV = "CORELATA_CONFIG"`.
- Test helpers: `tests.conftest.BASE_CONFIG`, fixture `make_config(**overrides) -> CorelataConfig`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/conftest.py` (first version; later tasks extend it):

```python
import pytest

from corelata.config import CorelataConfig

BASE_CONFIG: dict = {
    "backends": {"fake": {"base_url": "http://127.0.0.1:9/v1", "max_concurrency": 4}},
    "models": {
        "model-a": {"backend": "fake", "context_window": 32768},
        "model-b": {"backend": "fake", "context_window": 32768},
    },
    "roles": {
        "gate": {"model": "model-a"},
        "writer": {"model": "model-a"},
        "conveyor": {"model": "model-b"},
        "auditor": {"model": "model-b"},
    },
    "retry": {"max_attempts": 3, "base_delay_s": 0.01, "max_delay_s": 0.02},
}


def build_config(**overrides) -> CorelataConfig:
    return CorelataConfig.model_validate({**BASE_CONFIG, **overrides})


@pytest.fixture
def make_config():
    return build_config
```

`engine/tests/test_config.py`:

```python
from pathlib import Path

import pytest
import yaml

from corelata.config import (
    CONFIG_ENV,
    ConfigError,
    StructuredOutput,
    config_hash,
    default_config_path,
    load_config,
    validate_config,
)
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
    b = make_config(api={"web_dir": None}, worker={"concurrency": 7}, auth={"mode": "none"})
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


def test_auth_header_must_be_http_token(make_config):
    with pytest.raises(ValueError, match="HTTP header name"):
        make_config(auth={"mode": "trusted_header", "header": "bad header"})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/test_config.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.config'`

- [ ] **Step 3: Write `config.py`**

Start from Coglossa's file to keep helper code identical, then replace the sections:

```bash
cp $COGLOSSA/engine/coglossa/config.py engine/corelata/config.py
perl -pi -e 's/coglossa/corelata/g; s/Coglossa/Corelata/g; s/COGLOSSA/CORELATA/g' engine/corelata/config.py
```

Now edit it to exactly this content (keep `_Strict`, `BackendConfig`, `ModelConfig`, `RoleConfig`, `RetryConfig`, `DatabaseConfig`, `StorageConfig`, `ApiConfig`, `AuthConfig`, `ConfigIssue`, `_first_error`, `_more`, the YAML-loading part of `load_config` and `config_hash` as copied; delete `TranslatorConfig`, `ChunkingConfig`, `ProfilesConfig`, `ScorerConfig`, `SignalWeights`, `ThresholdsConfig`, `ScoringConfig` and their defaults; replace `RolesConfig`, `WorkerConfig`, `CorelataConfig`, `validate_config` and the path-resolution part of `load_config`):

```python
"""corelata.yaml: the single file that adapts Corelata to a deployment (spec §11)."""

import hashlib
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


class BackendConfig(_Strict):
    kind: str = "openai_compat"
    base_url: str
    api_key_env: str | None = None
    max_concurrency: int = Field(4, ge=1)
    timeout_s: float = Field(120.0, gt=0)


class ModelConfig(_Strict):
    backend: str
    name: str | None = None  # model id sent to the server; defaults to the config key
    context_window: int = Field(ge=2048)
    structured_output: StructuredOutput = StructuredOutput.JSON_SCHEMA
    bytes_per_token: float = Field(2.5, gt=0)  # conservative UTF-8 bytes per token estimate
    max_output_tokens: int | None = Field(None, ge=1)
    temperature: float = Field(0.2, ge=0)


class RoleConfig(_Strict):
    model: str


class RolesConfig(_Strict):
    """Spec §4.4: one model per role. `profiler` is only used by `corelata profile extract`."""

    gate: RoleConfig
    writer: RoleConfig
    conveyor: RoleConfig
    auditor: RoleConfig
    profiler: RoleConfig | None = None

    def all_roles(self) -> list[tuple[str, str]]:
        roles = [
            ("gate", self.gate.model),
            ("writer", self.writer.model),
            ("conveyor", self.conveyor.model),
            ("auditor", self.auditor.model),
        ]
        if self.profiler is not None:
            roles.append(("profiler", self.profiler.model))
        return roles

    def model_for(self, role: str) -> str:
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


class PipelineConfig(_Strict):
    """Spec §7.2 and §7.4."""

    max_iterations: int = Field(2, ge=0, le=10)
    digest_threshold_tokens: int = Field(6000, ge=500)
    gate_unit_budget_tokens: int = Field(12000, ge=500)


class AuditConfig(_Strict):
    store_llm_io: bool = True


class DatabaseConfig(_Strict):
    url_env: str = "CORELATA_DATABASE_URL"  # env var holding postgresql://user:pass@host:port/db

    def url(self) -> str | None:
        return os.environ.get(self.url_env) or None


class StorageConfig(_Strict):
    kind: Literal["local"] = "local"
    path: Path = Path("/data/files")


class WorkerConfig(_Strict):
    concurrency: int = Field(2, ge=1)  # runs one worker process executes at the same time
    # re-queue jobs of a worker silent this long; a run is minutes, not hours (spec §16)
    stalled_after_s: float = Field(900.0, ge=30)


class ApiConfig(_Strict):
    max_upload_mb: int = Field(200, ge=1)
    progress_poll_s: float = Field(1.0, gt=0, le=60)
    web_dir: Path | None = None


_HTTP_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


class AuthConfig(_Strict):
    """Spec §10.1. `none`: anyone who reaches the API may use it. `trusted_header`: a reverse
    proxy authenticates people and passes the user name in `header`."""

    mode: Literal["none", "trusted_header"] = "none"
    header: str = "X-Remote-User"

    @field_validator("header")
    @classmethod
    def _http_token(cls, value: str) -> str:
        if not _HTTP_TOKEN.fullmatch(value):
            raise ValueError(
                "must be an HTTP header name: letters, digits and !#$%&'*+-.^_`|~, without "
                "spaces (e.g. X-Remote-User)"
            )
        return value


class CoglossaIntegration(_Strict):
    """Spec §5.3: fetch a Coglossa run export by id instead of uploading it."""

    base_url: str
    api_key_env: str | None = None


class IntegrationsConfig(_Strict):
    coglossa: CoglossaIntegration | None = None


class CorelataConfig(_Strict):
    backends: dict[str, BackendConfig]
    models: dict[str, ModelConfig]
    roles: RolesConfig
    retry: RetryConfig = Field(default_factory=RetryConfig)
    standards: StandardsConfig = Field(default_factory=StandardsConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    prompts_dir: Path | None = None
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)

    @field_validator(
        "standards", "pipeline", "database", "storage", "worker", "api", "auth", "integrations",
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
    if coglossa is not None and coglossa.api_key_env and os.environ.get(coglossa.api_key_env) is None:
        add("error", f"integrations.coglossa: environment variable {coglossa.api_key_env} is not set")
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
    cfg = cfg.model_copy(
        update={
            "prompts_dir": _resolve(base, cfg.prompts_dir),
            "standards": cfg.standards.model_copy(
                update={"packs_dir": _resolve(base, cfg.standards.packs_dir)}
            ),
            "api": cfg.api.model_copy(update={"web_dir": _resolve(base, cfg.api.web_dir)}),
            "storage": cfg.storage.model_copy(update={"path": (base / cfg.storage.path).resolve()}),
        }
    )
    issues = validate_config(cfg)
    errors = [i.message for i in issues if i.level == "error"]
    if errors:
        raise ConfigError(f"{path}: {errors[0]}{_more(len(errors) - 1)}")
    return cfg, issues


# Operational sections: tuning the deployment never reads as a config change.
_OPERATIONAL_SECTIONS = {"database", "storage", "worker", "api", "auth", "integrations"}


def config_hash(cfg: CorelataConfig) -> str:
    """Identifies the settings that shape output; operational sections are excluded."""
    dump = cfg.model_dump_json(exclude=_OPERATIONAL_SECTIONS)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests**

Run: `cd engine && uv run pytest tests/test_config.py -q --no-cov`
Expected: all pass. If `test_load_errors_are_one_line` fails because pydantic reports only one error for `models: {}`, the role-reference errors come from `validate_config`, which produces four (one per role); the message must contain "and 3 more problems".

- [ ] **Step 5: Record divergences, lint, commit**

Append to `docs/m1-followups.md` under Divergences: `config.py: RolesConfig has fixed roles gate/writer/conveyor/auditor/profiler and a model_for() helper; added StandardsConfig, PipelineConfig, IntegrationsConfig; dropped chunking/profiles/scorer/scoring; WorkerConfig defaults 2 / 900 s and no scorer_wait_s; _resolve() helper replaces the repeated model_copy blocks (backport).`

```bash
make lint && make test-engine
git add -A && git commit -m "feat(config): corelata.yaml sections, validation, hash"
```

---

### Task 3: LLM layer (copied) and `schema/common.py`

**Files:**
- Copy: `$COGLOSSA/engine/coglossa/llm/{__init__,types,payload,retry,openai_compat,registry,agent}.py` → `engine/corelata/llm/`
- Copy tests: `$COGLOSSA/engine/tests/llm/{__init__,test_retry,test_openai_compat,test_registry}.py` → `engine/tests/llm/`
- Create: `engine/corelata/schema/__init__.py`, `engine/corelata/schema/common.py`, `engine/tests/llm/test_agent.py`, `engine/tests/schema/__init__.py`
- Modify: `engine/tests/conftest.py`

**Interfaces:**
- Produces (unchanged from Coglossa apart from the package name): `corelata.llm.types.{Backend, ChatMessage, ChatRequest, ChatResponse, BackendError, TransientBackendError, PermanentBackendError, ContextOverflowError, OutputTruncatedError, OVERSIZE_ERRORS}`; `corelata.llm.payload.{render_input, parse_input, INPUT_MARKER}`; `corelata.llm.retry.{RetryPolicy, call_with_retry}`; `corelata.llm.openai_compat.OpenAICompatBackend`; `corelata.llm.registry.{build_backends, available_kinds}`; `corelata.llm.agent.{AgentRunner, CallLog, StructuredOutputError, AGENT_FAILURES, extract_json}` with `AgentRunner.run(*, role, model_key, prompt_id, prompt_vars, payload, output_type, validate=None)`.
- Produces: `corelata.schema.common.{LLMCallRecord, Usage}` (fields exactly as Coglossa's `schema/report.py`).
- Consumes: `corelata.config` (Task 2); `corelata.prompts.library.PromptLibrary` (Task 4; this task's tests need a prompt, so Task 4's `library.py` copy happens here too, see Step 3).

- [ ] **Step 1: Copy the modules and rename**

```bash
COGLOSSA=$HOME/Downloads/coglossa
mkdir -p engine/corelata/llm engine/corelata/prompts engine/corelata/schema engine/tests/llm engine/tests/schema
for f in __init__ types payload retry openai_compat registry agent; do
  cp $COGLOSSA/engine/coglossa/llm/$f.py engine/corelata/llm/$f.py
done
cp $COGLOSSA/engine/coglossa/prompts/__init__.py engine/corelata/prompts/__init__.py
cp $COGLOSSA/engine/coglossa/prompts/library.py engine/corelata/prompts/library.py
for f in __init__ test_retry test_openai_compat test_registry; do
  cp $COGLOSSA/engine/tests/llm/$f.py engine/tests/llm/$f.py
done
touch engine/tests/schema/__init__.py
perl -pi -e 's/coglossa/corelata/g; s/Coglossa/Corelata/g; s/COGLOSSA/CORELATA/g' \
  engine/corelata/llm/*.py engine/corelata/prompts/*.py engine/tests/llm/*.py
grep -rn "coglossa" engine/corelata/llm engine/corelata/prompts engine/tests/llm && echo "RENAME INCOMPLETE" || echo "rename ok"
```

`registry.py` after rename reads the entry-point group `corelata.backends` and `types.py` imports `from corelata.config import StructuredOutput`; both are correct as copied. `agent.py` imports `from corelata.schema import LLMCallRecord, Usage`, which Step 2 provides.

- [ ] **Step 2: Create `schema/common.py` and `schema/__init__.py`**

`engine/corelata/schema/common.py`:

```python
"""Records every layer shares: one model call, and usage totals (copied from Coglossa)."""

from typing import Any

from pydantic import BaseModel


class LLMCallRecord(BaseModel):
    role: str
    backend: str
    model: str
    prompt_id: str
    prompt_version: int
    attempt: int
    ok: bool
    latency_ms: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    request: dict[str, Any] | None = None  # only when audit.store_llm_io
    response: str | None = None  # only when audit.store_llm_io


class Usage(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    by_role: dict[str, dict[str, int]]
```

`engine/corelata/schema/__init__.py` (first version; later tasks add exports):

```python
"""Canonical data contracts. JSON Schema is exported from these models (see export.py)."""

from corelata.schema.common import LLMCallRecord, Usage

__all__ = ["LLMCallRecord", "Usage"]
```

- [ ] **Step 3: Extend `conftest.py` and write the agent test**

Add to `engine/tests/conftest.py` (keep the existing content):

```python
from corelata.llm.agent import AgentRunner, CallLog
from corelata.prompts.library import PromptLibrary
from corelata.testing.fake_backend import FakeBackend


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend(name="fake")


@pytest.fixture
def make_runner(make_config, fake_backend):
    def _make(cfg: CorelataConfig | None = None, *, store_io: bool = True) -> AgentRunner:
        cfg = cfg or make_config()
        return AgentRunner(
            cfg,
            {"fake": fake_backend},
            PromptLibrary(cfg.prompts_dir),
            CallLog(store_io=store_io),
            sleep=_no_sleep,
        )

    return _make
```

`FakeBackend` does not exist yet; Task 4 creates it. To keep this task green on its own, create the minimal `engine/corelata/testing/__init__.py` (empty), `engine/corelata/testing/synthetic.py` and `engine/corelata/testing/fake_backend.py` now, exactly as Task 4 Step 1 specifies for the copy of `fake_backend.py`, and this first version of `synthetic.py`:

```python
"""Deterministic stand-in for a model: valid output for every agent task, no intelligence.
Task 10 fills in the role handlers."""

from collections.abc import Callable
from typing import Any

Payload = dict[str, Any]


def _ok(p: Payload) -> Payload:
    return {"ok": True}


_HANDLERS: dict[str, Callable[[Payload], Payload]] = {"ping": _ok}


def synthetic_response(payload: Payload) -> Payload:
    handler = _HANDLERS.get(payload.get("task", ""))
    if handler is None:
        raise ValueError(f"unknown task '{payload.get('task')}'")
    return handler(payload)


def chat_completion(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }
```

Create a test-only prompt so the agent test has a template: `engine/corelata/prompts/templates/ping/v1.j2`:

```
You are a connectivity probe for {{ product }}. INPUT_JSON carries a task. Respond with a single JSON object only.
```

`engine/tests/llm/test_agent.py`:

```python
import json

import pytest
from pydantic import BaseModel

from corelata.llm.agent import StructuredOutputError, extract_json
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
        "gate", "fake", "model-a", "ping", 1
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
    assert "invalid" in repair[3].content


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
```

- [ ] **Step 4: Run the whole llm test directory**

Run: `cd engine && uv run pytest tests/llm -q --no-cov`
Expected: all pass. The copied `test_registry.py` and `test_openai_compat.py` use only `make_config` and the backend classes; `test_retry.py` is self-contained.

- [ ] **Step 5: Lint, record, commit**

Append to Divergences in `docs/m1-followups.md`: `llm/: copied unchanged (rename only). prompts/library.py: copied unchanged. schema/common.py: LLMCallRecord and Usage lifted out of Coglossa's schema/report.py so the LLM layer does not depend on the report schema (backport candidate).`

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(llm): copy Coglossa LLM layer, prompt library and call records"
```

Coverage note: the full run now includes `llm/` and `prompts/library.py`. The copied tests covered Coglossa's versions at ≥95%; if the total dips because `testing/` is measured, add `--cov-report` inspection and confirm the gap is only in `fake_backend.py`'s `list_models`/`aclose`, which Task 4's tests cover.

---

### Task 4: Test fakes (copied) and the fake OpenAI server

**Files:**
- Copy: `$COGLOSSA/engine/coglossa/testing/{fake_backend,fake_openai,pdf}.py` → `engine/corelata/testing/`
- Copy tests: `$COGLOSSA/engine/tests/testing/` test files for `fake_openai` and `fake_backend` if present (check with `ls $COGLOSSA/engine/tests/testing`); otherwise create `engine/tests/testing/test_fakes.py` below.
- Create: `engine/tests/testing/__init__.py`, `engine/tests/testing/test_fakes.py`

**Interfaces:**
- Produces: `corelata.testing.fake_backend.FakeBackend(name="fake", models=("fake-model",))` with `.script(task, *items)`, `.requests`, `.closed`; `corelata.testing.fake_openai.FakeOpenAIServer(host, port, models, context_window=None, delay_s=0.0, keep_requests=True)` with `.start()`, `.stop()`, `.base_url`, `.requests`, `.max_in_flight`, `.serve_forever()`, context-manager support; `corelata.testing.pdf.make_pdf(pages) -> bytes`.

- [ ] **Step 1: Copy and rename**

```bash
for f in fake_backend fake_openai pdf; do
  cp $COGLOSSA/engine/coglossa/testing/$f.py engine/corelata/testing/$f.py
done
perl -pi -e 's/coglossa/corelata/g; s/Coglossa/Corelata/g; s/COGLOSSA/CORELATA/g' engine/corelata/testing/*.py
mkdir -p engine/tests/testing && touch engine/tests/testing/__init__.py
ls $COGLOSSA/engine/tests/testing
```

If `$COGLOSSA/engine/tests/testing` has `test_fake_openai.py` or similar, copy and rename them the same way and adapt any translation-specific payloads (`"task": "profile"` etc.) to `{"task": "ping"}`. Otherwise write Step 2's file.

- [ ] **Step 2: Write the tests**

`engine/tests/testing/test_fakes.py`:

```python
import json

import httpx
import pytest

from corelata.llm.openai_compat import OpenAICompatBackend
from corelata.llm.payload import render_input
from corelata.llm.types import ChatMessage, ChatRequest, ContextOverflowError, OutputTruncatedError
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.testing.pdf import make_pdf
from corelata.testing.synthetic import synthetic_response


def _request(payload: dict, **kw) -> ChatRequest:
    return ChatRequest(
        model="fake-model",
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content=render_input(payload)),
        ],
        schema_name="X",
        json_schema={},
        structured_output="json_schema",
        **kw,
    )


async def test_fake_backend_scripts_then_synthesises():
    backend = FakeBackend()
    backend.script("ping", '{"ok": false}')
    first = await backend.chat(_request({"task": "ping"}))
    second = await backend.chat(_request({"task": "ping"}))
    assert json.loads(first.content) == {"ok": False}
    assert json.loads(second.content) == {"ok": True}
    assert await backend.list_models() == ["fake-model"]
    await backend.aclose()
    assert backend.closed


def test_synthetic_unknown_task():
    with pytest.raises(ValueError, match="unknown task 'nope'"):
        synthetic_response({"task": "nope"})


async def test_fake_openai_serves_models_and_chat():
    with FakeOpenAIServer(models=("m1", "m2")) as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        assert await backend.list_models() == ["m1", "m2"]
        resp = await backend.chat(_request({"task": "ping"}))
        assert json.loads(resp.content) == {"ok": True}
        assert resp.tokens_in == 10
        assert server.requests[0]["model"] == "fake-model"
        await backend.aclose()


async def test_fake_openai_context_window_and_truncation():
    with FakeOpenAIServer(context_window=10) as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        with pytest.raises(ContextOverflowError):
            await backend.chat(_request({"task": "ping", "pad": "x" * 100}))
        await backend.aclose()
    with FakeOpenAIServer() as server:
        backend = OpenAICompatBackend("fake", server.base_url)
        with pytest.raises(OutputTruncatedError):
            await backend.chat(_request({"task": "ping"}, max_tokens=1))
        await backend.aclose()


async def test_fake_openai_unknown_routes_and_bad_payload():
    with FakeOpenAIServer() as server:
        async with httpx.AsyncClient(base_url=server.base_url) as client:
            assert (await client.get("/nope")).status_code == 404
            assert (await client.post("/nope", json={})).status_code == 404
            bad = await client.post(
                "/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
            )
            assert bad.status_code == 400


def test_make_pdf_produces_pdf_bytes():
    data = make_pdf([["Hello world."], "Second page."])
    assert data.startswith(b"%PDF")
```

- [ ] **Step 3: Run**

Run: `cd engine && uv run pytest tests/testing -q --no-cov`
Expected: all pass.

- [ ] **Step 4: Lint, record, commit**

Append to Divergences: `testing/fake_backend.py, fake_openai.py, pdf.py: copied unchanged (rename only). testing/synthetic.py: rewritten for Corelata's roles (Task 10).`

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(testing): fake backend, fake OpenAI server, PDF fixture helper"
```

---

### Task 5: Report, gate, digest, audit and run schemas

**Files:**
- Create: `engine/corelata/schema/source.py`, `engine/corelata/schema/report.py`, `engine/corelata/schema/gate.py`, `engine/corelata/schema/digest.py`, `engine/corelata/schema/audit.py`, `engine/corelata/schema/run.py`, `engine/corelata/schema/document.py`
- Copy: `$COGLOSSA/engine/coglossa/schema/document.py` → `engine/corelata/schema/document.py` (drop `Segment`, `Chunk`)
- Modify: `engine/corelata/schema/__init__.py`
- Test: `engine/tests/schema/test_report.py`, `engine/tests/schema/test_source.py`, `engine/tests/schema/test_run.py`

**Interfaces (spec §8):**
- `schema.document`: `BlockKind`, `Provenance`, `Block`, `SourceDocument` (as Coglossa).
- `schema.source`: `SourceKind(StrEnum) FILE|COGLOSSA_EXPORT`; `SourceUnit(id, text, locator, kind: BlockKind, meta: dict)`; `Source(id, kind, name, format, sha256, provenance: dict, units: list[SourceUnit])`; `unit_ref(source_id, unit_id) -> str` (`"src1/u3"`); `split_ref(ref) -> tuple[str, str]` raising `ValueError` on malformed refs.
- `schema.report`: `Confidence HIGH|MODERATE|LOW`; `ClaimKind FACT|JUDGMENT|ASSUMPTION`; `Claim(id, text, kind, evidence: list[str], likelihood_term: str | None)`; `KeyJudgment(text, confidence, claim_ids)`; `SourceEntry(source_id, descriptor, reliability_note="")`; `Paragraph(text, claim_ids=[])`; `Section(heading, paragraphs)`; `Alternative(hypothesis, assessment, claim_ids=[])`; `ReportBody(title, handling_marking, key_judgments, scope_note, sources, analysis, alternatives, gaps_and_indicators, claims)` with a model validator that every referenced `claim_id` exists and claim ids are unique; `ReportStatus CLEAN|FINDINGS_OPEN`; `ReportMetadata(run_id, pack_name, pack_hash, profile, iteration, status, open_findings)`; `Report(ReportBody)` adding `metadata: ReportMetadata`; `ReportBody.referenced_claim_ids() -> set[str]`; `ReportBody.unsourced_claims() -> list[Claim]`.
- `schema.gate`: `Substance SUFFICIENT|THIN|INSUFFICIENT`; `GateVerdict(supported: bool, substance, reasons: list[str], evidence: list[str], suggested_scope: str = "")`; `CandidateStatement(text, audience, evidence, confidence_note="")`; `DiscoveryResult(candidates: list[CandidateStatement])` (max 5, validated).
- `schema.digest`: `DigestSection(summary, unit_refs)`; `DigestOutput(sections)`; `Digest(source_id, sections)`.
- `schema.audit`: `Verdict PASS|FAIL|NOT_APPLICABLE|ATTESTED`; `FindingOut(rule_id, verdict, evidence: str, cited_units=[], claim_ids=[], recommendation="")`; `AuditOutput(findings: list[FindingOut], summary: str)`; `Finding(FindingOut)` adding `severity: str`, `route_to: str`, `iteration: int`; `Finding.id` property `f"{rule_id}@{iteration}"`.
- `schema.run`: `RunState` (CREATED, INGESTING, GATING, DRAFTING, CONVEYING, AUDITING, RENDERING, COMPLETED, GATE_REJECTED, FAILED, CANCELLED); `TERMINAL_STATES`; `StageResult(stage, iteration, ok, output: dict | None, error: str | None, started_at, finished_at)`; `DraftRecord(role, iteration, report: ReportBody)`; `RunRecord` (fields listed in Step 3).

- [ ] **Step 1: Write the failing tests**

`engine/tests/schema/test_source.py`:

```python
import pytest

from corelata.schema import BlockKind, Source, SourceKind, SourceUnit, split_ref, unit_ref


def test_unit_ref_roundtrip():
    assert unit_ref("src1", "u3") == "src1/u3"
    assert split_ref("src1/u3") == ("src1", "u3")


@pytest.mark.parametrize("bad", ["u3", "src1/", "/u3", "a/b/c", ""])
def test_split_ref_rejects_malformed(bad):
    with pytest.raises(ValueError, match="unit ref"):
        split_ref(bad)


def test_source_refs():
    src = Source(
        id="src1", kind=SourceKind.FILE, name="a.txt", format="txt", sha256="00",
        units=[SourceUnit(id="u1", text="x", locator="para 1", kind=BlockKind.PARAGRAPH)],
    )
    assert src.refs() == ["src1/u1"]
```

`engine/tests/schema/test_report.py`:

```python
import pytest
from pydantic import ValidationError

from corelata.schema import (
    Alternative, Claim, ClaimKind, Confidence, DiscoveryResult, Finding, FindingOut,
    KeyJudgment, Paragraph, Report, ReportBody, ReportMetadata, Section, SourceEntry, Verdict,
)


def body(**overrides) -> ReportBody:
    data = dict(
        title="T",
        handling_marking="UNCLASSIFIED",
        key_judgments=[KeyJudgment(text="KJ", confidence=Confidence.MODERATE, claim_ids=["c1"])],
        scope_note="scope",
        sources=[SourceEntry(source_id="src1", descriptor="open-source report")],
        analysis=[Section(heading="A", paragraphs=[Paragraph(text="p", claim_ids=["c1"])])],
        alternatives=[Alternative(hypothesis="h", assessment="a")],
        gaps_and_indicators=["gap"],
        claims=[Claim(id="c1", text="claim", kind=ClaimKind.JUDGMENT, evidence=["src1/u1"])],
    )
    data.update(overrides)
    return ReportBody(**data)


def test_valid_body():
    b = body()
    assert b.referenced_claim_ids() == {"c1"}
    assert b.unsourced_claims() == []


def test_unknown_claim_id_rejected():
    with pytest.raises(ValidationError, match="unknown claim id 'c9'"):
        body(key_judgments=[KeyJudgment(text="x", confidence=Confidence.LOW, claim_ids=["c9"])])


def test_duplicate_claim_ids_rejected():
    claims = [
        Claim(id="c1", text="a", kind=ClaimKind.FACT, evidence=["src1/u1"]),
        Claim(id="c1", text="b", kind=ClaimKind.FACT, evidence=["src1/u1"]),
    ]
    with pytest.raises(ValidationError, match="duplicate claim id 'c1'"):
        body(claims=claims)


def test_unsourced_claims_listed():
    b = body(claims=[Claim(id="c1", text="x", kind=ClaimKind.FACT, evidence=[])])
    assert [c.id for c in b.unsourced_claims()] == ["c1"]


def test_report_wraps_body_with_metadata():
    r = Report(**body().model_dump(), metadata=ReportMetadata(pack_name="p", pack_hash="h"))
    assert r.metadata.iteration == 0 and r.metadata.status is None


def test_discovery_max_five():
    cands = [{"text": f"c{i}", "audience": "a", "evidence": ["src1/u1"]} for i in range(6)]
    with pytest.raises(ValidationError):
        DiscoveryResult(candidates=cands)


def test_finding_id_and_output_has_no_report_field():
    f = Finding(
        **FindingOut(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="e").model_dump(),
        severity="blocking", route_to="writer", iteration=1,
    )
    assert f.id == "icd203.tc.8@1"
    assert "report" not in FindingOut.model_fields and "report" not in Finding.model_fields
```

`engine/tests/schema/test_run.py`:

```python
from datetime import UTC, datetime

from corelata.schema import TERMINAL_STATES, RunRecord, RunState, Usage


def test_run_record_minimal():
    rec = RunRecord(
        corelata_version="0.1.0",
        run_id="abc",
        created_at=datetime.now(UTC),
        value_statement="v",
        pack_name="icd203-base",
        pack_hash="h",
        pack_snapshot={},
        config_hash="c",
        prompt_versions={},
        max_iterations=2,
        usage=Usage(calls=0, tokens_in=0, tokens_out=0, by_role={}),
    )
    assert rec.state is RunState.CREATED and rec.report is None and rec.iterations == 0
    assert RunState.COMPLETED in TERMINAL_STATES and RunState.AUDITING not in TERMINAL_STATES
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/schema -q --no-cov`
Expected: ImportError on the new names.

- [ ] **Step 3: Write the schema modules**

Copy `document.py` and delete `Segment` and `Chunk`:

```bash
cp $COGLOSSA/engine/coglossa/schema/document.py engine/corelata/schema/document.py
```

Edit so only `BlockKind`, `Provenance`, `Block`, `SourceDocument` remain (docstring: `"""Source documents after ingestion (copied from Coglossa; segmentation dropped)."""`).

`engine/corelata/schema/source.py`:

```python
"""Sources and their addressable units (spec §5.2). A unit ref is "<source_id>/<unit_id>"."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from corelata.schema.document import BlockKind


class SourceKind(StrEnum):
    FILE = "file"
    COGLOSSA_EXPORT = "coglossa_export"


class SourceUnit(BaseModel):
    id: str  # "u1", "u2", … in reading order, scoped to the source
    text: str
    locator: str  # "page 3 / para 7", "row 42", "coglossa:<run_id>/span:p14"
    kind: BlockKind
    meta: dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    id: str  # "src1", "src2", … in upload order
    kind: SourceKind
    name: str  # file name as uploaded
    format: str
    sha256: str
    provenance: dict[str, Any] = Field(default_factory=dict)  # e.g. {"coglossa_run_id": ...}
    units: list[SourceUnit]

    def refs(self) -> list[str]:
        return [unit_ref(self.id, u.id) for u in self.units]


def unit_ref(source_id: str, unit_id: str) -> str:
    return f"{source_id}/{unit_id}"


def split_ref(ref: str) -> tuple[str, str]:
    parts = ref.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"malformed unit ref '{ref}' (expected <source_id>/<unit_id>)")
    return parts[0], parts[1]
```

`engine/corelata/schema/report.py`:

```python
"""The report is structured, never free prose, so every assertion is addressable (spec §8.1)."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Confidence(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class ClaimKind(StrEnum):
    FACT = "fact"
    JUDGMENT = "judgment"
    ASSUMPTION = "assumption"


class Claim(BaseModel):
    id: str = Field(description="Short id such as c1; unique within the report")
    text: str
    kind: ClaimKind
    evidence: list[str] = Field(
        default_factory=list, description="Unit refs (<source_id>/<unit_id>) the claim rests on"
    )
    likelihood_term: str | None = Field(
        None, description="For judgments: the estimative term used, from the lexicon"
    )


class KeyJudgment(BaseModel):
    text: str
    confidence: Confidence
    claim_ids: list[str]


class SourceEntry(BaseModel):
    source_id: str
    descriptor: str = Field(description="A source descriptor phrase from the lexicon")
    reliability_note: str = ""


class Paragraph(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class Section(BaseModel):
    heading: str
    paragraphs: list[Paragraph]


class Alternative(BaseModel):
    hypothesis: str
    assessment: str
    claim_ids: list[str] = Field(default_factory=list)


class ReportBody(BaseModel):
    """What the writer and conveyor produce. `Report` adds engine-owned metadata."""

    title: str
    handling_marking: str
    key_judgments: list[KeyJudgment]
    scope_note: str
    sources: list[SourceEntry]
    analysis: list[Section]
    alternatives: list[Alternative]
    gaps_and_indicators: list[str]
    claims: list[Claim]

    @model_validator(mode="after")
    def _claim_ids_resolve(self) -> "ReportBody":
        seen: set[str] = set()
        for c in self.claims:
            if c.id in seen:
                raise ValueError(f"duplicate claim id '{c.id}'")
            seen.add(c.id)
        for cid in sorted(self.referenced_claim_ids()):
            if cid not in seen:
                raise ValueError(f"unknown claim id '{cid}'")
        return self

    def referenced_claim_ids(self) -> set[str]:
        ids: set[str] = set()
        for kj in self.key_judgments:
            ids.update(kj.claim_ids)
        for section in self.analysis:
            for p in section.paragraphs:
                ids.update(p.claim_ids)
        for alt in self.alternatives:
            ids.update(alt.claim_ids)
        return ids

    def unsourced_claims(self) -> list[Claim]:
        return [c for c in self.claims if not c.evidence]


class ReportStatus(StrEnum):
    CLEAN = "clean"
    FINDINGS_OPEN = "findings_open"


class ReportMetadata(BaseModel):
    run_id: str | None = None
    pack_name: str
    pack_hash: str
    profile: str | None = None
    iteration: int = 0
    status: ReportStatus | None = None
    open_findings: list[str] = Field(default_factory=list)  # Finding ids


class Report(ReportBody):
    metadata: ReportMetadata
```

`engine/corelata/schema/gate.py`:

```python
"""Gate outputs (spec §7.1, §7.2)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Substance(StrEnum):
    SUFFICIENT = "sufficient"
    THIN = "thin"
    INSUFFICIENT = "insufficient"


class GateVerdict(BaseModel):
    supported: bool = Field(description="The sources support the value statement")
    substance: Substance
    reasons: list[str] = Field(description="One sentence each; what supports or undermines")
    evidence: list[str] = Field(default_factory=list, description="Unit refs that matter most")
    suggested_scope: str = Field("", description="A scope note the writer must include if thin")


class CandidateStatement(BaseModel):
    text: str
    audience: str
    evidence: list[str] = Field(default_factory=list)
    confidence_note: str = ""


class DiscoveryResult(BaseModel):
    candidates: list[CandidateStatement] = Field(max_length=5)
```

`engine/corelata/schema/digest.py`:

```python
"""Digests of oversized sources (spec §5.4)."""

from pydantic import BaseModel, Field


class DigestSection(BaseModel):
    summary: str
    unit_refs: list[str] = Field(description="The units this section covers")


class DigestOutput(BaseModel):
    sections: list[DigestSection]


class Digest(BaseModel):
    source_id: str
    sections: list[DigestSection]
```

`engine/corelata/schema/audit.py`:

```python
"""Auditor output (spec §8.2). There is no report field: the auditor cannot edit."""

from enum import StrEnum

from pydantic import BaseModel, Field


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    ATTESTED = "attested"


class FindingOut(BaseModel):
    rule_id: str
    verdict: Verdict
    evidence: str = Field(description="What in the draft (or missing from it) decided this")
    cited_units: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    recommendation: str = ""


class AuditOutput(BaseModel):
    findings: list[FindingOut]
    summary: str


class Finding(FindingOut):
    severity: str  # from the rule, never from the model
    route_to: str
    iteration: int

    @property
    def id(self) -> str:
        return f"{self.rule_id}@{self.iteration}"
```

`engine/corelata/schema/run.py`:

```python
"""The run state machine and the trace record `corelata run` writes (spec §7.2, §8.3)."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from corelata.schema.audit import Finding
from corelata.schema.common import LLMCallRecord, Usage
from corelata.schema.digest import Digest
from corelata.schema.gate import GateVerdict
from corelata.schema.report import Report, ReportBody, ReportStatus
from corelata.schema.source import Source


class RunState(StrEnum):
    CREATED = "created"
    INGESTING = "ingesting"
    GATING = "gating"
    DRAFTING = "drafting"
    CONVEYING = "conveying"
    AUDITING = "auditing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    GATE_REJECTED = "gate_rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {RunState.COMPLETED, RunState.GATE_REJECTED, RunState.FAILED, RunState.CANCELLED}
)


class StageResult(BaseModel):
    stage: str
    iteration: int
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class DraftRecord(BaseModel):
    role: str
    iteration: int
    report: ReportBody


class RunRecord(BaseModel):
    schema_version: Literal["1"] = "1"
    corelata_version: str
    run_id: str
    created_at: datetime
    state: RunState = RunState.CREATED
    status: ReportStatus | None = None
    value_statement: str
    profile: str | None = None
    pack_name: str
    pack_hash: str
    pack_snapshot: dict[str, Any]
    config_hash: str
    prompt_versions: dict[str, int]
    sources: list[Source] = Field(default_factory=list)
    digests: list[Digest] = Field(default_factory=list)
    gate: GateVerdict | None = None
    stages: list[StageResult] = Field(default_factory=list)
    drafts: list[DraftRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    report: Report | None = None
    iterations: int = 0
    max_iterations: int
    usage: Usage
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    error: str | None = None
```

`engine/corelata/schema/__init__.py`: re-export everything above (`BlockKind, Provenance, Block, SourceDocument, SourceKind, SourceUnit, Source, unit_ref, split_ref, Confidence, ClaimKind, Claim, KeyJudgment, SourceEntry, Paragraph, Section, Alternative, ReportBody, ReportStatus, ReportMetadata, Report, Substance, GateVerdict, CandidateStatement, DiscoveryResult, DigestSection, DigestOutput, Digest, Verdict, FindingOut, AuditOutput, Finding, RunState, TERMINAL_STATES, StageResult, DraftRecord, RunRecord, LLMCallRecord, Usage`) with a matching `__all__`.

- [ ] **Step 4: Run**

Run: `cd engine && uv run pytest tests/schema -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(schema): sources, report, gate, digest, audit and run records"
```

---

### Task 6: Standards pack schema and loader

**Files:**
- Create: `engine/corelata/standards/__init__.py`, `engine/corelata/standards/schema.py`, `engine/corelata/standards/loader.py`
- Test: `engine/tests/standards/__init__.py`, `engine/tests/standards/test_loader.py`, `engine/tests/standards/test_resolution_properties.py`

**Interfaces (spec §6):**
- `standards.schema`: `Severity BLOCKING|MAJOR|MINOR`; `Checkability VERIFIABLE|ADVISORY`; `RouteTo WRITER|CONVEYOR`; `RoleName = Literal["gate","writer","conveyor","auditor"]`; `Rule(id, title, source="", text, severity, checkability, applies_to: list[RoleName], evidence_required, route_to)` with `id` matching `^[a-z0-9]+(\.[a-z0-9]+)+$`; `ItemLimits(min: int, max: int)`; `Template(section_order: list[str], key_judgments: ItemLimits, analysis_max_words: int, alternatives_required_unless_all_high: bool, gaps_required: bool)`; `LikelihoodTerm(term, low: int, high: int)`; `Lexicon(likelihood: list[LikelihoodTerm], confidence_definitions: dict[Confidence, str], source_descriptors: list[str], handling_markings: list[str])` with `terms() -> set[str]`; `PackMeta(name, version, extends: str | None = None, description="")`; `RuleOverride(id, severity=None, checkability=None, route_to=None, text=None, evidence_required=None)`; `ProfileRules(add=[], disable=[], override=[])`; `TemplateOverride(key_judgments: ItemLimits | None, analysis_max_words: int | None)`; `ProfileFormat(docx_reference: Path | None, heading_style: Literal["plain","numbered"]="plain")`; `LexiconAdditions(handling_markings=[], source_descriptors=[])`; `Profile(name, extends, draft=False, rules: ProfileRules, template: TemplateOverride | None, tone="", format: ProfileFormat, lexicon: LexiconAdditions)`; `ResolvedPack(name, version, profile: str | None, rules: list[Rule], template: Template, lexicon: Lexicon, tone: str, format: ProfileFormat)` with `rule(rule_id) -> Rule`, `rules_for(role) -> list[Rule]`, `rule_ids() -> list[str]`.
- `standards.loader`: `PackError(ValueError)`; `BUILTIN_PACKS_DIR: Path`; `RawPack(meta, rules: list[Rule], template: Template | None, lexicon: Lexicon | None, profiles: dict[str, Profile], path: Path)`; `find_pack_dir(name, packs_dir) -> Path`; `read_pack_dir(path) -> RawPack`; `resolve(chain: list[RawPack], profile: Profile | None) -> ResolvedPack` (chain is base-first); `load_pack(name, *, packs_dir=None, profile=None, allow_draft=False) -> ResolvedPack`; `pack_hash(resolved) -> str` (16 hex chars); `validate_pack(path_or_name, packs_dir=None) -> list[ConfigIssue]`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/standards/__init__.py`: empty.

`engine/tests/standards/test_loader.py`:

```python
from pathlib import Path

import pytest
import yaml

from corelata.standards.loader import (
    PackError, find_pack_dir, load_pack, pack_hash, read_pack_dir, validate_pack,
)
from corelata.standards.schema import Checkability, RouteTo, Severity

RULE = {
    "id": "test.r.1",
    "title": "Rule one",
    "text": "Do the thing.",
    "severity": "major",
    "checkability": "verifiable",
    "applies_to": ["writer", "auditor"],
    "evidence_required": "Show the thing.",
    "route_to": "writer",
}
TEMPLATE = {
    "section_order": ["title", "handling_marking", "key_judgments", "scope_note", "sources",
                      "analysis", "alternatives", "gaps_and_indicators"],
    "key_judgments": {"min": 1, "max": 5},
    "analysis_max_words": 1200,
    "alternatives_required_unless_all_high": True,
    "gaps_required": True,
}
LEXICON = {
    "likelihood": [{"term": "likely", "low": 55, "high": 80}],
    "confidence_definitions": {"high": "H", "moderate": "M", "low": "L"},
    "source_descriptors": ["open-source report"],
    "handling_markings": ["UNCLASSIFIED"],
}


def write_pack(root: Path, name: str, *, rules: list[dict], extends: str | None = None,
               template: dict | None = TEMPLATE, lexicon: dict | None = LEXICON,
               profiles: dict[str, dict] | None = None) -> Path:
    pack = root / name
    (pack / "rules").mkdir(parents=True)
    meta = {"name": name, "version": "1.0", "extends": extends}
    (pack / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    for r in rules:
        (pack / "rules" / f"{r['id']}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    if template is not None:
        (pack / "template.yaml").write_text(yaml.safe_dump(template), encoding="utf-8")
    if lexicon is not None:
        (pack / "lexicon.yaml").write_text(yaml.safe_dump(lexicon), encoding="utf-8")
    if profiles:
        (pack / "profiles").mkdir()
        for pname, p in profiles.items():
            (pack / "profiles" / f"{pname}.yaml").write_text(yaml.safe_dump(p), encoding="utf-8")
    return pack


def test_read_and_resolve_single_pack(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    pack = load_pack("base", packs_dir=tmp_path)
    assert pack.name == "base" and pack.rule_ids() == ["test.r.1"]
    assert pack.rule("test.r.1").severity is Severity.MAJOR
    assert pack.rules_for("auditor") == pack.rules and pack.rules_for("gate") == []
    assert pack.lexicon.terms() == {"likely"}
    assert len(pack_hash(pack)) == 16


def test_extends_chain_merges_rules_and_profile_applies(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    child_rule = {**RULE, "id": "test.r.2", "severity": "minor"}
    profile = {
        "name": "team", "extends": "child",
        "rules": {
            "disable": ["test.r.2"],
            "override": [{"id": "test.r.1", "severity": "blocking", "route_to": "conveyor"}],
            "add": [{**RULE, "id": "team.r.1", "checkability": "advisory"}],
        },
        "template": {"key_judgments": {"min": 1, "max": 3}},
        "tone": "Terse.",
        "lexicon": {"handling_markings": ["UNCLASSIFIED//FOUO"]},
    }
    write_pack(tmp_path, "child", rules=[child_rule], extends="base", template=None,
               lexicon=None, profiles={"team": profile})
    pack = load_pack("child", packs_dir=tmp_path, profile="team")
    assert pack.rule_ids() == ["team.r.1", "test.r.1"]
    assert pack.rule("test.r.1").severity is Severity.BLOCKING
    assert pack.rule("test.r.1").route_to is RouteTo.CONVEYOR
    assert pack.rule("team.r.1").checkability is Checkability.ADVISORY
    assert pack.template.key_judgments.max == 3 and pack.template.analysis_max_words == 1200
    assert pack.tone == "Terse." and pack.profile == "team"
    assert pack.lexicon.handling_markings == ["UNCLASSIFIED", "UNCLASSIFIED//FOUO"]


def test_profile_hash_differs_from_base(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE],
               profiles={"t": {"name": "t", "extends": "base", "tone": "x"}})
    assert pack_hash(load_pack("base", packs_dir=tmp_path)) != pack_hash(
        load_pack("base", packs_dir=tmp_path, profile="t"))


def test_duplicate_rule_id_across_chain_is_error(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    write_pack(tmp_path, "child", rules=[RULE], extends="base", template=None, lexicon=None)
    with pytest.raises(PackError, match="rule 'test.r.1' defined in both"):
        load_pack("child", packs_dir=tmp_path)


def test_disable_or_override_unknown_rule_is_error(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE], profiles={
        "p1": {"name": "p1", "extends": "base", "rules": {"disable": ["nope.x.1"]}},
        "p2": {"name": "p2", "extends": "base",
               "rules": {"override": [{"id": "nope.x.2", "severity": "minor"}]}},
    })
    with pytest.raises(PackError, match="disables unknown rule 'nope.x.1'"):
        load_pack("base", packs_dir=tmp_path, profile="p1")
    with pytest.raises(PackError, match="overrides unknown rule 'nope.x.2'"):
        load_pack("base", packs_dir=tmp_path, profile="p2")


def test_extends_cycle_and_missing_parent(tmp_path):
    write_pack(tmp_path, "a", rules=[RULE], extends="b")
    write_pack(tmp_path, "b", rules=[], extends="a", template=None, lexicon=None)
    with pytest.raises(PackError, match="extends cycle"):
        load_pack("a", packs_dir=tmp_path)
    write_pack(tmp_path, "c", rules=[RULE], extends="ghost")
    with pytest.raises(PackError, match="pack 'ghost' not found"):
        load_pack("c", packs_dir=tmp_path)


def test_chain_without_template_or_lexicon_is_error(tmp_path):
    write_pack(tmp_path, "bare", rules=[RULE], template=None)
    with pytest.raises(PackError, match="no template.yaml"):
        load_pack("bare", packs_dir=tmp_path)
    write_pack(tmp_path, "bare2", rules=[RULE], lexicon=None)
    with pytest.raises(PackError, match="no lexicon.yaml"):
        load_pack("bare2", packs_dir=tmp_path)


def test_draft_profile_refused_unless_allowed(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE],
               profiles={"d": {"name": "d", "extends": "base", "draft": True}})
    with pytest.raises(PackError, match="profile 'd' is a draft"):
        load_pack("base", packs_dir=tmp_path, profile="d")
    assert load_pack("base", packs_dir=tmp_path, profile="d", allow_draft=True).profile == "d"


def test_unknown_profile(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    with pytest.raises(PackError, match="profile 'nope' not found in pack 'base'"):
        load_pack("base", packs_dir=tmp_path, profile="nope")


def test_rule_file_errors_name_the_file(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    (pack / "rules" / "bad.yaml").write_text("id: [\n", encoding="utf-8")
    with pytest.raises(PackError, match=r"bad\.yaml.*invalid YAML"):
        read_pack_dir(pack)
    (pack / "rules" / "bad.yaml").write_text(yaml.safe_dump({**RULE, "id": "Bad Id"}))
    with pytest.raises(PackError, match=r"bad\.yaml.*id"):
        read_pack_dir(pack)


def test_rule_id_mismatch_with_filename_is_error(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    (pack / "rules" / "other.yaml").write_text(yaml.safe_dump({**RULE, "id": "test.r.9"}))
    with pytest.raises(PackError, match="other.yaml: rule id 'test.r.9' must match the file name"):
        read_pack_dir(pack)


def test_find_pack_dir_prefers_customer_dir_then_builtin(tmp_path):
    write_pack(tmp_path, "icd203-base", rules=[RULE])
    assert find_pack_dir("icd203-base", tmp_path) == tmp_path / "icd203-base"
    assert find_pack_dir("icd203-base", None).name == "icd203-base"
    with pytest.raises(PackError, match="pack 'zzz' not found"):
        find_pack_dir("zzz", tmp_path)


def test_validate_pack_reports_issues_instead_of_raising(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE],
               profiles={"d": {"name": "d", "extends": "base", "draft": True},
                         "bad": {"name": "bad", "extends": "base",
                                 "rules": {"disable": ["nope.x.1"]}}})
    issues = validate_pack("base", packs_dir=tmp_path)
    levels = {(i.level, i.message.split(":")[0]) for i in issues}
    assert any(lvl == "warning" and "draft" in msg for lvl, msg in
               ((i.level, i.message) for i in issues))
    assert any(i.level == "error" and "nope.x.1" in i.message for i in issues)
    assert validate_pack(str(tmp_path / "base"), packs_dir=None) is not None
    assert levels  # smoke


def test_lexicon_band_validation(tmp_path):
    bad = {**LEXICON, "likelihood": [{"term": "likely", "low": 80, "high": 55}]}
    write_pack(tmp_path, "base", rules=[RULE], lexicon=bad)
    with pytest.raises(PackError, match="likelihood 'likely': low must be below high"):
        load_pack("base", packs_dir=tmp_path)
```

`engine/tests/standards/test_resolution_properties.py`:

```python
from hypothesis import given, settings
from hypothesis import strategies as st

from corelata.standards.loader import RawPack, resolve
from corelata.standards.schema import (
    Checkability, ItemLimits, Lexicon, PackMeta, Profile, ProfileRules, RouteTo, Rule,
    RuleOverride, Severity, Template,
)

ids = st.from_regex(r"\A[a-z]{1,4}\.[a-z]{1,3}\.[0-9]{1,2}\Z")


def rule(rule_id: str, severity: Severity = Severity.MAJOR) -> Rule:
    return Rule(
        id=rule_id, title="t", text="x", severity=severity,
        checkability=Checkability.VERIFIABLE, applies_to=["auditor"],
        evidence_required="e", route_to=RouteTo.WRITER,
    )


TEMPLATE = Template(
    section_order=["title"], key_judgments=ItemLimits(min=1, max=5), analysis_max_words=100,
    alternatives_required_unless_all_high=True, gaps_required=True,
)
LEXICON = Lexicon(likelihood=[], confidence_definitions={}, source_descriptors=[],
                  handling_markings=["U"])


def raw(name: str, rules: list[Rule], extends: str | None = None) -> RawPack:
    return RawPack(meta=PackMeta(name=name, version="1", extends=extends), rules=rules,
                   template=TEMPLATE if extends is None else None,
                   lexicon=LEXICON if extends is None else None, profiles={}, path=None)


@settings(max_examples=60, deadline=None)
@given(base_ids=st.lists(ids, min_size=1, max_size=6, unique=True),
       data=st.data())
def test_disable_wins_and_add_appends_and_result_sorted(base_ids, data):
    base = raw("base", [rule(i) for i in base_ids])
    disabled = data.draw(st.lists(st.sampled_from(base_ids), max_size=3, unique=True))
    overridden = data.draw(st.lists(st.sampled_from(base_ids), max_size=3, unique=True))
    added = data.draw(st.lists(ids.filter(lambda i: i not in base_ids), max_size=3, unique=True))
    profile = Profile(
        name="p", extends="base",
        rules=ProfileRules(
            add=[rule(i, Severity.MINOR) for i in added],
            disable=disabled,
            override=[RuleOverride(id=i, severity=Severity.BLOCKING) for i in overridden],
        ),
    )
    resolved = resolve([base], profile)
    got = resolved.rule_ids()
    assert got == sorted(got)
    assert set(got) == (set(base_ids) - set(disabled)) | set(added)
    for i in overridden:
        if i not in disabled:
            assert resolved.rule(i).severity is Severity.BLOCKING
    # idempotent: resolving the resolved rules as a base with no profile changes nothing
    again = resolve([raw("base", resolved.rules)], None)
    assert again.rules == resolved.rules
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/standards -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `standards/schema.py`**

```python
"""The standards pack data model (spec §6). Everything a customer edits is strict pydantic."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from corelata.schema.report import Confidence

RoleName = Literal["gate", "writer", "conveyor", "auditor"]
RULE_ID = r"^[a-z0-9]+(\.[a-z0-9]+)+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class Checkability(StrEnum):
    VERIFIABLE = "verifiable"
    ADVISORY = "advisory"


class RouteTo(StrEnum):
    WRITER = "writer"
    CONVEYOR = "conveyor"


class Rule(_Strict):
    id: str = Field(pattern=RULE_ID)
    title: str
    source: str = ""  # where the standard comes from, e.g. "ICD 203 (2015) D.6.e(2)"
    text: str
    severity: Severity
    checkability: Checkability
    applies_to: list[RoleName]
    evidence_required: str
    route_to: RouteTo


class ItemLimits(_Strict):
    min: int = Field(ge=0)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "ItemLimits":
        if self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class Template(_Strict):
    section_order: list[str]
    key_judgments: ItemLimits
    analysis_max_words: int = Field(ge=50)
    alternatives_required_unless_all_high: bool
    gaps_required: bool


class LikelihoodTerm(_Strict):
    term: str
    low: int = Field(ge=0, le=100)
    high: int = Field(ge=0, le=100)


class Lexicon(_Strict):
    likelihood: list[LikelihoodTerm]
    confidence_definitions: dict[Confidence, str]
    source_descriptors: list[str]
    handling_markings: list[str] = Field(min_length=1)

    def terms(self) -> set[str]:
        return {t.term for t in self.likelihood}


class PackMeta(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    version: str
    extends: str | None = None
    description: str = ""


class RuleOverride(_Strict):
    id: str = Field(pattern=RULE_ID)
    severity: Severity | None = None
    checkability: Checkability | None = None
    route_to: RouteTo | None = None
    text: str | None = None
    evidence_required: str | None = None


class ProfileRules(_Strict):
    add: list[Rule] = Field(default_factory=list)
    disable: list[str] = Field(default_factory=list)
    override: list[RuleOverride] = Field(default_factory=list)


class TemplateOverride(_Strict):
    key_judgments: ItemLimits | None = None
    analysis_max_words: int | None = Field(None, ge=50)


class ProfileFormat(_Strict):
    docx_reference: Path | None = None
    heading_style: Literal["plain", "numbered"] = "plain"


class LexiconAdditions(_Strict):
    handling_markings: list[str] = Field(default_factory=list)
    source_descriptors: list[str] = Field(default_factory=list)


class Profile(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    extends: str
    draft: bool = False
    rules: ProfileRules = Field(default_factory=ProfileRules)
    template: TemplateOverride | None = None
    tone: str = ""
    format: ProfileFormat = Field(default_factory=ProfileFormat)
    lexicon: LexiconAdditions = Field(default_factory=LexiconAdditions)


class ResolvedPack(BaseModel):
    """What a run snapshots (spec §6.6). Rules are sorted by id so the hash is stable."""

    name: str
    version: str
    profile: str | None
    rules: list[Rule]
    template: Template
    lexicon: Lexicon
    tone: str
    format: ProfileFormat

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)

    def rules_for(self, role: RoleName) -> list[Rule]:
        return [r for r in self.rules if role in r.applies_to]

    def rule_ids(self) -> list[str]:
        return [r.id for r in self.rules]
```

- [ ] **Step 4: Write `standards/loader.py`**

```python
"""Read pack directories, follow `extends`, apply a profile, hash the result (spec §6)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from corelata.config import ConfigIssue
from corelata.standards.schema import (
    Lexicon, PackMeta, Profile, ResolvedPack, Rule, Template,
)

BUILTIN_PACKS_DIR = Path(__file__).parent / "packs"


class PackError(ValueError):
    """A pack directory is unusable; the message names the file and the problem."""


@dataclass
class RawPack:
    meta: PackMeta
    rules: list[Rule]
    template: Template | None
    lexicon: Lexicon | None
    profiles: dict[str, Profile]
    path: Path | None


def _read_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PackError(f"{path.name}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise PackError(f"{path.name}: cannot read: {e}") from e


def _model[M: BaseModel](path: Path, model: type[M], data: object) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise PackError(f"{path.name}: {where}: {first['msg']}") from e


def find_pack_dir(name: str, packs_dir: Path | None) -> Path:
    for base in (packs_dir, BUILTIN_PACKS_DIR):
        if base is not None and (base / name / "pack.yaml").is_file():
            return base / name
    looked = ", ".join(str(b) for b in (packs_dir, BUILTIN_PACKS_DIR) if b is not None)
    raise PackError(f"pack '{name}' not found (looked in {looked})")


def read_pack_dir(path: Path) -> RawPack:
    meta = _model(path / "pack.yaml", PackMeta, _read_yaml(path / "pack.yaml"))
    rules: list[Rule] = []
    rules_dir = path / "rules"
    for file in sorted(rules_dir.glob("*.yaml")) if rules_dir.is_dir() else []:
        rule = _model(file, Rule, _read_yaml(file))
        if rule.id != file.stem:
            raise PackError(f"{file.name}: rule id '{rule.id}' must match the file name")
        rules.append(rule)
    template = lexicon = None
    if (path / "template.yaml").is_file():
        template = _model(path / "template.yaml", Template, _read_yaml(path / "template.yaml"))
    if (path / "lexicon.yaml").is_file():
        lexicon = _model(path / "lexicon.yaml", Lexicon, _read_yaml(path / "lexicon.yaml"))
        for t in lexicon.likelihood:
            if t.low >= t.high:
                raise PackError(f"lexicon.yaml: likelihood '{t.term}': low must be below high")
    profiles: dict[str, Profile] = {}
    profiles_dir = path / "profiles"
    for file in sorted(profiles_dir.glob("*.yaml")) if profiles_dir.is_dir() else []:
        profile = _model(file, Profile, _read_yaml(file))
        profiles[profile.name] = profile
    return RawPack(meta, rules, template, lexicon, profiles, path)


def _chain(name: str, packs_dir: Path | None) -> list[RawPack]:
    """Base-first list of packs: the named pack's ancestors, then itself."""
    chain: list[RawPack] = []
    seen: list[str] = []
    current: str | None = name
    while current is not None:
        if current in seen:
            raise PackError(f"extends cycle: {' -> '.join([*seen, current])}")
        seen.append(current)
        pack = read_pack_dir(find_pack_dir(current, packs_dir))
        chain.insert(0, pack)
        current = pack.meta.extends
    return chain


def resolve(chain: list[RawPack], profile: Profile | None) -> ResolvedPack:
    rules: dict[str, tuple[Rule, str]] = {}
    template: Template | None = None
    lexicon: Lexicon | None = None
    for pack in chain:
        for r in pack.rules:
            if r.id in rules:
                raise PackError(
                    f"rule '{r.id}' defined in both '{rules[r.id][1]}' and '{pack.meta.name}'"
                )
            rules[r.id] = (r, pack.meta.name)
        template = pack.template or template
        lexicon = pack.lexicon or lexicon
    leaf = chain[-1]
    if template is None:
        raise PackError(f"pack '{leaf.meta.name}': no template.yaml in it or its ancestors")
    if lexicon is None:
        raise PackError(f"pack '{leaf.meta.name}': no lexicon.yaml in it or its ancestors")
    tone = ""
    fmt = Profile(name="none", extends=leaf.meta.name).format
    if profile is not None:
        for rid in profile.rules.disable:
            if rid not in rules:
                raise PackError(f"profile '{profile.name}' disables unknown rule '{rid}'")
            del rules[rid]
        for ov in profile.rules.override:
            if ov.id not in rules:
                raise PackError(f"profile '{profile.name}' overrides unknown rule '{ov.id}'")
            base, origin = rules[ov.id]
            changes = {k: v for k, v in ov.model_dump().items() if k != "id" and v is not None}
            rules[ov.id] = (base.model_copy(update=changes), origin)
        for r in profile.rules.add:
            if r.id in rules:
                raise PackError(f"profile '{profile.name}' adds rule '{r.id}' that already exists")
            rules[r.id] = (r, profile.name)
        if profile.template is not None:
            changes = {k: v for k, v in profile.template.model_dump().items() if v is not None}
            if "key_judgments" in changes:
                changes["key_judgments"] = profile.template.key_judgments
            template = template.model_copy(update=changes)
        lexicon = lexicon.model_copy(
            update={
                "handling_markings": [*lexicon.handling_markings,
                                      *profile.lexicon.handling_markings],
                "source_descriptors": [*lexicon.source_descriptors,
                                       *profile.lexicon.source_descriptors],
            }
        )
        tone = profile.tone
        fmt = profile.format
    return ResolvedPack(
        name=leaf.meta.name,
        version=leaf.meta.version,
        profile=None if profile is None else profile.name,
        rules=[rules[k][0] for k in sorted(rules)],
        template=template,
        lexicon=lexicon,
        tone=tone,
        format=fmt,
    )


def load_pack(
    name: str, *, packs_dir: Path | None = None, profile: str | None = None,
    allow_draft: bool = False,
) -> ResolvedPack:
    chain = _chain(name, packs_dir)
    chosen: Profile | None = None
    if profile is not None:
        for pack in reversed(chain):
            if profile in pack.profiles:
                chosen = pack.profiles[profile]
                break
        if chosen is None:
            raise PackError(f"profile '{profile}' not found in pack '{name}' or its ancestors")
        if chosen.draft and not allow_draft:
            raise PackError(
                f"profile '{profile}' is a draft (draft: true); review it and remove the flag"
            )
    return resolve(chain, chosen)


def pack_hash(pack: ResolvedPack) -> str:
    dump = pack.model_dump_json()  # field order is fixed by the model; rules sorted by id
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]


def validate_pack(name_or_path: str, packs_dir: Path | None = None) -> list[ConfigIssue]:
    """`corelata pack validate`: every problem as an issue; never raises for pack content."""
    issues: list[ConfigIssue] = []
    path = Path(name_or_path)
    try:
        if path.is_dir():
            raw = read_pack_dir(path)
            packs_dir = path.parent
        else:
            raw = read_pack_dir(find_pack_dir(name_or_path, packs_dir))
        load_pack(raw.meta.name, packs_dir=packs_dir)
    except PackError as e:
        return [ConfigIssue(level="error", message=str(e))]
    for pname, profile in raw.profiles.items():
        if profile.draft:
            issues.append(ConfigIssue(level="warning", message=f"profile '{pname}' is a draft"))
        try:
            load_pack(raw.meta.name, packs_dir=packs_dir, profile=pname, allow_draft=True)
        except PackError as e:
            issues.append(ConfigIssue(level="error", message=f"profile '{pname}': {e}"))
    return issues
```

`engine/corelata/standards/__init__.py`: empty.

- [ ] **Step 5: Run**

Run: `cd engine && uv run pytest tests/standards -q --no-cov`
Expected: all pass. `test_find_pack_dir_prefers_customer_dir_then_builtin` needs the built-in pack from Task 7; until then it fails on the builtin assertion. Mark it `@pytest.mark.xfail(strict=True, reason="builtin pack arrives in Task 7")` now and remove the marker in Task 7.

- [ ] **Step 6: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(standards): pack schema, loader, profile resolution, hash"
```

---

### Task 7: The `icd203-base` pack

**Files:**
- Create: `engine/corelata/standards/packs/icd203-base/pack.yaml`, `template.yaml`, `lexicon.yaml`, `rules/*.yaml` (17 files)
- Test: `engine/tests/standards/test_builtin_pack.py`, golden file `engine/tests/standards/golden/icd203-base.resolved.json`
- Modify: `engine/pyproject.toml` (hatch must ship the YAML files), `engine/tests/standards/test_loader.py` (remove the xfail)

**Interfaces:**
- Produces: `load_pack("icd203-base")` resolves with the 17 rule ids in spec §6.7, lexicon terms per §6.4.

- [ ] **Step 1: Write the failing test**

`engine/tests/standards/test_builtin_pack.py`:

```python
import json
from pathlib import Path

from corelata.standards.loader import BUILTIN_PACKS_DIR, load_pack, pack_hash, validate_pack
from corelata.standards.schema import Checkability, Severity

GOLDEN = Path(__file__).parent / "golden" / "icd203-base.resolved.json"
EXPECTED_IDS = [
    "icd203.as.1", "icd203.as.2", "icd203.as.3", "icd203.as.4", "icd203.as.5",
    "icd203.tc.1", "icd203.tc.2", "icd203.tc.3", "icd203.tc.4", "icd203.tc.5",
    "icd203.tc.6", "icd203.tc.7", "icd203.tc.8", "icd203.tc.9",
    "icd206.src.1", "icd206.src.2", "icd206.src.3",
]


def test_builtin_pack_loads_with_expected_rules():
    pack = load_pack("icd203-base")
    assert pack.rule_ids() == EXPECTED_IDS
    assert pack.rule("icd203.tc.8").severity is Severity.BLOCKING
    assert pack.rule("icd203.as.2").checkability is Checkability.ADVISORY
    assert pack.rule("icd203.tc.9").checkability is Checkability.ADVISORY
    advisory = {r.id for r in pack.rules if r.checkability is Checkability.ADVISORY}
    assert advisory == {"icd203.as.1", "icd203.as.2", "icd203.as.3", "icd203.tc.7", "icd203.tc.9"}
    assert pack.lexicon.terms() == {
        "almost no chance", "very unlikely", "unlikely", "roughly even chance", "likely",
        "very likely", "almost certain",
    }
    assert pack.lexicon.handling_markings == ["UNCLASSIFIED"]
    assert pack.template.key_judgments.max == 5
    assert validate_pack("icd203-base") == []
    assert BUILTIN_PACKS_DIR.joinpath("icd203-base", "pack.yaml").is_file()


def test_builtin_pack_matches_golden():
    pack = load_pack("icd203-base")
    resolved = json.loads(pack.model_dump_json())
    if not GOLDEN.is_file():  # first run writes the golden; review the diff, then commit it
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n")
    assert resolved == json.loads(GOLDEN.read_text())
    assert pack_hash(pack) == pack_hash(load_pack("icd203-base"))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/standards/test_builtin_pack.py -q --no-cov`
Expected: FAIL with `PackError: pack 'icd203-base' not found`.

- [ ] **Step 3: Write the pack**

`pack.yaml`:

```yaml
name: icd203-base
version: "1.0.0"
description: >
  Intelligence Community Directive 203 (Analytic Standards, 2015) and ICD 206 (Sourcing
  Requirements) as checkable rules, with the ICD 203 estimative-language lexicon. Customers
  extend or replace this pack on their own deployment (spec §6).
```

`template.yaml`:

```yaml
section_order:
  - title
  - handling_marking
  - key_judgments
  - scope_note
  - sources
  - analysis
  - alternatives
  - gaps_and_indicators
key_judgments: { min: 1, max: 5 }
analysis_max_words: 1200
alternatives_required_unless_all_high: true
gaps_required: true
```

`lexicon.yaml`:

```yaml
likelihood:
  - { term: almost no chance, low: 1, high: 5 }
  - { term: very unlikely, low: 5, high: 20 }
  - { term: unlikely, low: 20, high: 45 }
  - { term: roughly even chance, low: 45, high: 55 }
  - { term: likely, low: 55, high: 80 }
  - { term: very likely, low: 80, high: 95 }
  - { term: almost certain, low: 95, high: 99 }
confidence_definitions:
  high: >
    Judgments rest on high-quality, corroborated information from multiple independent
    sources; the reasoning admits few plausible alternatives.
  moderate: >
    Judgments rest on credible but incompletely corroborated information, or on sound
    reasoning from limited information; alternative explanations remain plausible.
  low: >
    Judgments rest on fragmentary, uncorroborated or questionable information, or on
    significant assumptions; alternatives are as plausible as the judgment.
source_descriptors:
  - open-source report
  - open-source media article
  - official government publication
  - commercial database record
  - social media post
  - translated document
  - technical data extract
  - analyst-provided material
handling_markings:
  - UNCLASSIFIED
```

Rules. Each is `rules/<id>.yaml`. The `text` field quotes or closely paraphrases the directive; `source` gives the paragraph.

`rules/icd203.as.1.yaml`:

```yaml
id: icd203.as.1
title: Objective
source: "ICD 203 (2015) D.6.a"
text: >
  Analysts must perform their functions with objectivity and with awareness of their own
  assumptions and reasoning. They must employ reasoning techniques and practical mechanisms
  that reveal and mitigate bias.
severity: major
checkability: advisory
applies_to: [writer, conveyor, auditor]
evidence_required: >
  Note whether the draft states its assumptions and reasoning explicitly and avoids
  loaded or one-sided language.
route_to: writer
```

`rules/icd203.as.2.yaml`:

```yaml
id: icd203.as.2
title: Independent of political consideration
source: "ICD 203 (2015) D.6.b"
text: >
  Analytic assessments must not be distorted by, nor shaped for, advocacy of a particular
  audience, agenda, or policy viewpoint.
severity: major
checkability: advisory
applies_to: [writer, auditor]
evidence_required: >
  Note any passage that advocates a policy outcome rather than assessing a situation.
route_to: writer
```

`rules/icd203.as.3.yaml`:

```yaml
id: icd203.as.3
title: Timely
source: "ICD 203 (2015) D.6.c"
text: >
  Analysis must be disseminated in time to be actionable by customers.
severity: minor
checkability: advisory
applies_to: [auditor]
evidence_required: >
  Timeliness cannot be judged from the text alone; attest and note the date range of the
  sources if the draft states one.
route_to: conveyor
```

`rules/icd203.as.4.yaml`:

```yaml
id: icd203.as.4
title: Based on all available sources of intelligence information
source: "ICD 203 (2015) D.6.d"
text: >
  Analysis should be informed by all relevant information available. Analytic elements should
  identify and address critical information gaps.
severity: major
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  Every provided source is either cited by at least one claim or explicitly set aside in the
  scope note with a reason, and the gaps section names the information that is missing.
route_to: writer
```

`rules/icd203.as.5.yaml`:

```yaml
id: icd203.as.5
title: Implements and exhibits analytic tradecraft standards
source: "ICD 203 (2015) D.6.e"
text: >
  Analytic products must implement and exhibit the nine analytic tradecraft standards.
severity: major
checkability: verifiable
applies_to: [auditor]
evidence_required: >
  Pass when every verifiable icd203.tc.* rule passes; otherwise fail and list the failing
  tradecraft standards.
route_to: writer
```

`rules/icd203.tc.1.yaml`:

```yaml
id: icd203.tc.1
title: Properly describes quality and credibility of underlying sources, data, and methodologies
source: "ICD 203 (2015) D.6.e(1)"
text: >
  Analytic products should identify underlying sources and methodologies on which judgments are
  based, and use source descriptors to describe factors affecting source quality and
  credibility, such as accuracy and completeness, possible denial and deception, age and
  continued currency of information, and technical elements of collection.
severity: major
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  The sources section has one entry per source with a descriptor from the lexicon and a
  reliability note that addresses at least currency and completeness.
route_to: writer
```

`rules/icd203.tc.2.yaml`:

```yaml
id: icd203.tc.2
title: Properly expresses and explains uncertainties associated with major analytic judgments
source: "ICD 203 (2015) D.6.e(2)"
text: >
  Analytic products should indicate and explain the basis for the uncertainties associated with
  major analytic judgments, specifically the likelihood of occurrence of an event or
  development, and the analyst's confidence in the basis for this judgment. Products should
  use the standard terms of likelihood and should not combine a confidence level and a degree
  of likelihood in the same sentence.
severity: blocking
checkability: verifiable
applies_to: [writer, conveyor, auditor]
evidence_required: >
  Every key judgment carries a confidence level; every judgment claim uses a likelihood term
  from the lexicon and no other probability wording; the basis for uncertainty is stated.
route_to: writer
```

`rules/icd203.tc.3.yaml`:

```yaml
id: icd203.tc.3
title: Properly distinguishes between underlying intelligence information and analysts' assumptions and judgments
source: "ICD 203 (2015) D.6.e(3)"
text: >
  Analytic products should clearly distinguish statements that convey underlying intelligence
  information used in analysis from statements that convey assumptions or judgments.
  Assumptions should be explicitly stated and their implications for the analysis explained.
severity: major
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  Each claim's kind (fact, judgment, assumption) matches its wording; every assumption is
  stated as such in the analysis and its implication is given.
route_to: writer
```

`rules/icd203.tc.4.yaml`:

```yaml
id: icd203.tc.4
title: Incorporates analysis of alternatives
source: "ICD 203 (2015) D.6.e(4)"
text: >
  Analysis of alternatives is the systematic evaluation of differing hypotheses to explain
  events or phenomena, explore near-term outcomes, and imagine possible futures. Analytic
  products should identify and assess plausible alternative hypotheses, particularly when
  major judgments carry significant uncertainty or when a hypothesis would have major
  consequences if it proved true.
severity: major
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  At least one alternative hypothesis is stated and assessed whenever any key judgment is
  below high confidence; each alternative says why it is less likely than the judgment.
route_to: writer
```

`rules/icd203.tc.5.yaml`:

```yaml
id: icd203.tc.5
title: Demonstrates customer relevance and addresses implications
source: "ICD 203 (2015) D.6.e(5)"
text: >
  Analytic products should provide information and insight on issues relevant to the customers
  and address the implications of the information and analysis they provide.
severity: major
checkability: verifiable
applies_to: [writer, conveyor, auditor]
evidence_required: >
  The key judgments answer the value statement the analyst supplied, name the audience it
  serves, and state what the judgments imply for that audience.
route_to: conveyor
```

`rules/icd203.tc.6.yaml`:

```yaml
id: icd203.tc.6
title: Uses clear and logical argumentation
source: "ICD 203 (2015) D.6.e(6)"
text: >
  Analytic products should present a clear main analytic message up front. Products should
  provide the key reasons for the main analytic message and show how the evidence supports
  the judgments. Language and syntax should convey meaning unambiguously.
severity: major
checkability: verifiable
applies_to: [writer, conveyor, auditor]
evidence_required: >
  Key judgments come first; each analysis paragraph ties to the claims it supports; no
  paragraph contradicts a key judgment; sentences are unambiguous.
route_to: conveyor
```

`rules/icd203.tc.7.yaml`:

```yaml
id: icd203.tc.7
title: Explains change to or consistency of analytic judgments
source: "ICD 203 (2015) D.6.e(7)"
text: >
  Analytic products should state how their major judgments on a topic are consistent with or
  represent a change from those in previously published analysis, or represent initial
  coverage of a topic.
severity: minor
checkability: advisory
applies_to: [writer, auditor]
evidence_required: >
  Corelata v1 has no memory of prior reports; attest, and note whether the scope note says
  this is initial coverage.
route_to: writer
```

`rules/icd203.tc.8.yaml`:

```yaml
id: icd203.tc.8
title: Makes accurate judgments and assessments
source: "ICD 203 (2015) D.6.e(8)"
text: >
  Analytic products should apply expertise and logic to make the most accurate judgments and
  assessments possible, based on the information available and known information gaps.
  Judgments should not be overstated or understated relative to the evidence.
severity: blocking
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  Every claim cites at least one source unit whose text actually supports it; no judgment
  claims more than its cited units allow. Cite the claim ids and unit refs you checked.
route_to: writer
```

`rules/icd203.tc.9.yaml`:

```yaml
id: icd203.tc.9
title: Incorporates effective visual information where appropriate
source: "ICD 203 (2015) D.6.e(9)"
text: >
  Analytic products should incorporate visual information to clarify an analytic message and
  to complement or enhance the presentation of data and analysis.
severity: minor
checkability: advisory
applies_to: [auditor]
evidence_required: >
  Corelata v1 generates no visuals; attest. A profile may make this verifiable once a
  deployment renders charts or maps.
route_to: conveyor
```

`rules/icd206.src.1.yaml`:

```yaml
id: icd206.src.1
title: Source summary statement present
source: "ICD 206 (2015) D.2"
text: >
  Analytic products shall include a source summary statement that characterises the body of
  sourcing used, its strengths and weaknesses, and how it supports the key judgments.
severity: major
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  The scope note or sources section contains a summary of the sourcing as a whole, not only
  per-source entries.
route_to: writer
```

`rules/icd206.src.2.yaml`:

```yaml
id: icd206.src.2
title: Source reference citations for key judgments
source: "ICD 206 (2015) D.3"
text: >
  Analytic judgments shall be supported by source reference citations that allow the reader
  to identify the specific reporting behind each judgment.
severity: blocking
checkability: verifiable
applies_to: [writer, auditor]
evidence_required: >
  Every key judgment lists claim ids, and every one of those claims cites source units.
route_to: writer
```

`rules/icd206.src.3.yaml`:

```yaml
id: icd206.src.3
title: Source descriptors from the approved lexicon
source: "ICD 206 (2015) D.4"
text: >
  Source descriptors shall use consistent, approved terminology so that readers across
  products understand source type and reliability the same way.
severity: minor
checkability: verifiable
applies_to: [writer, conveyor, auditor]
evidence_required: >
  Every entry in the sources section uses a descriptor from the lexicon's source_descriptors.
route_to: conveyor
```

Ship the YAML in the wheel. Add to `engine/pyproject.toml` under `[tool.hatch.build.targets.wheel]`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["corelata"]
artifacts = ["corelata/standards/packs/**/*.yaml", "corelata/prompts/templates/**/*.j2"]
```

- [ ] **Step 4: Run, create the golden, review it**

Run: `cd engine && uv run pytest tests/standards -q --no-cov`
Expected: first run writes `tests/standards/golden/icd203-base.resolved.json` and passes; open the file and confirm the 17 rules and the lexicon look right. Remove the `xfail` marker added in Task 6 Step 5. Run again: passes.

- [ ] **Step 5: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(standards): ICD 203 + ICD 206 base pack with golden resolution"
```

---

### Task 8: Ingest parsers (copied) plus JSON and CSV

**Files:**
- Copy: `$COGLOSSA/engine/coglossa/ingest/{__init__,base,txt,markdown,docx,html,pdf}.py` → `engine/corelata/ingest/`
- Copy tests: `$COGLOSSA/engine/tests/ingest/{__init__,test_docx,test_html,test_pdf,test_txt_markdown,test_registry}.py` → `engine/tests/ingest/`
- Create: `engine/corelata/ingest/tabular.py`, `engine/corelata/ingest/registry.py`, `engine/tests/ingest/test_tabular.py`

**Interfaces:**
- Produces: `ingest.base.{IngestError, UnsupportedFormatError, Ingestor, file_sha256, read_utf8, split_paragraphs, make_blocks, strip_nul, error_reason, is_scene_break}`; `ingest.registry.{available_ingestors, check_extension, check_supported, ingest_file(path) -> SourceDocument}`; `ingest.tabular.{JsonIngestor, CsvIngestor}` producing `BlockKind.TABLE_CELL` blocks, one per record/row, locator `"record N"` / `"row N"`, with the CSV header carried as `"<header>: <value>; ..."` in the text so a unit is readable on its own.
- Consumes: `corelata.schema.{Block, BlockKind, Provenance, SourceDocument}` (Task 5); `corelata.text.clean_text` (Task 1).

- [ ] **Step 1: Copy and rename**

```bash
mkdir -p engine/corelata/ingest engine/tests/ingest
for f in __init__ base txt markdown docx html pdf; do
  cp $COGLOSSA/engine/coglossa/ingest/$f.py engine/corelata/ingest/$f.py
done
cp $COGLOSSA/engine/coglossa/ingest/registry.py engine/corelata/ingest/registry.py
for f in __init__ test_docx test_html test_pdf test_txt_markdown test_registry; do
  cp $COGLOSSA/engine/tests/ingest/$f.py engine/tests/ingest/$f.py
done
perl -pi -e 's/coglossa/corelata/g; s/Coglossa/Corelata/g; s/COGLOSSA/CORELATA/g' \
  engine/corelata/ingest/*.py engine/tests/ingest/*.py
```

Then edit `engine/corelata/ingest/registry.py`:
- Delete the `EpubIngestor` import and its entry in `available_ingestors()`.
- Add `from corelata.ingest.tabular import CsvIngestor, JsonIngestor` and append `JsonIngestor(), CsvIngestor()` to the list.
- Change the entry-point group to `corelata.ingestors` (the rename did this).
- Change the message `f"{path.name} contains no translatable text"` to `f"{path.name} contains no usable text"`.
- Docstring: `"""Pick an ingestor by file extension; third parties add formats via corelata.ingestors."""`

In `engine/corelata/ingest/html.py`, the EPUB helpers (`_epub_types`, `_is_footnote`, `_is_noteref`) stay: they are harmless and keep the file identical to Coglossa's. If `test_html.py` imports anything from an `epub` module, delete those tests only.

In `engine/tests/ingest/test_registry.py`, change `match="no translatable text"` to `match="no usable text"` and, if present, delete any test that references `.epub`.

- [ ] **Step 2: Write the failing tabular tests**

`engine/tests/ingest/test_tabular.py`:

```python
import json

import pytest

from corelata.ingest.base import IngestError
from corelata.ingest.registry import ingest_file
from corelata.schema import BlockKind


def test_json_array_one_unit_per_record(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps([{"who": "A", "what": "met B"}, {"who": "C", "what": "left"}]))
    doc = ingest_file(path)
    assert doc.format == "json"
    assert [b.kind for b in doc.blocks] == [BlockKind.TABLE_CELL] * 2
    assert doc.blocks[0].text == "who: A; what: met B"
    assert doc.blocks[1].provenance.locator == "record 2"


def test_json_object_one_unit_per_key(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"summary": "short", "detail": {"n": 1, "tags": ["x", "y"]}}))
    doc = ingest_file(path)
    assert doc.blocks[0].text == "summary: short"
    assert doc.blocks[1].text == 'detail: {"n": 1, "tags": ["x", "y"]}'
    assert doc.blocks[1].provenance.locator == "key detail"


def test_json_scalar_is_one_unit(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('"just text"')
    assert ingest_file(path).blocks[0].text == "just text"


def test_json_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nope")
    with pytest.raises(IngestError, match=r"bad\.json is not valid JSON"):
        ingest_file(path)


def test_csv_rows_carry_header(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("name,role\nAda,lead\nBob,analyst\n", encoding="utf-8")
    doc = ingest_file(path)
    assert [b.text for b in doc.blocks] == ["name: Ada; role: lead", "name: Bob; role: analyst"]
    assert doc.blocks[1].provenance.locator == "row 3"  # header is row 1


def test_csv_header_only_has_no_usable_text(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(IngestError, match="no usable text"):
        ingest_file(path)


def test_csv_ragged_rows_and_blank_cells(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("a,b,c\n1,,3\n4,5\n", encoding="utf-8")
    doc = ingest_file(path)
    assert [b.text for b in doc.blocks] == ["a: 1; c: 3", "a: 4; b: 5"]
```

- [ ] **Step 3: Run to verify failure**

Run: `cd engine && uv run pytest tests/ingest/test_tabular.py -q --no-cov`
Expected: ImportError for `corelata.ingest.tabular`.

- [ ] **Step 4: Write `tabular.py`**

```python
"""JSON and CSV ingestion (spec §5.2): one unit per record or row, readable on its own."""

import csv
import io
import json
from pathlib import Path

from corelata.ingest.base import IngestError, file_sha256, make_blocks, read_utf8, strip_nul
from corelata.schema import BlockKind, SourceDocument

Item = tuple[BlockKind, str, str | None]


def _scalar(value: object) -> str:
    if isinstance(value, str):
        return strip_nul(value)
    return json.dumps(value, ensure_ascii=False)


def _record_text(record: object) -> str:
    if isinstance(record, dict):
        return "; ".join(f"{k}: {_scalar(v)}" for k, v in record.items())
    return _scalar(record)


class JsonIngestor:
    format = "json"
    extensions = (".json",)

    def ingest(self, path: Path) -> SourceDocument:
        try:
            data = json.loads(read_utf8(path))
        except json.JSONDecodeError as e:
            raise IngestError(f"{path.name} is not valid JSON (line {e.lineno}: {e.msg})") from e
        items: list[Item] = []
        if isinstance(data, list):
            items = [
                (BlockKind.TABLE_CELL, _record_text(r), f"record {i}")
                for i, r in enumerate(data, start=1)
            ]
        elif isinstance(data, dict):
            items = [
                (BlockKind.TABLE_CELL, f"{k}: {_scalar(v)}", f"key {k}") for k, v in data.items()
            ]
        else:
            items = [(BlockKind.TABLE_CELL, _scalar(data), "value")]
        items = [it for it in items if it[1].strip()]
        return SourceDocument(
            source_path=str(path), format=self.format, sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )


class CsvIngestor:
    format = "csv"
    extensions = (".csv",)

    def ingest(self, path: Path) -> SourceDocument:
        reader = csv.reader(io.StringIO(read_utf8(path)))
        rows = [[strip_nul(c).strip() for c in row] for row in reader]
        header = rows[0] if rows else []
        items: list[Item] = []
        for number, row in enumerate(rows[1:], start=2):
            pairs = [
                f"{header[i] if i < len(header) else f'col{i + 1}'}: {cell}"
                for i, cell in enumerate(row)
                if cell
            ]
            if pairs:
                items.append((BlockKind.TABLE_CELL, "; ".join(pairs), f"row {number}"))
        return SourceDocument(
            source_path=str(path), format=self.format, sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )
```

- [ ] **Step 5: Run the whole ingest suite**

Run: `cd engine && uv run pytest tests/ingest -q --no-cov`
Expected: all pass. The copied tests exercise the copied parsers; `test_registry.py`'s plugin test uses the `corelata.ingestors` group.

- [ ] **Step 6: Lint, record, commit**

Append to Divergences: `ingest/: base, txt, markdown, docx, html, pdf copied unchanged; epub dropped; registry.py gains JsonIngestor/CsvIngestor and says "no usable text" instead of "no translatable text". tabular.py is new.`

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(ingest): copy Coglossa parsers, add JSON and CSV"
```

---

### Task 9: Source units, unit index, test source helper, Coglossa export adapter

**Files:**
- Create: `engine/corelata/ingest/units.py`, `engine/corelata/ingest/coglossa.py`, `engine/corelata/ingest/vendor/__init__.py`, `engine/corelata/ingest/vendor/coglossa-report-1.schema.json` (copy of `$COGLOSSA/schema/report.schema.json`), `engine/corelata/testing/sources.py`
- Test: `engine/tests/ingest/test_units.py`, `engine/tests/ingest/test_coglossa.py`
- Modify: `engine/pyproject.toml` (ship `vendor/*.json`)

**Interfaces (spec §5):**
- `ingest.units`: `units_from_document(doc: SourceDocument) -> list[SourceUnit]` (skips `BlockKind.BREAK`, ids `u1..`, locator from provenance: `"page N"` + `" / "` + provenance.locator when both, else whichever exists, else `"para <index+1>"`); `make_source(source_id: str, path: Path) -> Source` (kind FILE, name = `path.name`); `make_sources(paths: list[Path]) -> list[Source]` (ids `src1..` in order); `UnitIndex` with `UnitIndex.from_sources(sources)`, `.refs() -> list[str]`, `.get(ref) -> tuple[Source, SourceUnit]` (KeyError on unknown), `.text(ref) -> str`, `.has(ref) -> bool`, `.source(source_id) -> Source`.
- `ingest.coglossa`: `CoglossaExportError(IngestError)`; `load_coglossa_export(source_id: str, path: Path) -> list[Source]` returning the main source (kind COGLOSSA_EXPORT, format `"coglossa"`, provenance `{"coglossa_run_id", "coglossa_version", "document": {...}}`, one unit per span with locator `coglossa:<run_id>/span:<span_id>` and `meta` `{reliability, agreement, chosen_from, flags: [codes]}`) plus, when the export's guide has a non-empty `summary` or `style_guide` or glossary, a second source with id `f"{source_id}-guide"`, format `"coglossa-guide"`, units for summary, style guide and each glossary entry (`"<term> -> <rendering>"`, meta `{locked}`).
- `testing.sources`: `text_source(source_id: str, *paragraphs: str, name: str | None = None) -> Source` building a FILE source with one PARAGRAPH unit per string.

- [ ] **Step 1: Write the failing tests**

`engine/tests/ingest/test_units.py`:

```python
import pytest

from corelata.ingest.units import UnitIndex, make_source, make_sources, units_from_document
from corelata.schema import Block, BlockKind, Provenance, SourceDocument, SourceKind
from corelata.testing.sources import text_source


def _doc(*blocks):
    return SourceDocument(source_path="/x/a.txt", format="txt", sha256="ab" * 32, blocks=list(blocks))


def _block(i, kind, text, page=None, locator=None):
    return Block(id=f"b{i}", kind=kind, text=text,
                 provenance=Provenance(source_path="/x/a.txt", index=i - 1, page=page, locator=locator))


def test_units_skip_breaks_and_build_locators():
    doc = _doc(
        _block(1, BlockKind.PARAGRAPH, "one"),
        _block(2, BlockKind.BREAK, "* * *"),
        _block(3, BlockKind.PARAGRAPH, "two", page=3),
        _block(4, BlockKind.TABLE_CELL, "cell", page=3, locator="table 1 row 2 col 1"),
        _block(5, BlockKind.TABLE_CELL, "r", locator="row 7"),
    )
    units = units_from_document(doc)
    assert [u.id for u in units] == ["u1", "u2", "u3", "u4"]
    assert [u.locator for u in units] == ["para 1", "page 3", "page 3 / table 1 row 2 col 1", "row 7"]
    assert units[0].kind is BlockKind.PARAGRAPH and units[2].text == "cell"


def test_make_sources_ids_in_order_and_duplicate_names_stay_distinct(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "report.txt").write_text("Alpha text.", encoding="utf-8")
    (b / "report.txt").write_text("Beta text.", encoding="utf-8")
    sources = make_sources([a / "report.txt", b / "report.txt"])
    assert [s.id for s in sources] == ["src1", "src2"]
    assert [s.name for s in sources] == ["report.txt", "report.txt"]
    assert sources[0].sha256 != sources[1].sha256
    assert sources[0].kind is SourceKind.FILE and sources[0].format == "txt"
    assert make_source("srcX", a / "report.txt").id == "srcX"


def test_unit_index():
    s1 = text_source("src1", "alpha", "beta")
    s2 = text_source("src2", "gamma", name="g.txt")
    idx = UnitIndex.from_sources([s1, s2])
    assert idx.refs() == ["src1/u1", "src1/u2", "src2/u1"]
    assert idx.text("src2/u1") == "gamma"
    assert idx.has("src1/u2") and not idx.has("src1/u9") and not idx.has("garbage")
    src, unit = idx.get("src1/u2")
    assert src is s1 and unit.text == "beta"
    assert idx.source("src2").name == "g.txt"
    with pytest.raises(KeyError):
        idx.get("src3/u1")


def test_text_source_helper_defaults():
    s = text_source("src1", "a", "b")
    assert s.name == "src1.txt" and s.format == "txt" and len(s.sha256) == 64
    assert [u.locator for u in s.units] == ["para 1", "para 2"]
```

`engine/tests/ingest/test_coglossa.py`:

```python
import json
from pathlib import Path

import pytest

from corelata.ingest.coglossa import CoglossaExportError, load_coglossa_export
from corelata.schema import BlockKind, SourceKind

VENDORED = Path("corelata/ingest/vendor/coglossa-report-1.schema.json")


def export(**overrides) -> dict:
    data = {
        "schema_version": "1",
        "coglossa_version": "0.1.0",
        "run_id": "run-42",
        "created_at": "2026-10-12T00:00:00Z",
        "status": "complete",
        "document": {"source_path": "/in/letter.docx", "format": "docx", "sha256": "cd" * 32},
        "spans": [
            {"id": "p1", "chunk_id": "c1", "start": "s1", "end": "s1", "text": "Hello.",
             "agreement": "agree", "chosen_from": "literal",
             "score": {"signals": {}, "reliability": "A"}, "flags": []},
            {"id": "p2", "chunk_id": "c1", "start": "s2", "end": "s3", "text": "World.",
             "agreement": "major", "chosen_from": "rewritten",
             "score": {"signals": {}, "reliability": "B"},
             "flags": [{"code": "low_meaning", "explanation": "x"}]},
        ],
        "guide": {"summary": "A letter.", "style_guide": "Formal.",
                  "glossary": [{"term": "Herr", "rendering": "Mr", "locked": True}],
                  "entities": [], "cultural_references": []},
    }
    data.update(overrides)
    return data


def write(tmp_path, data) -> Path:
    path = tmp_path / "letter.coglossa.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_spans_become_units_with_provenance(tmp_path):
    main, guide = load_coglossa_export("src1", write(tmp_path, export()))
    assert main.kind is SourceKind.COGLOSSA_EXPORT and main.format == "coglossa"
    assert main.provenance["coglossa_run_id"] == "run-42"
    assert main.provenance["document"]["source_path"] == "/in/letter.docx"
    assert [u.id for u in main.units] == ["u1", "u2"]
    assert main.units[1].locator == "coglossa:run-42/span:p2"
    assert main.units[1].meta == {"reliability": "B", "agreement": "major",
                                  "chosen_from": "rewritten", "flags": ["low_meaning"]}
    assert main.units[0].kind is BlockKind.PARAGRAPH
    assert guide.id == "src1-guide" and guide.format == "coglossa-guide"
    assert [u.text for u in guide.units] == ["A letter.", "Formal.", "Herr -> Mr"]
    assert guide.units[2].meta == {"locked": True}


def test_empty_guide_yields_single_source(tmp_path):
    data = export(guide={"summary": "", "style_guide": "", "glossary": [], "entities": [],
                         "cultural_references": []})
    assert len(load_coglossa_export("src1", write(tmp_path, data))) == 1


def test_unknown_schema_version_refused(tmp_path):
    with pytest.raises(CoglossaExportError, match="schema_version '2'"):
        load_coglossa_export("src1", write(tmp_path, export(schema_version="2")))


def test_invalid_json_and_shape(tmp_path):
    path = tmp_path / "x.coglossa.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(CoglossaExportError, match="not valid JSON"):
        load_coglossa_export("src1", path)
    with pytest.raises(CoglossaExportError, match="spans"):
        load_coglossa_export("src1", write(tmp_path, export(spans="nope")))


def test_no_spans_is_no_usable_text(tmp_path):
    with pytest.raises(CoglossaExportError, match="no usable text"):
        load_coglossa_export("src1", write(tmp_path, export(spans=[])))


def test_vendored_schema_agrees_with_adapter_fields():
    schema = json.loads(VENDORED.read_text())
    props = schema["properties"]
    assert {"schema_version", "run_id", "document", "spans", "guide"} <= set(props)
    span = schema["$defs"]["Span"]["properties"]
    assert {"id", "text", "agreement", "chosen_from", "score", "flags"} <= set(span)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/ingest/test_units.py tests/ingest/test_coglossa.py -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `units.py`**

```python
"""Blocks become addressable source units; a UnitIndex answers unit refs (spec §5.2)."""

from dataclasses import dataclass, field
from pathlib import Path

from corelata.ingest.registry import ingest_file
from corelata.schema import (
    BlockKind, Source, SourceDocument, SourceKind, SourceUnit, split_ref, unit_ref,
)


def _locator(page: int | None, locator: str | None, index: int) -> str:
    parts = []
    if page is not None:
        parts.append(f"page {page}")
    if locator:
        parts.append(locator)
    return " / ".join(parts) if parts else f"para {index + 1}"


def units_from_document(doc: SourceDocument) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    for block in doc.blocks:
        if block.kind is BlockKind.BREAK:
            continue
        p = block.provenance
        units.append(
            SourceUnit(
                id=f"u{len(units) + 1}",
                text=block.text,
                locator=_locator(p.page, p.locator, p.index),
                kind=block.kind,
            )
        )
    return units


def make_source(source_id: str, path: Path) -> Source:
    doc = ingest_file(path)
    return Source(
        id=source_id, kind=SourceKind.FILE, name=path.name, format=doc.format,
        sha256=doc.sha256, units=units_from_document(doc),
    )


def make_sources(paths: list[Path]) -> list[Source]:
    return [make_source(f"src{i}", p) for i, p in enumerate(paths, start=1)]


@dataclass
class UnitIndex:
    _sources: dict[str, Source] = field(default_factory=dict)
    _units: dict[str, tuple[Source, SourceUnit]] = field(default_factory=dict)

    @classmethod
    def from_sources(cls, sources: list[Source]) -> "UnitIndex":
        index = cls()
        for s in sources:
            index._sources[s.id] = s
            for u in s.units:
                index._units[unit_ref(s.id, u.id)] = (s, u)
        return index

    def refs(self) -> list[str]:
        return list(self._units)

    def has(self, ref: str) -> bool:
        try:
            split_ref(ref)
        except ValueError:
            return False
        return ref in self._units

    def get(self, ref: str) -> tuple[Source, SourceUnit]:
        return self._units[ref]

    def text(self, ref: str) -> str:
        return self._units[ref][1].text

    def source(self, source_id: str) -> Source:
        return self._sources[source_id]

    def sources(self) -> list[Source]:
        return list(self._sources.values())
```

- [ ] **Step 4: Write `testing/sources.py`**

```python
"""Build sources from strings for tests and demos, without touching the file system."""

import hashlib

from corelata.schema import BlockKind, Source, SourceKind, SourceUnit


def text_source(source_id: str, *paragraphs: str, name: str | None = None) -> Source:
    text = "\n\n".join(paragraphs)
    return Source(
        id=source_id,
        kind=SourceKind.FILE,
        name=name or f"{source_id}.txt",
        format="txt",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        units=[
            SourceUnit(id=f"u{i}", text=p, locator=f"para {i}", kind=BlockKind.PARAGRAPH)
            for i, p in enumerate(paragraphs, start=1)
        ],
    )
```

- [ ] **Step 5: Write `coglossa.py` and vendor the schema**

```bash
mkdir -p engine/corelata/ingest/vendor && touch engine/corelata/ingest/vendor/__init__.py
cp $COGLOSSA/schema/report.schema.json engine/corelata/ingest/vendor/coglossa-report-1.schema.json
```

Add `"corelata/ingest/vendor/*.json"` to the `artifacts` list in `pyproject.toml`.

`engine/corelata/ingest/coglossa.py`:

```python
"""Coglossa export adapter (spec §5.3). The vendored JSON Schema documents the full export; the
pydantic subset below is what Corelata reads. Unknown fields are ignored, unknown schema
versions are refused."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from corelata.ingest.base import IngestError, file_sha256, read_utf8
from corelata.schema import BlockKind, Source, SourceKind, SourceUnit

VENDORED_SCHEMA = Path(__file__).parent / "vendor" / "coglossa-report-1.schema.json"


class CoglossaExportError(IngestError):
    pass


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Flag(_Loose):
    code: str


class _Score(_Loose):
    reliability: str = "unscored"


class _Span(_Loose):
    id: str
    text: str
    agreement: str
    chosen_from: str
    score: _Score = Field(default_factory=_Score)
    flags: list[_Flag] = Field(default_factory=list)


class _Glossary(_Loose):
    term: str
    rendering: str
    locked: bool = False


class _Guide(_Loose):
    summary: str = ""
    style_guide: str = ""
    glossary: list[_Glossary] = Field(default_factory=list)


class _Document(_Loose):
    source_path: str
    format: str
    sha256: str


class CoglossaExport(_Loose):
    schema_version: Literal["1"]
    coglossa_version: str
    run_id: str | None = None
    document: _Document
    spans: list[_Span]
    guide: _Guide = Field(default_factory=_Guide)


def _parse(path: Path) -> CoglossaExport:
    try:
        raw: Any = json.loads(read_utf8(path))
    except json.JSONDecodeError as e:
        raise CoglossaExportError(f"{path.name} is not valid JSON ({e.msg})") from e
    version = raw.get("schema_version") if isinstance(raw, dict) else None
    if version != "1":
        raise CoglossaExportError(
            f"{path.name}: Coglossa export schema_version '{version}' is not supported (want '1')"
        )
    try:
        return CoglossaExport.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise CoglossaExportError(f"{path.name}: {where}: {first['msg']}") from e


def load_coglossa_export(source_id: str, path: Path) -> list[Source]:
    export = _parse(path)
    run_id = export.run_id or "unknown"
    units = [
        SourceUnit(
            id=f"u{i}",
            text=span.text,
            locator=f"coglossa:{run_id}/span:{span.id}",
            kind=BlockKind.PARAGRAPH,
            meta={
                "reliability": span.score.reliability,
                "agreement": span.agreement,
                "chosen_from": span.chosen_from,
                "flags": [f.code for f in span.flags],
            },
        )
        for i, span in enumerate(export.spans, start=1)
        if span.text.strip()
    ]
    if not units:
        raise CoglossaExportError(f"{path.name} contains no usable text (no spans)")
    sha = file_sha256(path)
    main = Source(
        id=source_id,
        kind=SourceKind.COGLOSSA_EXPORT,
        name=path.name,
        format="coglossa",
        sha256=sha,
        provenance={
            "coglossa_run_id": run_id,
            "coglossa_version": export.coglossa_version,
            "document": export.document.model_dump(),
        },
        units=units,
    )
    guide_texts: list[tuple[str, dict[str, Any]]] = []
    if export.guide.summary.strip():
        guide_texts.append((export.guide.summary, {"part": "summary"}))
    if export.guide.style_guide.strip():
        guide_texts.append((export.guide.style_guide, {"part": "style_guide"}))
    guide_texts += [(f"{g.term} -> {g.rendering}", {"locked": g.locked}) for g in export.guide.glossary]
    if not guide_texts:
        return [main]
    guide = Source(
        id=f"{source_id}-guide",
        kind=SourceKind.COGLOSSA_EXPORT,
        name=f"{path.name} (translation guide)",
        format="coglossa-guide",
        sha256=sha,
        provenance={"coglossa_run_id": run_id, "part": "guide"},
        units=[
            SourceUnit(id=f"u{i}", text=text, locator=f"coglossa:{run_id}/guide:{i}",
                       kind=BlockKind.PARAGRAPH, meta=meta)
            for i, (text, meta) in enumerate(guide_texts, start=1)
        ],
    )
    return [main, guide]
```

Adjust the test `test_spans_become_units_with_provenance` expectation for the guide's third unit: `meta == {"locked": True}` holds because glossary entries carry only `locked`; summary and style_guide units carry `{"part": ...}`.

- [ ] **Step 6: Run**

Run: `cd engine && uv run pytest tests/ingest -q --no-cov`
Expected: all pass.

- [ ] **Step 7: Record, lint, commit**

Append to Spec deviations in `docs/m1-followups.md`: `§5.3 says the adapter validates against the vendored JSON Schema; M1 validates with a pydantic subset of it (no jsonschema dependency) and refuses unknown schema_version. The vendored file is kept and a test checks the subset's field names against it.`

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(ingest): source units, unit index, Coglossa export adapter"
```

---

### Task 10: Prompt templates, prompt check, and the synthetic responder

**Files:**
- Create: `engine/corelata/prompts/templates/{gate,discover,digest,writer,conveyor,auditor}/v1.j2`, `engine/corelata/prompts/check.py`
- Modify: `engine/corelata/testing/synthetic.py` (full role handlers)
- Test: `engine/tests/prompts/__init__.py`, `engine/tests/prompts/test_library.py`, `engine/tests/prompts/test_check.py`, `engine/tests/testing/test_synthetic.py`
- Delete: `engine/corelata/prompts/templates/ping/` (move the `ping` prompt to a test fixture dir: `engine/tests/fixtures/prompts/ping/v1.j2`, and point the Task 3 agent tests at it via `PromptLibrary(override_dir=Path("tests/fixtures/prompts"))` in `make_runner`; `ping` stays a synthetic task).

**Interfaces:**
- Prompt ids and their Jinja variables (all strings unless noted):
  - `gate`: `mode` (`"verify"` or `"discover"`), `tone`.
  - `discover`: `audience_hint`, `tone`.
  - `digest`: none.
  - `writer`: `tone`, `section_order` (list[str]), `iteration` (int).
  - `conveyor`: `tone`, `heading_style`.
  - `auditor`: none.
- Payload shapes (the `task` key selects the synthetic handler and names the prompt):
  - gate verify: `{"task":"gate","value_statement":str,"digests":[Digest],"units":[{"ref","text","locator","source"}]}`
  - discover: `{"task":"discover","audience_hint":str,"digests":[...],"units":[...]}`
  - digest: `{"task":"digest","source":{"id","name"},"units":[{"ref","text"}]}`
  - writer: `{"task":"writer","value_statement","template":Template,"rules":[Rule],"lexicon":Lexicon,"digests":[...],"units":[...],"sources":[{"id","name","format","provenance"}],"prior_draft":ReportBody|None,"findings":[Finding],"extra_guidance":str,"iteration":int}`
  - conveyor: `{"task":"conveyor","draft":ReportBody,"template":Template,"rules":[Rule],"tone":str,"findings":[Finding],"iteration":int}`
  - auditor: `{"task":"auditor","draft":ReportBody,"rules":[{"id","title","text","severity","checkability","evidence_required"}],"lexicon":Lexicon,"cited_units":[{"ref","text"}],"value_statement":str}`
- `prompts.check.validate_prompts(cfg, prompts) -> None` raises `ConfigError` if any of the six prompts fails to render; `prompts.check.run_prompt_ids() -> list[str]` returns `["gate", "discover", "digest", "writer", "conveyor", "auditor"]`.
- `testing.synthetic.synthetic_response(payload) -> dict` handles the six tasks plus `ping`; markers `UNSOURCED`, `UNFIXABLE`, `BADTERM` as described in Step 4.

- [ ] **Step 1: Write the prompt templates**

`templates/gate/v1.j2`:

```
You are the value gate for an intelligence reporting team.{% if tone %} House guidance: {{ tone }}{% endif %}
{% if mode == "verify" -%}
INPUT_JSON.value_statement is an analyst's claim about what the material shows, why it matters and for whom. INPUT_JSON.units are passages from the sources (each with a "ref"), and INPUT_JSON.digests summarise sources too long to show in full.
Decide whether the sources support the statement and whether there is enough substance to write a report.
- supported: true only if specific passages back the statement's core assertion. Hearsay in a single passage is support; absence of contradiction is not.
- substance: "sufficient" when several independent passages bear on the statement; "thin" when it rests on one or two passages or on a digest alone; "insufficient" when the material does not address it.
- reasons: one sentence each, citing refs, for what supports and what undermines the statement.
- evidence: the refs that matter most (at most 12), best first.
- suggested_scope: if thin, one sentence the writer must include in the scope note describing the limits of the material.
{%- else -%}
No value statement was given. From INPUT_JSON.units and INPUT_JSON.digests, propose what intelligence value this material holds.
Return a JSON object with "candidates": up to five objects {text, audience, evidence, confidence_note}. "text" is a one-to-three-sentence value statement an analyst could adopt. "audience" names who would act on it. "evidence" lists the refs behind it. "confidence_note" says how firmly the material supports it.
{%- endif %}
Respond with a single JSON object only.
```

`templates/discover/v1.j2`:

```
You are the value gate for an intelligence reporting team, working in discovery mode.{% if tone %} House guidance: {{ tone }}{% endif %}
INPUT_JSON.units are passages from the sources (each with a "ref"); INPUT_JSON.digests summarise sources too long to show in full.{% if audience_hint %} The analyst expects the audience to be: {{ audience_hint }}.{% endif %}
Propose what intelligence value this material holds. Return "candidates": up to five objects {text, audience, evidence, confidence_note}. "text" is a one-to-three-sentence value statement an analyst could adopt: what the material shows, why it matters, for whom. "audience" names who would act on it. "evidence" lists the refs behind it. "confidence_note" says how firmly the material supports it. Prefer candidates that several passages support over ones that rest on a single passage.
Respond with a single JSON object only.
```

`templates/digest/v1.j2`:

```
You summarise one long source for analysts who will cite it. INPUT_JSON.source names it; INPUT_JSON.units are its passages in order, each with a "ref".
Return "sections": an ordered list of {summary, unit_refs}. Each section covers a run of consecutive passages: "summary" states what those passages say in two to four sentences with every name, number, date and place preserved; "unit_refs" lists exactly the refs the summary covers. Every passage must appear in exactly one section. Never add information the passages do not contain.
Respond with a single JSON object only.
```

`templates/writer/v1.j2`:

```
You are the writer on an intelligence reporting team producing one analytic assessment. Iteration {{ iteration }}.{% if tone %} House guidance: {{ tone }}{% endif %}
INPUT_JSON.value_statement is what the analyst needs the report to establish and for whom. INPUT_JSON.units are the source passages you may cite (each with a "ref"); INPUT_JSON.digests summarise sources too long to show in full; INPUT_JSON.sources describes each source. INPUT_JSON.template gives the required structure, INPUT_JSON.rules the standards you must meet, INPUT_JSON.lexicon the only likelihood terms, confidence definitions, source descriptors and handling markings you may use.
Write the report as one JSON object with these sections in this order: {{ section_order | join(", ") }}.
- Every assertion is a claim in "claims" with an id (c1, c2, …), a kind ("fact" for what the sources say, "judgment" for your assessment, "assumption" for what you take as given), and "evidence": the refs that support it. A judgment also names its "likelihood_term" from the lexicon. A claim with no evidence will fail the audit.
- key_judgments answer the value statement first, each with a confidence level and the claim ids it rests on.
- sources: one entry per source in INPUT_JSON.sources with a descriptor from the lexicon and a reliability note on currency and completeness.
- analysis: headed sections whose paragraphs list the claim ids they draw on. Distinguish what the sources say from what you judge.
- alternatives: at least one plausible alternative hypothesis and why it is less likely, unless every key judgment is high confidence.
- gaps_and_indicators: what is missing and what would change the judgments.
- scope_note: what material was used and set aside and why; if the gate marked the material thin, include its suggested scope sentence.
{% if iteration > 0 -%}
INPUT_JSON.prior_draft is the previous draft and INPUT_JSON.findings are the audit findings routed to you. Fix every finding: a failing rule names its evidence and a recommendation. Keep what passed.
{%- endif %}
{% if iteration == 0 and extra_guidance is defined and extra_guidance -%}
Additional guidance from the analyst: {{ extra_guidance }}
{%- endif %}
Respond with a single JSON object only.
```

Note: `extra_guidance` is passed as a prompt variable in Task 12; add it to the writer's prompt_vars.

`templates/conveyor/v1.j2`:

```
You are the conveyance reviewer: you edit an intelligence assessment so the downstream reader grasps it fast and cannot misread it.{% if tone %} House guidance: {{ tone }}{% endif %}
INPUT_JSON.draft is the report as JSON; INPUT_JSON.template is the required structure; INPUT_JSON.rules are the standards that concern presentation. Headings are {{ heading_style }}.
Return the full report JSON with your edits:
- Lead with the main message. Key judgments must be readable without the analysis.
- Make every sentence unambiguous; cut hedges that are not estimative language; keep the likelihood terms and confidence levels exactly as written.
- Keep every claim id and every evidence ref. You may reword claims; you may not add a claim without evidence or remove evidence from one. You may not change a claim's kind.
- Keep the handling marking and the sources section intact apart from wording.
{% if findings -%}
INPUT_JSON.findings are audit findings routed to you about presentation; resolve each.
{%- endif %}
Respond with a single JSON object only.
```

`templates/auditor/v1.j2`:

```
You are the compliance auditor for an intelligence reporting team. You never edit the report: you return findings only.
INPUT_JSON.draft is the report as JSON. INPUT_JSON.rules are the standards to check, each with an id, severity, checkability and the evidence required to decide it. INPUT_JSON.cited_units are the source passages the draft's claims cite, by "ref", so you can check that each claim is actually supported. INPUT_JSON.lexicon lists the only permitted likelihood terms, confidence levels, source descriptors and handling markings. INPUT_JSON.value_statement is what the analyst asked the report to establish.
Return "findings": exactly one object per rule in INPUT_JSON.rules, in the same order, and a one-paragraph "summary".
- verdict: "pass" or "fail" for verifiable rules; "not_applicable" when the rule's subject is absent by design (say why); "attested" for advisory rules, with a note on what you observed.
- evidence: what in the draft, or missing from it, decided the verdict. For icd203.tc.8 and icd206.src.2, name every claim whose cited passages do not support it, or that cites nothing.
- cited_units and claim_ids: the refs and claim ids you examined for this rule.
- recommendation: for a fail, one or two sentences the writer or reviewer can act on.
Be strict: a claim whose evidence list is empty fails icd203.tc.8. A judgment using a likelihood term outside the lexicon fails icd203.tc.2.
Respond with a single JSON object only.
```

- [ ] **Step 2: Write `prompts/check.py`**

```python
"""Fail fast on unusable prompts: test-render every prompt a run uses, before any model call."""

from jinja2 import TemplateError

from corelata.config import ConfigError, CorelataConfig
from corelata.prompts.library import PromptLibrary, PromptNotFoundError

_CHECKS: list[tuple[str, dict[str, object]]] = [
    ("gate", {"mode": "verify", "tone": ""}),
    ("gate", {"mode": "discover", "tone": "x"}),
    ("discover", {"audience_hint": "", "tone": ""}),
    ("digest", {}),
    ("writer", {"tone": "", "section_order": ["title"], "iteration": 0, "extra_guidance": ""}),
    ("writer", {"tone": "x", "section_order": ["title"], "iteration": 1, "extra_guidance": "g"}),
    ("conveyor", {"tone": "", "heading_style": "plain", "findings": []}),
    ("auditor", {}),
]


def run_prompt_ids() -> list[str]:
    return ["gate", "discover", "digest", "writer", "conveyor", "auditor"]


def validate_prompts(cfg: CorelataConfig, prompts: PromptLibrary) -> None:
    for prompt_id, variables in _CHECKS:
        try:
            prompts.render(prompt_id, **variables)
        except (PromptNotFoundError, TemplateError, OSError, UnicodeDecodeError) as e:
            raise ConfigError(f"prompt '{prompt_id}' is unusable: {e}") from e
```

- [ ] **Step 3: Write the prompt tests**

`engine/tests/prompts/test_library.py`:

```python
from pathlib import Path

import pytest
from jinja2 import UndefinedError

from corelata.prompts.check import _CHECKS, run_prompt_ids, validate_prompts
from corelata.prompts.library import PromptLibrary, PromptNotFoundError
from corelata.config import ConfigError


@pytest.mark.parametrize(("prompt_id", "variables"), _CHECKS)
def test_builtin_templates_render(prompt_id, variables):
    rendered = PromptLibrary().render(prompt_id, **variables)
    assert rendered.id == prompt_id and rendered.version == 1
    assert "JSON" in rendered.text
    assert "{{" not in rendered.text and "{%" not in rendered.text


def test_gate_modes_differ():
    verify = PromptLibrary().render("gate", mode="verify", tone="").text
    discover = PromptLibrary().render("gate", mode="discover", tone="").text
    assert "supported" in verify and "candidates" in discover and "supported" not in discover


def test_writer_iteration_one_mentions_findings():
    text = PromptLibrary().render(
        "writer", tone="", section_order=["title"], iteration=1, extra_guidance=""
    ).text
    assert "prior_draft" in text


def test_missing_variable_fails_loudly():
    with pytest.raises(UndefinedError):
        PromptLibrary().render("writer", tone="")


def test_override_dir_wins(tmp_path):
    (tmp_path / "auditor").mkdir()
    (tmp_path / "auditor" / "v2.j2").write_text("custom auditor JSON", encoding="utf-8")
    lib = PromptLibrary(tmp_path)
    assert lib.render("auditor").text == "custom auditor JSON"
    assert lib.versions(["auditor", "gate"]) == {"auditor": 2, "gate": 1}


def test_unknown_prompt():
    with pytest.raises(PromptNotFoundError):
        PromptLibrary().resolve("nope")


def test_validate_prompts_reports_broken_override(make_config, tmp_path):
    (tmp_path / "digest").mkdir()
    (tmp_path / "digest" / "v1.j2").write_text("{{ undefined_thing }}", encoding="utf-8")
    with pytest.raises(ConfigError, match="prompt 'digest' is unusable"):
        validate_prompts(make_config(), PromptLibrary(tmp_path))
    validate_prompts(make_config(), PromptLibrary())
    assert run_prompt_ids() == ["gate", "discover", "digest", "writer", "conveyor", "auditor"]
    assert Path("corelata/prompts/templates/ping").exists() is False
```

- [ ] **Step 4: Write the synthetic responder**

Replace `engine/corelata/testing/synthetic.py` with:

```python
"""Deterministic stand-in for a model: valid output for every agent task, no intelligence.
Markers in source text steer it so tests and demos have something to find:
- UNSOURCED: the writer emits a claim with no evidence; it removes it when findings are routed
  back, unless the text also says UNFIXABLE.
- BADTERM: the writer puts the word BADTERM in a key judgment; the auditor fails icd203.tc.2."""

import re
from collections.abc import Callable
from typing import Any

Payload = dict[str, Any]
UNSOURCED, UNFIXABLE, BADTERM = "UNSOURCED", "UNFIXABLE", "BADTERM"
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']{3,}")


def key_terms(statement: str) -> list[str]:
    seen: dict[str, None] = {}
    for w in _WORD.findall(statement):
        seen.setdefault(w.casefold(), None)
    return list(seen)


def _unit_texts(p: Payload) -> list[tuple[str, str]]:
    units = [(u["ref"], u["text"]) for u in p.get("units", [])]
    for d in p.get("digests", []):
        for s in d["sections"]:
            units.append((s["unit_refs"][0] if s["unit_refs"] else "", s["summary"]))
    return units


def _gate(p: Payload) -> Payload:
    terms = key_terms(p["value_statement"])
    units = _unit_texts(p)
    hits = [(ref, text) for ref, text in units if any(t in text.casefold() for t in terms)]
    found = {t for t in terms for _, text in units if t in text.casefold()}
    supported = bool(terms) and len(found) >= min(2, len(terms))
    if not supported:
        substance = "insufficient"
    elif len(hits) >= 3:
        substance = "sufficient"
    else:
        substance = "thin"
    reasons = [f"{len(found)} of {len(terms)} key terms appear in the sources."]
    if not supported:
        reasons.append("The sources do not address the statement's key terms.")
    return {
        "supported": supported,
        "substance": substance,
        "reasons": reasons,
        "evidence": [ref for ref, _ in hits[:8] if ref],
        "suggested_scope": "Synthetic scope: the material is thin." if substance == "thin" else "",
    }


def _discover(p: Payload) -> Payload:
    seen: dict[str, tuple[str, str]] = {}
    for ref, text in _unit_texts(p):
        if ref:
            seen.setdefault(ref.split("/")[0], (ref, text))
    return {
        "candidates": [
            {
                "text": f"Source {sid} indicates: {' '.join(text.split()[:8])}.",
                "audience": p.get("audience_hint") or "synthetic audience",
                "evidence": [ref],
                "confidence_note": "Synthetic candidate.",
            }
            for sid, (ref, text) in list(seen.items())[:5]
        ]
    }


def _digest(p: Payload) -> Payload:
    units = p["units"]
    sections = []
    for i in range(0, len(units), 5):
        chunk = units[i : i + 5]
        sections.append(
            {"summary": f"Synthetic digest: {chunk[0]['text'][:80]}", "unit_refs": [u["ref"] for u in chunk]}
        )
    return {"sections": sections}


def _writer(p: Payload) -> Payload:
    statement = p["value_statement"]
    lexicon = p["lexicon"]
    units = p["units"]
    fixing = bool(p.get("findings"))
    cited = [u for u in units if u["ref"] in set(p.get("gate_evidence", []))] or units[:5]
    claims = [
        {"id": "c0", "text": f"It is likely that {statement}", "kind": "judgment",
         "evidence": [cited[0]["ref"]] if cited else [], "likelihood_term": "likely"}
    ]
    for i, u in enumerate(cited[:5], start=1):
        claims.append({"id": f"c{i}", "text": f"Source states: {u['text'][:120]}", "kind": "fact",
                       "evidence": [u["ref"]], "likelihood_term": None})
    texts = " ".join(u["text"] for u in units)
    if UNSOURCED in texts and (not fixing or UNFIXABLE in texts):
        claims.append({"id": "c99", "text": "An unsourced assertion.", "kind": "fact",
                       "evidence": [], "likelihood_term": None})
    kj_text = statement if (fixing or BADTERM not in texts) else f"{statement} {BADTERM}"
    return {
        "title": f"Synthetic assessment: {statement[:40]}",
        "handling_marking": lexicon["handling_markings"][0],
        "key_judgments": [{"text": kj_text, "confidence": "moderate", "claim_ids": ["c0"]}],
        "scope_note": "Synthetic scope note covering all sources.",
        "sources": [
            {"source_id": s["id"], "descriptor": lexicon["source_descriptors"][0],
             "reliability_note": "Synthetic: current and complete."}
            for s in p["sources"]
        ],
        "analysis": [
            {"heading": "Analysis", "paragraphs": [
                {"text": c["text"], "claim_ids": [c["id"]]} for c in claims
            ]}
        ],
        "alternatives": [{"hypothesis": "The opposite holds.", "assessment": "Less likely.",
                          "claim_ids": []}],
        "gaps_and_indicators": ["Synthetic gap."],
        "claims": claims,
    }


def _conveyor(p: Payload) -> Payload:
    draft = dict(p["draft"])
    if not draft["title"].startswith("Conveyed: "):
        draft["title"] = "Conveyed: " + draft["title"]
    return draft


def _auditor(p: Payload) -> Payload:
    draft = p["draft"]
    unsourced = [c["id"] for c in draft["claims"] if not c["evidence"]]
    badterm = any(BADTERM in kj["text"] for kj in draft["key_judgments"])
    findings = []
    for rule in p["rules"]:
        rid = rule["id"]
        if rule["checkability"] == "advisory":
            verdict, evidence, rec = "attested", "Synthetic attestation.", ""
        elif rid in ("icd203.tc.8", "icd206.src.2") and unsourced:
            verdict, evidence, rec = "fail", f"Claims without evidence: {', '.join(unsourced)}.", "Cite a source unit for each claim or remove it."
        elif rid == "icd203.tc.2" and badterm:
            verdict, evidence, rec = "fail", f"A key judgment uses '{BADTERM}'.", "Use a likelihood term from the lexicon."
        elif rid == "icd203.as.5" and (unsourced or badterm):
            verdict, evidence, rec = "fail", "A tradecraft standard fails.", "Resolve the failing tradecraft findings."
        else:
            verdict, evidence, rec = "pass", "Synthetic check passed.", ""
        findings.append({"rule_id": rid, "verdict": verdict, "evidence": evidence,
                         "cited_units": [], "claim_ids": unsourced if verdict == "fail" else [],
                         "recommendation": rec})
    return {"findings": findings, "summary": "Synthetic audit."}


def _ok(p: Payload) -> Payload:
    return {"ok": True}


_HANDLERS: dict[str, Callable[[Payload], Payload]] = {
    "gate": _gate,
    "discover": _discover,
    "digest": _digest,
    "writer": _writer,
    "conveyor": _conveyor,
    "auditor": _auditor,
    "ping": _ok,
}


def synthetic_response(payload: Payload) -> Payload:
    handler = _HANDLERS.get(payload.get("task", ""))
    if handler is None:
        raise ValueError(f"unknown task '{payload.get('task')}'")
    return handler(payload)


def chat_completion(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }
```

Note the writer handler reads an optional `gate_evidence` list of refs from the payload; Task 12 includes it so the synthetic writer cites the units the gate chose.

- [ ] **Step 5: Write the synthetic tests**

`engine/tests/testing/test_synthetic.py`:

```python
from corelata.schema import AuditOutput, DigestOutput, DiscoveryResult, GateVerdict, ReportBody
from corelata.testing.synthetic import key_terms, synthetic_response

UNITS = [
    {"ref": "src1/u1", "text": "The port of Varna expanded its container capacity in 2025.", "locator": "para 1", "source": "a.txt"},
    {"ref": "src1/u2", "text": "Capacity expansion was financed by a state bank.", "locator": "para 2", "source": "a.txt"},
    {"ref": "src2/u1", "text": "Container traffic through Varna rose 40 percent.", "locator": "para 1", "source": "b.txt"},
]
LEXICON = {"likelihood": [{"term": "likely", "low": 55, "high": 80}],
           "confidence_definitions": {"high": "h", "moderate": "m", "low": "l"},
           "source_descriptors": ["open-source report"], "handling_markings": ["UNCLASSIFIED"]}
SOURCES = [{"id": "src1", "name": "a.txt", "format": "txt", "provenance": {}},
           {"id": "src2", "name": "b.txt", "format": "txt", "provenance": {}}]
RULES = [{"id": "icd203.tc.2", "checkability": "verifiable", "severity": "blocking"},
         {"id": "icd203.tc.8", "checkability": "verifiable", "severity": "blocking"},
         {"id": "icd203.as.1", "checkability": "advisory", "severity": "major"},
         {"id": "icd203.as.5", "checkability": "verifiable", "severity": "major"}]


def writer_payload(units=UNITS, findings=None):
    return {"task": "writer", "value_statement": "Varna port capacity expansion matters to shippers",
            "template": {}, "rules": [], "lexicon": LEXICON, "digests": [], "units": units,
            "sources": SOURCES, "prior_draft": None, "findings": findings or [],
            "extra_guidance": "", "iteration": 1 if findings else 0}


def test_key_terms():
    assert key_terms("The Port of Varna, the port!") == ["port", "varna"]


def test_gate_supported_and_thin_vs_sufficient():
    v = GateVerdict.model_validate(synthetic_response(
        {"task": "gate", "value_statement": "Varna container capacity", "digests": [], "units": UNITS}))
    assert v.supported and v.substance.value == "sufficient" and v.evidence[0] == "src1/u1"
    v2 = GateVerdict.model_validate(synthetic_response(
        {"task": "gate", "value_statement": "Varna container capacity", "digests": [], "units": UNITS[:1]}))
    assert v2.supported and v2.substance.value == "thin" and v2.suggested_scope
    v3 = GateVerdict.model_validate(synthetic_response(
        {"task": "gate", "value_statement": "lunar mining", "digests": [], "units": UNITS}))
    assert not v3.supported and v3.substance.value == "insufficient"


def test_discover_one_candidate_per_source():
    r = DiscoveryResult.model_validate(synthetic_response(
        {"task": "discover", "audience_hint": "ops", "digests": [], "units": UNITS}))
    assert len(r.candidates) == 2 and r.candidates[0].audience == "ops"


def test_digest_groups_by_five():
    units = [{"ref": f"src1/u{i}", "text": f"t{i}"} for i in range(1, 12)]
    d = DigestOutput.model_validate(synthetic_response(
        {"task": "digest", "source": {"id": "src1", "name": "x"}, "units": units}))
    assert [len(s.unit_refs) for s in d.sections] == [5, 5, 1]


def test_writer_valid_and_markers():
    body = ReportBody.model_validate(synthetic_response(writer_payload()))
    assert body.unsourced_claims() == [] and body.handling_marking == "UNCLASSIFIED"
    marked = UNITS + [{"ref": "src2/u2", "text": "UNSOURCED BADTERM here", "locator": "p", "source": "b"}]
    body = ReportBody.model_validate(synthetic_response(writer_payload(marked)))
    assert [c.id for c in body.unsourced_claims()] == ["c99"]
    assert "BADTERM" in body.key_judgments[0].text
    fixed = ReportBody.model_validate(synthetic_response(writer_payload(marked, findings=[{"rule_id": "x"}])))
    assert fixed.unsourced_claims() == [] and "BADTERM" not in fixed.key_judgments[0].text
    stubborn = UNITS + [{"ref": "src2/u2", "text": "UNSOURCED UNFIXABLE", "locator": "p", "source": "b"}]
    still = ReportBody.model_validate(synthetic_response(writer_payload(stubborn, findings=[{"rule_id": "x"}])))
    assert [c.id for c in still.unsourced_claims()] == ["c99"]


def test_conveyor_prefixes_once():
    draft = synthetic_response(writer_payload())
    once = synthetic_response({"task": "conveyor", "draft": draft})
    twice = synthetic_response({"task": "conveyor", "draft": once})
    assert once["title"].startswith("Conveyed: ") and twice["title"] == once["title"]


def test_auditor_one_finding_per_rule():
    draft = synthetic_response(writer_payload(UNITS + [{"ref": "src2/u2", "text": "UNSOURCED BADTERM", "locator": "p", "source": "b"}]))
    out = AuditOutput.model_validate(synthetic_response({"task": "auditor", "draft": draft, "rules": RULES, "lexicon": LEXICON, "cited_units": [], "value_statement": "v"}))
    verdicts = {f.rule_id: f.verdict.value for f in out.findings}
    assert verdicts == {"icd203.tc.2": "fail", "icd203.tc.8": "fail", "icd203.as.1": "attested", "icd203.as.5": "fail"}
    clean = synthetic_response(writer_payload())
    out2 = AuditOutput.model_validate(synthetic_response({"task": "auditor", "draft": clean, "rules": RULES, "lexicon": LEXICON, "cited_units": [], "value_statement": "v"}))
    assert {f.verdict.value for f in out2.findings} == {"pass", "attested"}
```

- [ ] **Step 6: Move the ping prompt, run everything**

```bash
mkdir -p engine/tests/fixtures/prompts/ping
git mv engine/corelata/prompts/templates/ping/v1.j2 engine/tests/fixtures/prompts/ping/v1.j2
```

In `tests/conftest.py`'s `make_runner`, replace `PromptLibrary(cfg.prompts_dir)` with `PromptLibrary(cfg.prompts_dir or Path(__file__).parent / "fixtures" / "prompts")`.

Run: `cd engine && uv run pytest -q`
Expected: all pass, coverage ≥ 95%.

- [ ] **Step 7: Lint, commit**

```bash
make lint
git add -A && git commit -m "feat(prompts): six role prompts, prompt check, synthetic responder"
```

---

### Task 11: Stage context, digests and the gate stage

**Files:**
- Create: `engine/corelata/stages/__init__.py`, `engine/corelata/stages/context.py`, `engine/corelata/stages/digest.py`, `engine/corelata/stages/gate.py`
- Test: `engine/tests/stages/__init__.py`, `engine/tests/stages/conftest.py`, `engine/tests/stages/test_context.py`, `engine/tests/stages/test_digest.py`, `engine/tests/stages/test_gate.py`

**Interfaces (spec §5.4, §7.1, §7.4):**
- `stages.context`: `StageError(Exception)` with `.stage: str`; `estimate_tokens(text: str, bytes_per_token: float) -> int`; `@dataclass StageContext(cfg, runner: AgentRunner, pack: ResolvedPack, sources: list[Source], index: UnitIndex, value_statement: str, digests: dict[str, Digest] = {}, extra_guidance: str = "", gate_evidence: list[str] = [])` with `model_key(role) -> str`, `bytes_per_token(role) -> float`, `unit_payload(refs: list[str]) -> list[dict]` (each `{"ref","text","locator","source"}`), `digest_payload() -> list[dict]`, `source_payload() -> list[dict]`.
- `stages.digest`: `needs_digest(ctx, source) -> bool`; `async run_digests(ctx) -> dict[str, Digest]` (one agent call per oversized source, validator: every unit of the source appears in exactly one section and no foreign refs).
- `stages.gate`: `select_units(ctx, budget_tokens) -> list[str]` (refs of non-digested sources' units ranked by overlap with the statement's key terms, then document order, cut at the budget; digested sources contribute no units); `async run_gate(ctx) -> GateVerdict` (validator: evidence refs exist); `async run_discovery(ctx, audience_hint: str) -> DiscoveryResult` (validator: evidence refs exist).

- [ ] **Step 1: Write the stage test fixtures and failing tests**

`engine/tests/stages/conftest.py`:

```python
import pytest

from corelata.ingest.units import UnitIndex
from corelata.stages.context import StageContext
from corelata.standards.loader import load_pack
from corelata.testing.sources import text_source

PORT = [
    "The port of Varna expanded its container capacity in 2025.",
    "Capacity expansion was financed by a state bank.",
    "Container traffic through Varna rose 40 percent.",
]


@pytest.fixture
def pack():
    return load_pack("icd203-base")


@pytest.fixture
def make_ctx(make_config, make_runner, pack):
    def _make(*sources, statement="Varna port capacity expansion matters to shippers", cfg=None,
              **kw) -> StageContext:
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return StageContext(
            cfg=cfg, runner=make_runner(cfg), pack=pack, sources=sources,
            index=UnitIndex.from_sources(sources), value_statement=statement, **kw,
        )

    return _make
```

`engine/tests/stages/test_context.py`:

```python
from corelata.stages.context import StageError, estimate_tokens
from corelata.testing.sources import text_source


def test_estimate_tokens_rounds_up():
    assert estimate_tokens("abcd", 2.5) == 2
    assert estimate_tokens("", 2.5) == 0
    assert estimate_tokens("é", 2.5) == 1  # 2 bytes


def test_context_payload_helpers(make_ctx):
    ctx = make_ctx(text_source("src1", "alpha", "beta", name="a.txt"))
    assert ctx.model_key("writer") == "model-a" and ctx.bytes_per_token("auditor") == 2.5
    assert ctx.unit_payload(["src1/u2"]) == [
        {"ref": "src1/u2", "text": "beta", "locator": "para 2", "source": "a.txt"}
    ]
    assert ctx.source_payload()[0] == {"id": "src1", "name": "a.txt", "format": "txt", "provenance": {}}
    assert ctx.digest_payload() == []


def test_stage_error_carries_stage():
    e = StageError("gating", "boom")
    assert e.stage == "gating" and str(e) == "gating: boom"
```

`engine/tests/stages/test_digest.py`:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.stages.digest import needs_digest, run_digests
from corelata.testing.sources import text_source


def big_source(n=40):
    return text_source("src1", *[f"Paragraph {i} about Varna port traffic and finance." for i in range(n)])


async def test_small_sources_need_no_digest(make_ctx):
    ctx = make_ctx()
    assert not needs_digest(ctx, ctx.sources[0])
    assert await run_digests(ctx) == {}


async def test_oversized_source_is_digested(make_ctx, make_config):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    ctx = make_ctx(big_source(), cfg=cfg)
    assert needs_digest(ctx, ctx.sources[0])
    digests = await run_digests(ctx)
    d = digests["src1"]
    assert d.source_id == "src1" and len(d.sections) == 8
    covered = [r for s in d.sections for r in s.unit_refs]
    assert covered == ctx.sources[0].refs()
    assert ctx.runner.log.records[0].role == "writer"


async def test_digest_validator_rejects_gaps_and_foreign_refs(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    ctx = make_ctx(big_source(6), cfg=cfg)
    bad = json.dumps({"sections": [{"summary": "s", "unit_refs": ["src1/u1", "src9/u1"]}]})
    fake_backend.script("digest", bad, bad)
    with pytest.raises(StructuredOutputError, match="not covered|unknown"):
        await run_digests(ctx)
```

`engine/tests/stages/test_gate.py`:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Substance
from corelata.stages.gate import run_discovery, run_gate, select_units
from corelata.testing.sources import text_source


def test_select_units_ranks_by_overlap_then_order(make_ctx, make_config):
    ctx = make_ctx(
        text_source("src1", "Nothing relevant here.", "Varna port capacity doubled.", "Weather."),
        text_source("src2", "Shippers welcomed the capacity at Varna."),
    )
    assert select_units(ctx, budget_tokens=10_000) == ["src1/u2", "src2/u1", "src1/u1", "src1/u3"]
    assert select_units(ctx, budget_tokens=12) == ["src1/u2"]


def test_select_units_skips_digested_sources(make_ctx):
    from corelata.schema import Digest, DigestSection
    ctx = make_ctx(text_source("src1", "Varna port."), text_source("src2", "Varna capacity."))
    ctx.digests = {"src2": Digest(source_id="src2", sections=[DigestSection(summary="s", unit_refs=["src2/u1"])])}
    assert select_units(ctx, 10_000) == ["src1/u1"]


async def test_run_gate_supported(make_ctx):
    ctx = make_ctx()
    verdict = await run_gate(ctx)
    assert verdict.supported and verdict.substance is Substance.SUFFICIENT
    assert verdict.evidence and all(ctx.index.has(r) for r in verdict.evidence)
    rec = ctx.runner.log.records[0]
    assert rec.role == "gate" and rec.prompt_id == "gate"
    assert "verify" not in rec.request["messages"][0]["content"].lower() or "supported" in rec.request["messages"][0]["content"]


async def test_run_gate_rejects_unrelated_statement(make_ctx):
    verdict = await run_gate(make_ctx(statement="Lunar helium mining"))
    assert not verdict.supported and verdict.substance is Substance.INSUFFICIENT


async def test_run_gate_validator_rejects_unknown_evidence(make_ctx, fake_backend):
    bad = json.dumps({"supported": True, "substance": "sufficient", "reasons": ["r"],
                      "evidence": ["src7/u1"], "suggested_scope": ""})
    fake_backend.script("gate", bad, bad)
    with pytest.raises(StructuredOutputError, match="unknown unit ref 'src7/u1'"):
        await run_gate(make_ctx())


async def test_run_discovery(make_ctx):
    ctx = make_ctx(text_source("src1", "Varna port grew."), text_source("src2", "Rail link opened."))
    result = await run_discovery(ctx, audience_hint="logistics planners")
    assert len(result.candidates) == 2
    assert result.candidates[0].audience == "logistics planners"
    assert ctx.runner.log.records[0].prompt_id == "discover"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/stages -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `stages/context.py`**

```python
"""What every stage needs, and the payload helpers they share (spec §7.4)."""

import math
from dataclasses import dataclass, field
from typing import Any

from corelata.config import CorelataConfig
from corelata.ingest.units import UnitIndex
from corelata.llm.agent import AgentRunner
from corelata.schema import Digest, Source
from corelata.standards.schema import ResolvedPack


class StageError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


def estimate_tokens(text: str, bytes_per_token: float) -> int:
    return math.ceil(len(text.encode("utf-8")) / bytes_per_token)


@dataclass
class StageContext:
    cfg: CorelataConfig
    runner: AgentRunner
    pack: ResolvedPack
    sources: list[Source]
    index: UnitIndex
    value_statement: str
    digests: dict[str, Digest] = field(default_factory=dict)
    extra_guidance: str = ""
    gate_evidence: list[str] = field(default_factory=list)

    def model_key(self, role: str) -> str:
        return self.cfg.roles.model_for(role)

    def bytes_per_token(self, role: str) -> float:
        return self.cfg.models[self.model_key(role)].bytes_per_token

    def unit_payload(self, refs: list[str]) -> list[dict[str, Any]]:
        out = []
        for ref in refs:
            source, unit = self.index.get(ref)
            out.append({"ref": ref, "text": unit.text, "locator": unit.locator, "source": source.name})
        return out

    def digest_payload(self) -> list[dict[str, Any]]:
        return [d.model_dump() for d in self.digests.values()]

    def source_payload(self) -> list[dict[str, Any]]:
        return [
            {"id": s.id, "name": s.name, "format": s.format, "provenance": s.provenance}
            for s in self.sources
        ]

    def check_refs(self, refs: list[str]) -> list[str]:
        """Validation errors for refs that are not in the index (used by every validator)."""
        return [f"unknown unit ref '{r}'" for r in refs if not self.index.has(r)]
```

- [ ] **Step 4: Write `stages/digest.py`**

```python
"""Digests for sources too long to show a model in full (spec §5.4). The writer role
summarises; the digest is traced like any stage output."""

from corelata.schema import Digest, DigestOutput, Source
from corelata.stages.context import StageContext, estimate_tokens


def needs_digest(ctx: StageContext, source: Source) -> bool:
    text = "\n".join(u.text for u in source.units)
    return estimate_tokens(text, ctx.bytes_per_token("writer")) > ctx.cfg.pipeline.digest_threshold_tokens


def _validator(source: Source):
    expected = source.refs()

    def validate(out: DigestOutput) -> list[str]:
        errors: list[str] = []
        seen: list[str] = []
        for s in out.sections:
            for r in s.unit_refs:
                if r not in expected:
                    errors.append(f"unknown ref '{r}' for source {source.id}")
                elif r in seen:
                    errors.append(f"ref '{r}' appears in more than one section")
                seen.append(r)
        missing = [r for r in expected if r not in seen]
        if missing:
            errors.append(f"units not covered: {', '.join(missing[:5])}")
        return errors

    return validate


async def run_digests(ctx: StageContext) -> dict[str, Digest]:
    digests: dict[str, Digest] = {}
    for source in ctx.sources:
        if not needs_digest(ctx, source):
            continue
        out = await ctx.runner.run(
            role="writer",
            model_key=ctx.model_key("writer"),
            prompt_id="digest",
            prompt_vars={},
            payload={
                "task": "digest",
                "source": {"id": source.id, "name": source.name},
                "units": [{"ref": r, "text": u.text} for r, u in zip(source.refs(), source.units, strict=True)],
            },
            output_type=DigestOutput,
            validate=_validator(source),
        )
        digests[source.id] = Digest(source_id=source.id, sections=out.sections)
    return digests
```

- [ ] **Step 5: Write `stages/gate.py`**

```python
"""The value gate (spec §7.1, §7.2): verify the analyst's statement, or propose statements."""

from corelata.schema import DiscoveryResult, GateVerdict
from corelata.stages.context import StageContext, estimate_tokens
from corelata.testing.synthetic import key_terms


def select_units(ctx: StageContext, budget_tokens: int) -> list[str]:
    """Refs of units from non-digested sources, ranked by overlap with the statement's key
    terms (then document order), cut when the budget is spent."""
    terms = key_terms(ctx.value_statement)
    ranked: list[tuple[int, int, str]] = []
    position = 0
    for source in ctx.sources:
        if source.id in ctx.digests:
            continue
        for ref, unit in zip(source.refs(), source.units, strict=True):
            folded = unit.text.casefold()
            overlap = sum(1 for t in terms if t in folded)
            ranked.append((-overlap, position, ref))
            position += 1
    ranked.sort()
    chosen: list[str] = []
    spent = 0
    bpt = ctx.bytes_per_token("gate")
    for _, _, ref in ranked:
        cost = estimate_tokens(ctx.index.text(ref), bpt)
        if chosen and spent + cost > budget_tokens:
            break
        chosen.append(ref)
        spent += cost
    return chosen


async def run_gate(ctx: StageContext) -> GateVerdict:
    refs = select_units(ctx, ctx.cfg.pipeline.gate_unit_budget_tokens)
    return await ctx.runner.run(
        role="gate",
        model_key=ctx.model_key("gate"),
        prompt_id="gate",
        prompt_vars={"mode": "verify", "tone": ctx.pack.tone},
        payload={
            "task": "gate",
            "value_statement": ctx.value_statement,
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(refs),
        },
        output_type=GateVerdict,
        validate=lambda v: ctx.check_refs(v.evidence),
    )


async def run_discovery(ctx: StageContext, audience_hint: str = "") -> DiscoveryResult:
    refs = select_units(ctx, ctx.cfg.pipeline.gate_unit_budget_tokens)
    return await ctx.runner.run(
        role="gate",
        model_key=ctx.model_key("gate"),
        prompt_id="discover",
        prompt_vars={"audience_hint": audience_hint, "tone": ctx.pack.tone},
        payload={
            "task": "discover",
            "audience_hint": audience_hint,
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(refs),
        },
        output_type=DiscoveryResult,
        validate=lambda r: ctx.check_refs([e for c in r.candidates for e in c.evidence]),
    )
```

`key_terms` lives in `testing/synthetic.py` because the fake needs the same tokenisation; move it to `corelata/text.py` as `key_terms(statement) -> list[str]` and import it from there in both places, so production code never imports `testing`. Add a test for it in `tests/test_text.py`:

```python
def test_key_terms_dedupes_and_folds():
    assert key_terms("The Port of Varna, the port!") == ["port", "varna"]
```

- [ ] **Step 6: Run**

Run: `cd engine && uv run pytest tests/stages tests/test_text.py -q --no-cov`
Expected: all pass. In `test_select_units_ranks_by_overlap_then_order`, the terms are `varna, port, capacity, expansion, matters, shippers`; `src1/u2` matches 3, `src2/u1` matches 3 but comes later in order, so `src1/u2` first; the second call's budget of 12 tokens fits only the first unit (`"Varna port capacity doubled."` is 28 bytes → 12 tokens).

- [ ] **Step 7: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(stages): stage context, digests, value gate and discovery"
```

---

### Task 12: Writer and conveyor stages

**Files:**
- Create: `engine/corelata/stages/write.py`, `engine/corelata/stages/convey.py`
- Test: `engine/tests/stages/test_write.py`, `engine/tests/stages/test_convey.py`

**Interfaces (spec §4.4, §7.4):**
- `stages.write`: `report_validator(ctx) -> Callable[[ReportBody], list[str]]` checking (a) every evidence ref exists in the index, (b) `handling_marking` is in the lexicon's allowed list, (c) every source in `ctx.sources` has a `SourceEntry`, (d) key judgment count within template limits; `async run_writer(ctx, *, iteration: int, prior: ReportBody | None, findings: list[Finding]) -> ReportBody`.
- `stages.convey`: `conveyor_validator(ctx, draft) -> Callable[[ReportBody], list[str]]` checking the writer's rules plus (e) the claim id set is unchanged, (f) no claim lost evidence, (g) no claim changed kind; `async run_conveyor(ctx, *, iteration: int, draft: ReportBody, findings: list[Finding]) -> ReportBody`.
- Payloads carry `findings` as `[f.model_dump() for f in findings]` and the rules as `[r.model_dump() for r in ctx.pack.rules_for(role)]`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/stages/test_write.py`:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Finding, FindingOut, Verdict
from corelata.stages.write import run_writer
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


async def test_writer_first_draft(make_ctx):
    ctx = make_ctx()
    ctx.gate_evidence = ["src1/u1", "src1/u3"]
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.title.startswith("Synthetic assessment")
    assert {c.evidence[0] for c in body.claims if c.kind.value == "fact"} == {"src1/u1", "src1/u3"}
    assert [s.source_id for s in body.sources] == ["src1"]
    rec = ctx.runner.log.records[0]
    assert rec.role == "writer" and rec.prompt_id == "writer"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert payload["iteration"] == 0 and payload["prior_draft"] is None
    assert [r["id"] for r in payload["rules"]] == [r.id for r in ctx.pack.rules_for("writer")]
    assert payload["gate_evidence"] == ["src1/u1", "src1/u3"]


async def test_writer_revision_receives_prior_and_findings(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED detail."))
    first = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert first.unsourced_claims()
    finding = Finding(
        **FindingOut(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="c99").model_dump(),
        severity="blocking", route_to="writer", iteration=0,
    )
    second = await run_writer(ctx, iteration=1, prior=first, findings=[finding])
    assert second.unsourced_claims() == []
    payload = json.loads(ctx.runner.log.records[1].request["messages"][1]["content"].split("\n", 1)[1])
    assert payload["prior_draft"]["title"] == first.title
    assert payload["findings"][0]["rule_id"] == "icd203.tc.8"
    assert "prior_draft" in ctx.runner.log.records[1].request["messages"][0]["content"]


async def test_writer_validator_rejects_unknown_ref_then_fails(make_ctx, fake_backend):
    ctx = make_ctx()
    good = json.loads(json.dumps(__import__("corelata.testing.synthetic", fromlist=["x"]).synthetic_response(
        {"task": "writer", "value_statement": ctx.value_statement, "template": {}, "rules": [],
         "lexicon": ctx.pack.lexicon.model_dump(), "digests": [], "units": ctx.unit_payload(ctx.index.refs()),
         "sources": ctx.source_payload(), "prior_draft": None, "findings": [], "extra_guidance": "",
         "iteration": 0})))
    good["claims"][0]["evidence"] = ["src9/u1"]
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError, match="unknown unit ref 'src9/u1'"):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert [r.ok for r in ctx.runner.log.records] == [False, False]


async def test_writer_validator_checks_marking_sources_and_limits(make_ctx, fake_backend):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."))
    from corelata.testing.synthetic import synthetic_response
    base = synthetic_response(
        {"task": "writer", "value_statement": ctx.value_statement, "template": {}, "rules": [],
         "lexicon": ctx.pack.lexicon.model_dump(), "digests": [], "units": ctx.unit_payload(ctx.index.refs()),
         "sources": ctx.source_payload(), "prior_draft": None, "findings": [], "extra_guidance": "",
         "iteration": 0})
    wrong = dict(base)
    wrong["handling_marking"] = "SECRET"
    wrong["sources"] = base["sources"][:1]
    wrong["key_judgments"] = base["key_judgments"] * 6
    fake_backend.script("writer", json.dumps(wrong))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[1].messages[3].content
    assert "handling marking 'SECRET'" in repair
    assert "source 'src2' has no entry" in repair
    assert "key judgments: 6 (allowed 1-5)" in repair
    assert body.handling_marking == "UNCLASSIFIED"
```

`engine/tests/stages/test_convey.py`:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.stages.convey import run_conveyor
from corelata.stages.write import run_writer


async def test_conveyor_edits_and_keeps_claims(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert out.title == "Conveyed: " + draft.title
    assert out.claims == draft.claims
    rec = ctx.runner.log.records[1]
    assert rec.role == "conveyor" and rec.prompt_id == "conveyor"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert [r["id"] for r in payload["rules"]] == [r.id for r in ctx.pack.rules_for("conveyor")]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["claims"].pop(), "claim set changed"),
        (lambda d: d["claims"][1].__setitem__("evidence", []), "claim 'c1' lost evidence"),
        (lambda d: d["claims"][1].__setitem__("kind", "judgment"), "claim 'c1' changed kind"),
    ],
)
async def test_conveyor_validator_guards_claims(make_ctx, fake_backend, mutate, message):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    mutate(data)
    if message == "claim set changed":
        for section in data["analysis"]:
            section["paragraphs"] = [p for p in section["paragraphs"] if p["claim_ids"] != [draft.claims[-1].id]]
    bad = json.dumps(data)
    fake_backend.script("conveyor", bad, bad)
    with pytest.raises(StructuredOutputError, match=message):
        await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/stages/test_write.py tests/stages/test_convey.py -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `stages/write.py`**

```python
"""The writer (spec §4.4): structured report from template, rules and cited units."""

from collections.abc import Callable

from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext


def report_validator(ctx: StageContext) -> Callable[[ReportBody], list[str]]:
    allowed_markings = set(ctx.pack.lexicon.handling_markings)
    limits = ctx.pack.template.key_judgments
    source_ids = [s.id for s in ctx.sources]

    def validate(body: ReportBody) -> list[str]:
        errors = ctx.check_refs([r for c in body.claims for r in c.evidence])
        if body.handling_marking not in allowed_markings:
            errors.append(
                f"handling marking '{body.handling_marking}' is not allowed "
                f"(allowed: {', '.join(sorted(allowed_markings))})"
            )
        listed = {s.source_id for s in body.sources}
        errors += [f"source '{sid}' has no entry in sources" for sid in source_ids if sid not in listed]
        n = len(body.key_judgments)
        if not limits.min <= n <= limits.max:
            errors.append(f"key judgments: {n} (allowed {limits.min}-{limits.max})")
        return errors

    return validate


def _cited_refs(ctx: StageContext) -> list[str]:
    """Full text the writer sees: the gate's evidence, else every unit of non-digested sources."""
    if ctx.gate_evidence:
        return [r for r in ctx.gate_evidence if ctx.index.has(r)]
    return [r for s in ctx.sources if s.id not in ctx.digests for r in s.refs()]


async def run_writer(
    ctx: StageContext, *, iteration: int, prior: ReportBody | None, findings: list[Finding]
) -> ReportBody:
    return await ctx.runner.run(
        role="writer",
        model_key=ctx.model_key("writer"),
        prompt_id="writer",
        prompt_vars={
            "tone": ctx.pack.tone,
            "section_order": ctx.pack.template.section_order,
            "iteration": iteration,
            "extra_guidance": ctx.extra_guidance,
        },
        payload={
            "task": "writer",
            "value_statement": ctx.value_statement,
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("writer")],
            "lexicon": ctx.pack.lexicon.model_dump(),
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(_cited_refs(ctx)),
            "gate_evidence": list(ctx.gate_evidence),
            "sources": ctx.source_payload(),
            "prior_draft": None if prior is None else prior.model_dump(),
            "findings": [f.model_dump() for f in findings],
            "extra_guidance": ctx.extra_guidance,
            "iteration": iteration,
        },
        output_type=ReportBody,
        validate=report_validator(ctx),
    )
```

- [ ] **Step 4: Write `stages/convey.py`**

```python
"""The conveyance reviewer (spec §4.4): edits for the reader, may not touch evidence."""

from collections.abc import Callable

from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext
from corelata.stages.write import report_validator


def conveyor_validator(ctx: StageContext, draft: ReportBody) -> Callable[[ReportBody], list[str]]:
    base = report_validator(ctx)
    before = {c.id: c for c in draft.claims}

    def validate(body: ReportBody) -> list[str]:
        errors = base(body)
        after = {c.id: c for c in body.claims}
        if set(after) != set(before):
            errors.append("claim set changed: the reviewer may reword claims, not add or remove them")
        for cid, c in after.items():
            prev = before.get(cid)
            if prev is None:
                continue
            if set(prev.evidence) - set(c.evidence):
                errors.append(f"claim '{cid}' lost evidence")
            if prev.kind is not c.kind:
                errors.append(f"claim '{cid}' changed kind")
        return errors

    return validate


async def run_conveyor(
    ctx: StageContext, *, iteration: int, draft: ReportBody, findings: list[Finding]
) -> ReportBody:
    return await ctx.runner.run(
        role="conveyor",
        model_key=ctx.model_key("conveyor"),
        prompt_id="conveyor",
        prompt_vars={
            "tone": ctx.pack.tone,
            "heading_style": ctx.pack.format.heading_style,
            "findings": [f.model_dump() for f in findings],
        },
        payload={
            "task": "conveyor",
            "draft": draft.model_dump(),
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("conveyor")],
            "tone": ctx.pack.tone,
            "findings": [f.model_dump() for f in findings],
            "iteration": iteration,
        },
        output_type=ReportBody,
        validate=conveyor_validator(ctx, draft),
    )
```

- [ ] **Step 5: Run**

Run: `cd engine && uv run pytest tests/stages -q --no-cov`
Expected: all pass.

- [ ] **Step 6: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(stages): writer and conveyance reviewer with claim guards"
```

---

### Task 13: Auditor stage and the loop decision

**Files:**
- Create: `engine/corelata/stages/audit.py`
- Test: `engine/tests/stages/test_audit.py`, `engine/tests/stages/test_decide_next.py`

**Interfaces (spec §6.2, §7.2, §7.3, §8.2):**
- `stages.audit`: `audit_validator(ctx) -> Callable[[AuditOutput], list[str]]` checking exactly one finding per rule id in `ctx.pack.rules` (no extras, no missing), that advisory rules get `ATTESTED` or `NOT_APPLICABLE` and verifiable rules never get `ATTESTED`, and that `cited_units` exist; `async run_auditor(ctx, *, iteration: int, draft: ReportBody) -> list[Finding]` (engine fills `severity`, `route_to`, `iteration` from the rule; the auditor sees cited units' full text); `open_findings(findings) -> list[Finding]` (verdict FAIL with severity blocking or major); `decide_next(findings: list[Finding], iteration: int, max_iterations: int) -> Literal["drafting", "conveying", "rendering"]`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/stages/test_audit.py`:

```python
import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Verdict
from corelata.stages.audit import open_findings, run_auditor
from corelata.stages.write import run_writer
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


async def test_clean_draft_passes(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    findings = await run_auditor(ctx, iteration=0, draft=draft)
    assert [f.rule_id for f in findings] == ctx.pack.rule_ids()
    assert all(f.iteration == 0 for f in findings)
    assert {f.verdict for f in findings} == {Verdict.PASS, Verdict.ATTESTED}
    assert open_findings(findings) == []
    tc8 = next(f for f in findings if f.rule_id == "icd203.tc.8")
    assert tc8.severity == "blocking" and tc8.route_to == "writer"
    rec = ctx.runner.log.records[-1]
    assert rec.role == "auditor"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert {u["ref"] for u in payload["cited_units"]} == {r for c in draft.claims for r in c.evidence}
    assert "severity" in payload["rules"][0] and "route_to" not in payload["rules"][0]


async def test_marked_draft_fails_with_routing(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED BADTERM"))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    findings = await run_auditor(ctx, iteration=0, draft=draft)
    failed = {f.rule_id for f in open_findings(findings)}
    assert failed == {"icd203.tc.2", "icd203.tc.8", "icd206.src.2", "icd203.as.5"}
    assert all(f.route_to == "writer" for f in open_findings(findings))


async def test_validator_requires_one_finding_per_rule(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    bad = json.dumps({"findings": [{"rule_id": "icd203.tc.8", "verdict": "pass", "evidence": "e"}],
                      "summary": "s"})
    fake_backend.script("auditor", bad, bad)
    with pytest.raises(StructuredOutputError, match="missing finding for rule 'icd203.as.1'"):
        await run_auditor(ctx, iteration=0, draft=draft)


async def test_validator_rejects_attested_verifiable_and_unknown_rule(make_ctx, fake_backend):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    findings = [{"rule_id": r.id, "verdict": "attested", "evidence": "e"} for r in ctx.pack.rules]
    findings.append({"rule_id": "zzz.x.1", "verdict": "pass", "evidence": "e"})
    bad = json.dumps({"findings": findings, "summary": "s"})
    fake_backend.script("auditor", bad, bad)
    with pytest.raises(StructuredOutputError) as e:
        await run_auditor(ctx, iteration=0, draft=draft)
    msg = str(e.value)
    assert "verifiable rule 'icd203.tc.8' cannot be attested" in msg
    assert "unknown rule 'zzz.x.1'" in msg
```

`engine/tests/stages/test_decide_next.py`:

```python
import pytest

from corelata.schema import Finding, FindingOut, Verdict
from corelata.stages.audit import decide_next


def f(rule, verdict=Verdict.FAIL, severity="blocking", route_to="writer", iteration=0):
    return Finding(**FindingOut(rule_id=rule, verdict=verdict, evidence="e").model_dump(),
                   severity=severity, route_to=route_to, iteration=iteration)


def test_clean_renders():
    assert decide_next([f("a.b.1", Verdict.PASS)], 0, 2) == "rendering"


def test_minor_failures_never_loop():
    assert decide_next([f("a.b.1", severity="minor")], 0, 2) == "rendering"


def test_blocking_routes_to_writer_and_conveyor_only_to_conveyor():
    assert decide_next([f("a.b.1", route_to="conveyor")], 0, 2) == "conveying"
    assert decide_next([f("a.b.1", route_to="conveyor"), f("a.b.2", route_to="writer")], 0, 2) == "drafting"


def test_budget_exhausted_renders():
    assert decide_next([f("a.b.1")], 2, 2) == "rendering"
    assert decide_next([f("a.b.1")], 0, 0) == "rendering"


@pytest.mark.parametrize("severity", ["blocking", "major"])
def test_major_and_blocking_loop_while_budget(severity):
    assert decide_next([f("a.b.1", severity=severity)], 1, 2) == "drafting"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/stages/test_audit.py tests/stages/test_decide_next.py -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `stages/audit.py`**

```python
"""The compliance auditor (spec §8.2) and the engine-owned loop decision (spec §6.2, §7.3).
The auditor returns findings only; severity and routing come from the rule, never the model."""

from collections.abc import Callable
from typing import Literal

from corelata.schema import AuditOutput, Finding, ReportBody, Verdict
from corelata.stages.context import StageContext
from corelata.standards.schema import Checkability, Severity

LOOPING = {Severity.BLOCKING.value, Severity.MAJOR.value}
Next = Literal["drafting", "conveying", "rendering"]


def audit_validator(ctx: StageContext) -> Callable[[AuditOutput], list[str]]:
    rules = {r.id: r for r in ctx.pack.rules}

    def validate(out: AuditOutput) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for f in out.findings:
            rule = rules.get(f.rule_id)
            if rule is None:
                errors.append(f"unknown rule '{f.rule_id}'")
                continue
            if f.rule_id in seen:
                errors.append(f"more than one finding for rule '{f.rule_id}'")
            seen.add(f.rule_id)
            if rule.checkability is Checkability.VERIFIABLE and f.verdict is Verdict.ATTESTED:
                errors.append(f"verifiable rule '{f.rule_id}' cannot be attested: pass or fail it")
            if rule.checkability is Checkability.ADVISORY and f.verdict in (Verdict.PASS, Verdict.FAIL):
                errors.append(f"advisory rule '{f.rule_id}' is attested, not passed or failed")
            errors += ctx.check_refs(f.cited_units)
        errors += [f"missing finding for rule '{rid}'" for rid in rules if rid not in seen]
        return errors

    return validate


async def run_auditor(ctx: StageContext, *, iteration: int, draft: ReportBody) -> list[Finding]:
    cited = sorted({r for c in draft.claims for r in c.evidence if ctx.index.has(r)})
    out = await ctx.runner.run(
        role="auditor",
        model_key=ctx.model_key("auditor"),
        prompt_id="auditor",
        prompt_vars={},
        payload={
            "task": "auditor",
            "draft": draft.model_dump(),
            "rules": [
                {"id": r.id, "title": r.title, "text": r.text, "severity": r.severity.value,
                 "checkability": r.checkability.value, "evidence_required": r.evidence_required}
                for r in ctx.pack.rules
            ],
            "lexicon": ctx.pack.lexicon.model_dump(),
            "cited_units": [{"ref": r, "text": ctx.index.text(r)} for r in cited],
            "value_statement": ctx.value_statement,
        },
        output_type=AuditOutput,
        validate=audit_validator(ctx),
    )
    by_id = {f.rule_id: f for f in out.findings}
    return [
        Finding(
            **by_id[r.id].model_dump(),
            severity=r.severity.value,
            route_to=r.route_to.value,
            iteration=iteration,
        )
        for r in ctx.pack.rules
    ]


def open_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.verdict is Verdict.FAIL and f.severity in LOOPING]


def decide_next(findings: list[Finding], iteration: int, max_iterations: int) -> Next:
    """Spec §6.2 and §7.3: blocking and major failures loop while budget remains; the writer
    is re-run if any failure is routed to it, else only the conveyor."""
    open_ = open_findings(findings)
    if not open_ or iteration >= max_iterations:
        return "rendering"
    if any(f.route_to == "writer" for f in open_):
        return "drafting"
    return "conveying"
```

- [ ] **Step 4: Run**

Run: `cd engine && uv run pytest tests/stages -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(stages): auditor with per-rule validation and loop decision"
```

---

### Task 14: The pipeline (state machine, loop, trace record)

**Files:**
- Create: `engine/corelata/pipeline.py`
- Test: `engine/tests/test_pipeline.py`

**Interfaces (spec §7.2, §7.5, §8.3):**
- `pipeline.RunOptions(value_statement: str, profile: str | None = None, max_iterations: int | None = None, extra_guidance: str = "", run_id: str | None = None)`.
- `async pipeline.run_report(cfg, sources: list[Source], options, *, backends, prompts, log, pack: ResolvedPack | None = None, now: Callable[[], datetime] = utcnow) -> RunRecord`. Never raises for model or validation failures: those end in `state=FAILED` with `error` set. Raises `ValueError` for an empty source list or a blank value statement (the CLI turns these into exit 2).
- `async pipeline.discover(cfg, sources, *, backends, prompts, log, audience_hint="", pack=None) -> DiscoveryResult`.
- `pipeline.load_run_pack(cfg, profile) -> ResolvedPack` (uses `cfg.standards`).
- Behaviour: states advance as in §7.2; every stage appends a `StageResult`; each writer/conveyor output appends a `DraftRecord`; all findings from every iteration are kept; oversize errors (`OVERSIZE_ERRORS`) in any stage halve `digest_threshold_tokens` once, regenerate digests and retry the stage, then fail; any other `AGENT_FAILURES` retry the stage once, then fail; the final report's metadata carries `status`, `iteration` and `open_findings` ids; `RunRecord.status` mirrors it; `gate_rejected` leaves `report=None` and `gate` set.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_pipeline.py`:

```python
import json
from datetime import UTC, datetime

import pytest

from corelata.llm.agent import CallLog
from corelata.llm.types import ContextOverflowError, PermanentBackendError
from corelata.pipeline import RunOptions, discover, run_report
from corelata.prompts.library import PromptLibrary
from corelata.schema import ReportStatus, RunState
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


@pytest.fixture
def run(make_config, fake_backend):
    async def _run(*sources, statement="Varna port capacity expansion matters to shippers",
                   cfg=None, **opts):
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return await run_report(
            cfg, sources, RunOptions(value_statement=statement, **opts),
            backends={"fake": fake_backend}, prompts=PromptLibrary(), log=CallLog(),
            now=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        )

    return _run


async def test_clean_run_completes(run):
    rec = await run(run_id="r1")
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.CLEAN
    assert rec.run_id == "r1" and rec.iterations == 0
    assert [s.stage for s in rec.stages] == ["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]
    assert all(s.ok for s in rec.stages)
    assert [d.role for d in rec.drafts] == ["writer", "conveyor"]
    assert rec.report is not None and rec.report.metadata.status is ReportStatus.CLEAN
    assert rec.report.metadata.pack_name == "icd203-base" and rec.report.metadata.open_findings == []
    assert rec.report.title.startswith("Conveyed: ")
    assert len(rec.findings) == 17 and rec.usage.calls == 4
    assert set(rec.prompt_versions) == {"gate", "discover", "digest", "writer", "conveyor", "auditor"}
    assert rec.pack_snapshot["name"] == "icd203-base" and len(rec.pack_hash) == 16
    assert rec.llm_calls[0].role == "gate"


async def test_findings_loop_once_then_clean(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED detail."))
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.CLEAN
    assert rec.iterations == 1
    assert [s.stage for s in rec.stages] == ["ingesting", "gating", "drafting", "conveying", "auditing",
                                             "drafting", "conveying", "auditing", "rendering"]
    assert [d.iteration for d in rec.drafts] == [0, 0, 1, 1]
    assert {f.iteration for f in rec.findings} == {0, 1}
    assert rec.report.unsourced_claims() == []


async def test_unfixable_findings_deliver_with_findings_open(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED UNFIXABLE detail."))
    assert rec.state is RunState.COMPLETED and rec.status is ReportStatus.FINDINGS_OPEN
    assert rec.iterations == 2
    assert rec.report.metadata.status is ReportStatus.FINDINGS_OPEN
    assert "icd203.tc.8@2" in rec.report.metadata.open_findings
    assert rec.report.unsourced_claims()


async def test_max_iterations_zero_audits_once(run):
    rec = await run(text_source("src1", *PORT, "UNSOURCED detail."), max_iterations=0)
    assert rec.iterations == 0 and rec.status is ReportStatus.FINDINGS_OPEN
    assert [s.stage for s in rec.stages].count("auditing") == 1


async def test_gate_rejected(run):
    rec = await run(statement="Lunar helium mining")
    assert rec.state is RunState.GATE_REJECTED and rec.report is None
    assert rec.gate is not None and not rec.gate.supported
    assert [s.stage for s in rec.stages] == ["ingesting", "gating"]
    assert rec.usage.calls == 1


async def test_thin_substance_passes_scope_to_writer(run, fake_backend):
    rec = await run(text_source("src1", PORT[0]))
    assert rec.state is RunState.COMPLETED
    assert rec.gate.substance.value == "thin"
    writer_req = next(r for r in fake_backend.requests if '"task": "writer"' in r.messages[1].content)
    payload = json.loads(writer_req.messages[1].content.split("\n", 1)[1])
    assert "thin" in payload["extra_guidance"]


async def test_permanent_failure_is_recorded_not_raised(run, fake_backend):
    fake_backend.script("writer", PermanentBackendError("down"), PermanentBackendError("down"))
    rec = await run()
    assert rec.state is RunState.FAILED and "down" in rec.error
    failed = [s for s in rec.stages if not s.ok]
    assert failed[-1].stage == "drafting" and "down" in failed[-1].error
    assert rec.report is None


async def test_oversize_halves_digest_threshold_and_retries(run, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 600})
    big = text_source("src1", *[f"Paragraph {i} on Varna port capacity for shippers." for i in range(40)])
    fake_backend.script("gate", ContextOverflowError("too long"))
    rec = await run(big, cfg=cfg)
    assert rec.state is RunState.COMPLETED
    assert rec.digests and rec.digests[0].source_id == "src1"
    gating = [s for s in rec.stages if s.stage == "gating"]
    assert [s.ok for s in gating] == [False, True]


async def test_second_oversize_fails(run, make_config, fake_backend):
    fake_backend.script("gate", ContextOverflowError("a"), ContextOverflowError("b"))
    rec = await run()
    assert rec.state is RunState.FAILED and "context" in rec.error.lower() or "b" in rec.error


async def test_empty_inputs_are_usage_errors(make_config, fake_backend):
    cfg = make_config()
    with pytest.raises(ValueError, match="at least one source"):
        await run_report(cfg, [], RunOptions(value_statement="x"), backends={"fake": fake_backend},
                         prompts=PromptLibrary(), log=CallLog())
    with pytest.raises(ValueError, match="value statement"):
        await run_report(cfg, [text_source("src1", "a")], RunOptions(value_statement="  "),
                         backends={"fake": fake_backend}, prompts=PromptLibrary(), log=CallLog())


async def test_discover(make_config, fake_backend):
    result = await discover(
        make_config(), [text_source("src1", "Varna port grew."), text_source("src2", "Rail link.")],
        backends={"fake": fake_backend}, prompts=PromptLibrary(), log=CallLog(), audience_hint="ops",
    )
    assert len(result.candidates) == 2 and result.candidates[0].audience == "ops"


async def test_profile_flows_into_metadata(run, make_config, tmp_path):
    import yaml
    pack = tmp_path / "icd203-base"
    pack.mkdir()
    (pack / "pack.yaml").write_text(yaml.safe_dump({"name": "icd203-base", "version": "9"}))
    (pack / "rules").mkdir()
    import shutil
    from corelata.standards.loader import BUILTIN_PACKS_DIR
    for f in (BUILTIN_PACKS_DIR / "icd203-base").iterdir():
        if f.name != "pack.yaml":
            (shutil.copytree if f.is_dir() else shutil.copy)(f, pack / f.name, dirs_exist_ok=True) if f.is_dir() else shutil.copy(f, pack / f.name)
    (pack / "profiles").mkdir()
    (pack / "profiles" / "east.yaml").write_text(yaml.safe_dump({"name": "east", "extends": "icd203-base", "tone": "Terse."}))
    cfg = make_config(standards={"packs_dir": str(tmp_path)})
    rec = await run(cfg=cfg, profile="east")
    assert rec.profile == "east" and rec.report.metadata.profile == "east"
    assert rec.pack_snapshot["tone"] == "Terse."
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/test_pipeline.py -q --no-cov`
Expected: ImportError for `corelata.pipeline`.

- [ ] **Step 3: Write `pipeline.py`**

```python
"""The run: gate → writer → conveyor → auditor with one bounded loop (spec §7). Model and
validation failures end the run in `failed` with the error recorded; they never raise."""

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from corelata import __version__
from corelata.config import CorelataConfig, config_hash
from corelata.ingest.units import UnitIndex
from corelata.llm.agent import AGENT_FAILURES, AgentRunner, CallLog
from corelata.llm.types import OVERSIZE_ERRORS, Backend
from corelata.prompts.check import run_prompt_ids
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    DiscoveryResult, DraftRecord, Finding, Report, ReportBody, ReportMetadata, ReportStatus,
    RunRecord, RunState, Source, StageResult, Substance,
)
from corelata.stages.audit import decide_next, open_findings, run_auditor
from corelata.stages.context import StageContext
from corelata.stages.convey import run_conveyor
from corelata.stages.digest import run_digests
from corelata.stages.gate import run_discovery, run_gate
from corelata.stages.write import run_writer
from corelata.standards.loader import load_pack, pack_hash
from corelata.standards.schema import ResolvedPack


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunOptions:
    value_statement: str
    profile: str | None = None
    max_iterations: int | None = None
    extra_guidance: str = ""
    run_id: str | None = None


def load_run_pack(cfg: CorelataConfig, profile: str | None) -> ResolvedPack:
    return load_pack(
        cfg.standards.default_pack,
        packs_dir=cfg.standards.packs_dir,
        profile=profile or cfg.standards.default_profile,
    )


class _Run:
    """One execution; holds the record and the mutable context."""

    def __init__(
        self, cfg: CorelataConfig, sources: list[Source], options: RunOptions, *,
        backends: dict[str, Backend], prompts: PromptLibrary, log: CallLog,
        pack: ResolvedPack, now: Callable[[], datetime],
    ) -> None:
        self.now = now
        self.log = log
        self.ctx = StageContext(
            cfg=cfg, runner=AgentRunner(cfg, backends, prompts, log), pack=pack,
            sources=sources, index=UnitIndex.from_sources(sources),
            value_statement=options.value_statement.strip(), extra_guidance=options.extra_guidance,
        )
        self.max_iterations = (
            cfg.pipeline.max_iterations if options.max_iterations is None else options.max_iterations
        )
        self.record = RunRecord(
            corelata_version=__version__,
            run_id=options.run_id or secrets.token_hex(6),
            created_at=now(),
            value_statement=self.ctx.value_statement,
            profile=pack.profile,
            pack_name=pack.name,
            pack_hash=pack_hash(pack),
            pack_snapshot=pack.model_dump(mode="json"),
            config_hash=config_hash(cfg),
            prompt_versions=prompts.versions(run_prompt_ids()),
            sources=sources,
            max_iterations=self.max_iterations,
            usage=log.usage(),
        )
        self.halved = False

    async def stage[T](
        self, state: RunState, iteration: int, fn: Callable[[], Awaitable[T]],
        output: Callable[[T], dict[str, Any] | None] = lambda r: None,
    ) -> T:
        """Run one stage with the spec §7.5 retry ladder; record every attempt."""
        self.record.state = state
        attempts = 0
        while True:
            started = self.now()
            attempts += 1
            try:
                result = await fn()
            except OVERSIZE_ERRORS as e:
                self._record_stage(state, iteration, started, error=str(e))
                if self.halved:
                    raise
                self.halved = True
                self.ctx.cfg = self.ctx.cfg.model_copy(
                    update={"pipeline": self.ctx.cfg.pipeline.model_copy(update={
                        "digest_threshold_tokens": max(500, self.ctx.cfg.pipeline.digest_threshold_tokens // 2)
                    })}
                )
                self.ctx.runner.cfg = self.ctx.cfg
                self.ctx.digests = await run_digests(self.ctx)
                self.record.digests = list(self.ctx.digests.values())
                continue
            except AGENT_FAILURES as e:
                self._record_stage(state, iteration, started, error=str(e))
                if attempts >= 2:
                    raise
                continue
            self._record_stage(state, iteration, started, output=output(result))
            return result

    def _record_stage(
        self, state: RunState, iteration: int, started: datetime, *,
        output: dict[str, Any] | None = None, error: str | None = None,
    ) -> None:
        self.record.stages.append(
            StageResult(stage=state.value, iteration=iteration, ok=error is None, output=output,
                        error=error, started_at=started, finished_at=self.now())
        )

    async def execute(self) -> RunRecord:
        rec = self.record
        try:
            await self.stage(RunState.INGESTING, 0, self._ingest, lambda d: {"digested": sorted(d)})
            verdict = await self.stage(RunState.GATING, 0, lambda: run_gate(self.ctx), lambda v: v.model_dump())
            rec.gate = verdict
            if not verdict.supported or verdict.substance is Substance.INSUFFICIENT:
                rec.state = RunState.GATE_REJECTED
                return self._finish()
            self.ctx.gate_evidence = list(verdict.evidence)
            if verdict.substance is Substance.THIN and verdict.suggested_scope:
                self.ctx.extra_guidance = (
                    f"{self.ctx.extra_guidance}\nThe gate judged the material thin. Scope note must "
                    f"include: {verdict.suggested_scope}"
                ).strip()
            iteration = 0
            prior: ReportBody | None = None
            draft: ReportBody | None = None
            next_stage = "drafting"
            findings: list[Finding] = []
            while True:
                routed = [f for f in open_findings(findings)]
                if next_stage == "drafting":
                    draft = await self.stage(
                        RunState.DRAFTING, iteration,
                        lambda: run_writer(self.ctx, iteration=iteration, prior=prior,
                                           findings=[f for f in routed if f.route_to == "writer"]),
                        lambda b: {"title": b.title, "claims": len(b.claims)},
                    )
                    rec.drafts.append(DraftRecord(role="writer", iteration=iteration, report=draft))
                assert draft is not None
                draft = await self.stage(
                    RunState.CONVEYING, iteration,
                    lambda: run_conveyor(self.ctx, iteration=iteration, draft=draft,
                                         findings=[f for f in routed if f.route_to == "conveyor"]),
                    lambda b: {"title": b.title},
                )
                rec.drafts.append(DraftRecord(role="conveyor", iteration=iteration, report=draft))
                findings = await self.stage(
                    RunState.AUDITING, iteration,
                    lambda: run_auditor(self.ctx, iteration=iteration, draft=draft),
                    lambda fs: {"open": [f.id for f in open_findings(fs)]},
                )
                rec.findings.extend(findings)
                next_stage = decide_next(findings, iteration, self.max_iterations)
                if next_stage == "rendering":
                    break
                iteration += 1
                prior = draft
            rec.iterations = iteration
            still_open = open_findings(findings)
            status = ReportStatus.FINDINGS_OPEN if still_open else ReportStatus.CLEAN
            rec.state = RunState.RENDERING
            started = self.now()
            rec.report = Report(
                **draft.model_dump(),
                metadata=ReportMetadata(
                    run_id=rec.run_id, pack_name=rec.pack_name, pack_hash=rec.pack_hash,
                    profile=rec.profile, iteration=iteration, status=status,
                    open_findings=[f.id for f in still_open],
                ),
            )
            self._record_stage(RunState.RENDERING, iteration, started, output={"status": status.value})
            rec.status = status
            rec.state = RunState.COMPLETED
        except AGENT_FAILURES as e:
            rec.state = RunState.FAILED
            rec.error = str(e)
        return self._finish()

    async def _ingest(self) -> dict[str, Any]:
        self.ctx.digests = await run_digests(self.ctx)
        self.record.digests = list(self.ctx.digests.values())
        return self.ctx.digests

    def _finish(self) -> RunRecord:
        self.record.usage = self.log.usage()
        self.record.llm_calls = list(self.log.records)
        return self.record


async def run_report(
    cfg: CorelataConfig, sources: list[Source], options: RunOptions, *,
    backends: dict[str, Backend], prompts: PromptLibrary, log: CallLog,
    pack: ResolvedPack | None = None, now: Callable[[], datetime] = utcnow,
) -> RunRecord:
    if not sources:
        raise ValueError("a run needs at least one source")
    if not options.value_statement.strip():
        raise ValueError("a run needs a value statement")
    pack = pack or load_run_pack(cfg, options.profile)
    return await _Run(cfg, sources, options, backends=backends, prompts=prompts, log=log,
                      pack=pack, now=now).execute()


async def discover(
    cfg: CorelataConfig, sources: list[Source], *, backends: dict[str, Backend],
    prompts: PromptLibrary, log: CallLog, audience_hint: str = "",
    pack: ResolvedPack | None = None,
) -> DiscoveryResult:
    if not sources:
        raise ValueError("discovery needs at least one source")
    pack = pack or load_run_pack(cfg, None)
    ctx = StageContext(
        cfg=cfg, runner=AgentRunner(cfg, backends, prompts, log), pack=pack, sources=sources,
        index=UnitIndex.from_sources(sources), value_statement="",
    )
    ctx.digests = await run_digests(ctx)
    return await run_discovery(ctx, audience_hint)
```

Implementation notes for the engineer:
- `AgentRunner` reads `self.cfg.models[...]` on each call, so reassigning `runner.cfg` after halving the threshold is enough; `RetryPolicy` is fixed at construction and that is fine.
- The `lambda` closures capture `iteration`, `prior`, `draft`, `routed` by reference; because each is awaited before the loop variables change, this is safe. Ruff `B023` flags loop-variable closures; rebind with default arguments (`lambda it=iteration, p=prior, r=routed: ...`) rather than suppressing the rule.
- `test_profile_flows_into_metadata` copies the builtin pack into a temp `packs_dir` so the customer-dir-wins behaviour is exercised end to end; simplify the copy loop to `shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", pack, dirs_exist_ok=True)` then overwrite `pack.yaml` and add the profile.

- [ ] **Step 4: Run**

Run: `cd engine && uv run pytest tests/test_pipeline.py -q --no-cov`
Expected: all pass. In `test_second_oversize_fails`, fix the assertion to `assert rec.state is RunState.FAILED and rec.error` (both scripted errors surface as the stage error; the assertion as first written is ambiguous).

- [ ] **Step 5: Record the spec deviation, lint, commit**

Append to Spec deviations: `§8.4 invariant 1 ("every claim in a delivered report has evidence") holds for status=clean. A findings_open report keeps unsourced claims so the analyst sees what failed; they are listed in metadata.open_findings via icd203.tc.8.`

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(pipeline): run state machine, bounded audit loop, trace record"
```

---

### Task 15: Markdown renderer

**Files:**
- Create: `engine/corelata/render/__init__.py`, `engine/corelata/render/markdown.py`
- Test: `engine/tests/render/__init__.py`, `engine/tests/render/test_markdown.py`

**Interfaces (spec §9):**
- `render.markdown.render_markdown(report: Report, pack: ResolvedPack, sources: list[Source], *, with_claim_ids: bool = False, open_findings: list[Finding] | None = None) -> str`. Sections follow `pack.template.section_order`; headings are `##` (or `## 1.`, `## 2.` when `pack.format.heading_style == "numbered"`); the handling marking is the first and last line; claim ids render as `^[c1]` after the sentence when enabled; the sources section lists `name`, descriptor, reliability note, SHA-256 prefix (first 8) and, for Coglossa sources, `Coglossa run <id>`; when `open_findings` is non-empty an appendix `## Audit findings open at delivery` lists `rule_id (severity): evidence — recommendation`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/render/test_markdown.py`:

```python
from corelata.render.markdown import render_markdown
from corelata.schema import (
    Alternative, Claim, ClaimKind, Confidence, Finding, FindingOut, KeyJudgment, Paragraph,
    Report, ReportMetadata, Section, Source, SourceEntry, SourceKind, SourceUnit, Verdict, BlockKind,
)
from corelata.standards.loader import load_pack


def _report(**md) -> Report:
    return Report(
        title="Varna port", handling_marking="UNCLASSIFIED",
        key_judgments=[KeyJudgment(text="Capacity grew.", confidence=Confidence.MODERATE, claim_ids=["c1"])],
        scope_note="Two sources.",
        sources=[SourceEntry(source_id="src1", descriptor="open-source report", reliability_note="Current."),
                 SourceEntry(source_id="src2", descriptor="translated document", reliability_note="Tier B.")],
        analysis=[Section(heading="Capacity", paragraphs=[Paragraph(text="Grew 40 percent.", claim_ids=["c1"])])],
        alternatives=[Alternative(hypothesis="Flat.", assessment="Unlikely.")],
        gaps_and_indicators=["Customs data."],
        claims=[Claim(id="c1", text="Grew.", kind=ClaimKind.FACT, evidence=["src1/u1"])],
        metadata=ReportMetadata(pack_name="icd203-base", pack_hash="h", **md),
    )


SOURCES = [
    Source(id="src1", kind=SourceKind.FILE, name="a.txt", format="txt", sha256="abcdef0123456789" * 4,
           units=[SourceUnit(id="u1", text="x", locator="para 1", kind=BlockKind.PARAGRAPH)]),
    Source(id="src2", kind=SourceKind.COGLOSSA_EXPORT, name="b.json", format="coglossa", sha256="ff" * 32,
           provenance={"coglossa_run_id": "run-42"}, units=[]),
]


def test_sections_in_template_order_with_marking_top_and_bottom():
    pack = load_pack("icd203-base")
    md = render_markdown(_report(), pack, SOURCES)
    lines = md.strip().splitlines()
    assert lines[0] == "UNCLASSIFIED" and lines[-1] == "UNCLASSIFIED"
    headings = [l for l in lines if l.startswith("## ")]
    assert headings == ["## Key judgments", "## Scope note", "## Sources", "## Capacity",
                        "## Alternatives considered", "## Gaps and indicators"]
    assert "# Varna port" in md
    assert "**Moderate confidence.** Capacity grew." in md
    assert "- a.txt — open-source report; Current. (sha256 abcdef01)" in md
    assert "- b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)" in md
    assert "^[c1]" not in md


def test_claim_ids_and_numbered_headings_and_open_findings():
    pack = load_pack("icd203-base").model_copy(update={"format": load_pack("icd203-base").format.model_copy(update={"heading_style": "numbered"})})
    finding = Finding(**FindingOut(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="c9 has no evidence",
                                   recommendation="Cite or remove.").model_dump(),
                      severity="blocking", route_to="writer", iteration=2)
    md = render_markdown(_report(status="findings_open", open_findings=["icd203.tc.8@2"]), pack, SOURCES,
                         with_claim_ids=True, open_findings=[finding])
    assert "## 1. Key judgments" in md and "## 4. Capacity" in md
    assert "Grew 40 percent. ^[c1]" in md
    assert "## Audit findings open at delivery" in md
    assert "- icd203.tc.8 (blocking): c9 has no evidence — Cite or remove." in md
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/render -q --no-cov`
Expected: ImportError.

- [ ] **Step 3: Write `render/markdown.py`**

```python
"""Markdown render of a Report: a pure function of report, resolved pack and sources (spec §9)."""

from corelata.schema import Finding, Report, Source, SourceKind
from corelata.standards.schema import ResolvedPack

_TITLES = {
    "key_judgments": "Key judgments",
    "scope_note": "Scope note",
    "sources": "Sources",
    "alternatives": "Alternatives considered",
    "gaps_and_indicators": "Gaps and indicators",
}


def _ids(claim_ids: list[str], on: bool) -> str:
    return f" ^[{', '.join(claim_ids)}]" if on and claim_ids else ""


def render_markdown(
    report: Report, pack: ResolvedPack, sources: list[Source], *,
    with_claim_ids: bool = False, open_findings: list[Finding] | None = None,
) -> str:
    numbered = pack.format.heading_style == "numbered"
    counter = 0
    by_id = {s.id: s for s in sources}
    out: list[str] = [report.handling_marking, ""]

    def heading(text: str) -> None:
        nonlocal counter
        counter += 1
        out.append(f"## {counter}. {text}" if numbered else f"## {text}")
        out.append("")

    for section in pack.template.section_order:
        if section == "title":
            out += [f"# {report.title}", ""]
        elif section == "handling_marking":
            continue  # rendered top and bottom
        elif section == "key_judgments":
            heading(_TITLES[section])
            for kj in report.key_judgments:
                out.append(f"- **{kj.confidence.value.capitalize()} confidence.** {kj.text}{_ids(kj.claim_ids, with_claim_ids)}")
            out.append("")
        elif section == "scope_note":
            heading(_TITLES[section])
            out += [report.scope_note, ""]
        elif section == "sources":
            heading(_TITLES[section])
            for entry in report.sources:
                src = by_id.get(entry.source_id)
                name = src.name if src else entry.source_id
                extra = f"sha256 {src.sha256[:8]}" if src else "sha256 unknown"
                if src and src.kind is SourceKind.COGLOSSA_EXPORT:
                    extra += f"; Coglossa run {src.provenance.get('coglossa_run_id', 'unknown')}"
                note = f"; {entry.reliability_note}" if entry.reliability_note else ""
                out.append(f"- {name} — {entry.descriptor}{note} ({extra})")
            out.append("")
        elif section == "analysis":
            for sec in report.analysis:
                heading(sec.heading)
                for p in sec.paragraphs:
                    out += [f"{p.text}{_ids(p.claim_ids, with_claim_ids)}", ""]
        elif section == "alternatives":
            heading(_TITLES[section])
            for alt in report.alternatives:
                out.append(f"- **{alt.hypothesis}** {alt.assessment}{_ids(alt.claim_ids, with_claim_ids)}")
            out.append("")
        elif section == "gaps_and_indicators":
            heading(_TITLES[section])
            out += [f"- {g}" for g in report.gaps_and_indicators]
            out.append("")
    if open_findings:
        out += ["## Audit findings open at delivery", ""]
        for f in open_findings:
            rec = f" — {f.recommendation}" if f.recommendation else ""
            out.append(f"- {f.rule_id} ({f.severity}): {f.evidence}{rec}")
        out.append("")
    out.append(report.handling_marking)
    return "\n".join(out).rstrip() + "\n"
```

`render/__init__.py`: empty.

- [ ] **Step 4: Run**

Run: `cd engine && uv run pytest tests/render -q --no-cov`
Expected: pass. Adjust the heading expectation if `analysis` numbering in the test differs: with the base order, numbered headings are 1 Key judgments, 2 Scope note, 3 Sources, 4 Capacity, 5 Alternatives, 6 Gaps.

- [ ] **Step 5: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(render): Markdown renderer with claim ids and open-findings appendix"
```

---

### Task 16: The CLI

**Files:**
- Create: `engine/corelata/cli.py`
- Test: `engine/tests/test_cli.py`

**Interfaces (spec §10.2):**
- `corelata --version`
- `corelata run <inputs...> --statement TEXT | --statement-file PATH [--coglossa-export PATH]... [--config PATH] [--profile NAME] [--max-iterations N] [--guidance TEXT] [--out DIR] [--claim-ids]`. Writes `report.md`, `report.json` (the `Report`), `trace.json` (the `RunRecord`), and `gate.json` into `--out` (default `corelata-out/<run_id>`). Prints one summary line. Exit codes: 0 completed clean, 3 completed with findings open, 4 gate rejected, 1 failed, 2 usage or config error, 130 interrupted.
- `corelata discover <inputs...> [--coglossa-export PATH]... [--config PATH] [--audience TEXT]` prints `DiscoveryResult` JSON to stdout; exit 0, or 2 on usage/config error, 1 on model failure.
- `corelata pack validate NAME_OR_PATH [--packs-dir DIR] [--config PATH]` prints issues one per line (`error: …` / `warning: …`); exit 0 if no errors, 1 otherwise.
- `corelata pack show NAME [--profile P] [--packs-dir DIR] [--config PATH]` prints the resolved pack JSON; exit 0 or 1 on `PackError`.
- `corelata fake-openai [--host] [--port] [--model ID]...` serves the synthetic responder (blocking).
- `cli.main(argv: list[str] | None = None) -> int`; `cli.load_sources(paths, coglossa_exports) -> list[Source]` assigning ids `src1..` across both kinds in order (files first, then exports); `cli.write_outputs(out_dir, record, pack, with_claim_ids) -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_cli.py`:

```python
import json
from pathlib import Path

import pytest
import yaml

from corelata import __version__
from corelata.cli import main
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG
from tests.stages.conftest import PORT


@pytest.fixture
def fake_server():
    with FakeOpenAIServer() as server:
        yield server


@pytest.fixture
def config_path(tmp_path, fake_server) -> Path:
    data = {**BASE_CONFIG, "backends": {"fake": {"base_url": fake_server.base_url}}}
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path) -> list[str]:
    a = tmp_path / "a.txt"
    a.write_text("\n\n".join(PORT), encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("# Note\n\nShippers welcomed the capacity at Varna.", encoding="utf-8")
    return [str(a), str(b)]


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and __version__ in capsys.readouterr().out


def test_run_clean(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["run", *inputs, "--statement", "Varna port capacity expansion matters to shippers",
                 "--config", str(config_path), "--out", str(out)])
    assert code == 0
    assert {p.name for p in out.iterdir()} == {"report.md", "report.json", "trace.json", "gate.json"}
    trace = json.loads((out / "trace.json").read_text())
    assert trace["state"] == "completed" and trace["status"] == "clean"
    assert [s["id"] for s in trace["sources"]] == ["src1", "src2"]
    report = json.loads((out / "report.json").read_text())
    assert report["metadata"]["status"] == "clean"
    md = (out / "report.md").read_text()
    assert md.startswith("UNCLASSIFIED\n") and "^[" not in md
    summary = capsys.readouterr().out
    assert "completed" in summary and "clean" in summary and str(out) in summary


def test_run_findings_open_exit_3(config_path, tmp_path, capsys):
    src = tmp_path / "s.txt"
    src.write_text("\n\n".join([*PORT, "UNSOURCED UNFIXABLE detail."]), encoding="utf-8")
    out = tmp_path / "out"
    code = main(["run", str(src), "--statement", "Varna port capacity expansion matters to shippers",
                 "--config", str(config_path), "--out", str(out), "--claim-ids"])
    assert code == 3
    md = (out / "report.md").read_text()
    assert "## Audit findings open at delivery" in md and "^[c0]" in md


def test_run_gate_rejected_exit_4(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["run", *inputs, "--statement", "Lunar helium mining", "--config", str(config_path),
                 "--out", str(out)])
    assert code == 4
    assert {p.name for p in out.iterdir()} == {"trace.json", "gate.json"}
    assert "gate rejected" in capsys.readouterr().out


def test_run_blank_statement_is_usage_error(config_path, inputs, capsys):
    assert main(["run", *inputs, "--statement", "   ", "--config", str(config_path)]) == 2
    assert "value statement" in capsys.readouterr().err


def test_run_statement_file_and_default_out(config_path, inputs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "v.txt").write_text("Varna port capacity expansion matters to shippers")
    code = main(["run", *inputs, "--statement-file", str(tmp_path / "v.txt"), "--config", str(config_path)])
    assert code == 0
    runs = list((tmp_path / "corelata-out").iterdir())
    assert len(runs) == 1 and (runs[0] / "report.md").is_file()


def test_run_requires_exactly_one_statement_source(config_path, inputs, capsys):
    assert main(["run", *inputs, "--config", str(config_path)]) == 2
    assert main(["run", *inputs, "--statement", "x", "--statement-file", "y", "--config", str(config_path)]) == 2


def test_run_bad_input_file(config_path, tmp_path, capsys):
    bad = tmp_path / "x.odt"
    bad.write_bytes(b"x")
    assert main(["run", str(bad), "--statement", "s", "--config", str(config_path)]) == 2
    assert "unsupported file type" in capsys.readouterr().err


def test_run_bad_config(tmp_path, inputs, capsys):
    assert main(["run", *inputs, "--statement", "s", "--config", str(tmp_path / "nope.yaml")]) == 2
    assert "config file not found" in capsys.readouterr().err


def test_run_with_coglossa_export(config_path, tmp_path, inputs):
    export = {
        "schema_version": "1", "coglossa_version": "0.1.0", "run_id": "run-7",
        "document": {"source_path": "/in/x.docx", "format": "docx", "sha256": "00" * 32},
        "spans": [{"id": "p1", "text": "Varna port capacity rose for shippers.", "agreement": "agree",
                   "chosen_from": "literal", "score": {"reliability": "A"}, "flags": []}],
        "guide": {"summary": "", "style_guide": "", "glossary": []},
    }
    path = tmp_path / "x.coglossa.json"
    path.write_text(json.dumps(export))
    out = tmp_path / "out"
    code = main(["run", inputs[0], "--coglossa-export", str(path), "--statement",
                 "Varna port capacity expansion matters to shippers", "--config", str(config_path),
                 "--out", str(out)])
    assert code == 0
    trace = json.loads((out / "trace.json").read_text())
    assert [s["id"] for s in trace["sources"]] == ["src1", "src2"]
    assert trace["sources"][1]["provenance"]["coglossa_run_id"] == "run-7"
    assert "Coglossa run run-7" in (out / "report.md").read_text()


def test_discover(config_path, inputs, capsys):
    assert main(["discover", *inputs, "--config", str(config_path), "--audience", "ops"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["candidates"]) == 2 and data["candidates"][0]["audience"] == "ops"


def test_pack_validate_and_show(capsys, tmp_path):
    assert main(["pack", "validate", "icd203-base"]) == 0
    assert main(["pack", "show", "icd203-base"]) == 0
    shown = json.loads(capsys.readouterr().out.splitlines()[-1] if False else capsys.readouterr().out or "{}") if False else None
    capsys.readouterr()
    assert main(["pack", "show", "icd203-base"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "icd203-base" and len(data["rules"]) == 17
    assert main(["pack", "show", "nope"]) == 1
    assert "not found" in capsys.readouterr().err
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "pack.yaml").write_text("name: p\nversion: '1'\n")
    assert main(["pack", "validate", str(tmp_path / "p")]) == 1
    assert "error:" in capsys.readouterr().out


def test_fake_openai_command_binds_and_stops(monkeypatch):
    import corelata.cli as cli

    class Stop(Exception):
        pass

    def fake_serve(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeOpenAIServer, "serve_forever", fake_serve)
    assert main(["fake-openai", "--port", "0"]) == 0
```

Clean up `test_pack_validate_and_show`'s accidental noise before committing: it should read

```python
def test_pack_validate_and_show(capsys, tmp_path):
    assert main(["pack", "validate", "icd203-base"]) == 0
    capsys.readouterr()
    assert main(["pack", "show", "icd203-base"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "icd203-base" and len(data["rules"]) == 17
    assert main(["pack", "show", "nope"]) == 1
    assert "not found" in capsys.readouterr().err
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "pack.yaml").write_text("name: p\nversion: '1'\n")
    assert main(["pack", "validate", str(tmp_path / "p")]) == 1
    assert "error:" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `cd engine && uv run pytest tests/test_cli.py -q --no-cov`
Expected: ImportError for `corelata.cli`.

- [ ] **Step 3: Write `cli.py`**

```python
"""Command-line interface (spec §10.2).

Exit codes: 0 completed clean, 3 completed with findings open, 4 gate rejected, 1 failed,
2 usage or config error, 130 interrupted."""

import argparse
import asyncio
import contextlib
import json
import sys
from pathlib import Path

from corelata import __version__
from corelata.config import ConfigError, CorelataConfig, default_config_path, load_config
from corelata.ingest.base import IngestError
from corelata.ingest.coglossa import load_coglossa_export
from corelata.ingest.units import make_source
from corelata.llm.agent import CallLog
from corelata.llm.registry import build_backends
from corelata.pipeline import RunOptions, discover, load_run_pack, run_report
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.render.markdown import render_markdown
from corelata.schema import ReportStatus, RunRecord, RunState, Source
from corelata.stages.audit import open_findings
from corelata.standards.loader import PackError, load_pack, validate_pack
from corelata.standards.schema import ResolvedPack
from corelata.testing.fake_openai import FakeOpenAIServer

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_FINDINGS_OPEN, EXIT_GATE_REJECTED = 0, 1, 2, 3, 4
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corelata", description="Standards-enforced intelligence report production."
    )
    parser.add_argument("--version", action="version", version=f"corelata {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def inputs(p: argparse.ArgumentParser) -> None:
        p.add_argument("inputs", nargs="*", type=Path, help="TXT, MD, DOCX, HTML, PDF, JSON or CSV files")
        p.add_argument("--coglossa-export", action="append", default=[], type=Path,
                       help="a Coglossa run export (JSON); repeatable")
        p.add_argument("--config", type=Path, default=default_config_path())

    run = sub.add_parser("run", help="produce a report from sources and a value statement")
    inputs(run)
    run.add_argument("--statement", help="the analyst's value statement")
    run.add_argument("--statement-file", type=Path, help="file holding the value statement")
    run.add_argument("--profile", help="standards pack profile (team overlay)")
    run.add_argument("--max-iterations", type=int, help="audit loop bound (default from config)")
    run.add_argument("--guidance", default="", help="extra guidance for the writer")
    run.add_argument("--out", type=Path, help="output directory (default corelata-out/<run_id>)")
    run.add_argument("--claim-ids", action="store_true", help="show claim ids in report.md")

    disc = sub.add_parser("discover", help="propose value statements for the sources")
    inputs(disc)
    disc.add_argument("--audience", default="", help="who the report is for, if known")

    pack = sub.add_parser("pack", help="inspect standards packs")
    pack_sub = pack.add_subparsers(dest="pack_command", required=True)
    for name, help_ in (("validate", "check a pack directory or name"), ("show", "print the resolved pack")):
        p = pack_sub.add_parser(name, help=help_)
        p.add_argument("name", help="pack name, or a directory for validate")
        p.add_argument("--profile")
        p.add_argument("--packs-dir", type=Path)
        p.add_argument("--config", type=Path)

    fake = sub.add_parser("fake-openai", help="serve a synthetic OpenAI-compatible endpoint")
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=int, default=8000)
    fake.add_argument("--model", action="append", dest="models")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "discover":
            return _discover(args)
        if args.command == "pack":
            return _pack(args)
        return _fake_openai(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


def _usage(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_USAGE


def load_sources(paths: list[Path], coglossa_exports: list[Path]) -> list[Source]:
    sources: list[Source] = []
    for path in paths:
        sources.append(make_source(f"src{len(sources) + 1}", path))
    for path in coglossa_exports:
        sources.extend(load_coglossa_export(f"src{len(sources) + 1}", path))
    return sources


def _setup(args: argparse.Namespace) -> tuple[CorelataConfig, list[Source], PromptLibrary]:
    cfg, issues = load_config(args.config)
    for issue in issues:
        print(f"{issue.level}: {issue.message}", file=sys.stderr)
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    if not args.inputs and not args.coglossa_export:
        raise IngestError("give at least one input file or --coglossa-export")
    return cfg, load_sources(args.inputs, args.coglossa_export), prompts


def _statement(args: argparse.Namespace) -> str:
    if bool(args.statement) == bool(args.statement_file):
        raise ConfigError("give exactly one of --statement or --statement-file")
    text = args.statement if args.statement else args.statement_file.read_text(encoding="utf-8")
    if not text.strip():
        raise ConfigError("the value statement is empty")
    return text.strip()


def write_outputs(out_dir: Path, record: RunRecord, pack: ResolvedPack, with_claim_ids: bool) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def dump(name: str, data: object) -> None:
        path = out_dir / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)

    dump("trace.json", record.model_dump(mode="json"))
    if record.gate is not None:
        dump("gate.json", record.gate.model_dump(mode="json"))
    if record.report is not None:
        dump("report.json", record.report.model_dump(mode="json"))
        last = [f for f in record.findings if f.iteration == record.iterations]
        md = render_markdown(record.report, pack, record.sources, with_claim_ids=with_claim_ids,
                             open_findings=open_findings(last))
        path = out_dir / "report.md"
        path.write_text(md, encoding="utf-8")
        written.append(path)
    return written


def _run(args: argparse.Namespace) -> int:
    try:
        statement = _statement(args)
        cfg, sources, prompts = _setup(args)
        pack = load_run_pack(cfg, args.profile)
    except (ConfigError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    backends = build_backends(cfg)
    log = CallLog(store_io=cfg.audit.store_llm_io)
    options = RunOptions(value_statement=statement, profile=args.profile,
                         max_iterations=args.max_iterations, extra_guidance=args.guidance)

    async def go() -> RunRecord:
        try:
            return await run_report(cfg, sources, options, backends=backends, prompts=prompts,
                                    log=log, pack=pack)
        finally:
            for b in backends.values():
                await b.aclose()

    record = asyncio.run(go())
    out_dir = args.out or Path("corelata-out") / record.run_id
    write_outputs(out_dir, record, pack, args.claim_ids)
    if record.state is RunState.GATE_REJECTED:
        reasons = "; ".join(record.gate.reasons) if record.gate else ""
        print(f"run {record.run_id}: gate rejected ({reasons}) -> {out_dir}")
        return EXIT_GATE_REJECTED
    if record.state is RunState.FAILED:
        print(f"run {record.run_id}: failed: {record.error} -> {out_dir}")
        return EXIT_FAILED
    print(
        f"run {record.run_id}: completed {record.status.value} after {record.iterations} "
        f"revision(s), {record.usage.calls} model calls -> {out_dir}"
    )
    return EXIT_FINDINGS_OPEN if record.status is ReportStatus.FINDINGS_OPEN else EXIT_OK


def _discover(args: argparse.Namespace) -> int:
    try:
        cfg, sources, prompts = _setup(args)
    except (ConfigError, IngestError, PackError, OSError) as e:
        return _usage(str(e))
    backends = build_backends(cfg)

    async def go():
        try:
            return await discover(cfg, sources, backends=backends, prompts=prompts, log=CallLog(),
                                  audience_hint=args.audience)
        finally:
            for b in backends.values():
                await b.aclose()

    try:
        result = asyncio.run(go())
    except Exception as e:  # noqa: BLE001 - the CLI reports any model failure as exit 1
        print(f"discovery failed: {e}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return EXIT_OK


def _packs_dir(args: argparse.Namespace) -> Path | None:
    if args.packs_dir is not None:
        return args.packs_dir
    if args.config is not None:
        cfg, _ = load_config(args.config)
        return cfg.standards.packs_dir
    return None


def _pack(args: argparse.Namespace) -> int:
    try:
        packs_dir = _packs_dir(args)
    except ConfigError as e:
        return _usage(str(e))
    if args.pack_command == "validate":
        issues = validate_pack(args.name, packs_dir=packs_dir)
        for issue in issues:
            print(f"{issue.level}: {issue.message}")
        if not issues:
            print("ok")
        return EXIT_FAILED if any(i.level == "error" for i in issues) else EXIT_OK
    try:
        pack = load_pack(args.name, packs_dir=packs_dir, profile=args.profile, allow_draft=True)
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(pack.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return EXIT_OK


def _fake_openai(args: argparse.Namespace) -> int:
    models = tuple(args.models or ["fake-model"])
    server = FakeOpenAIServer(args.host, args.port, models, keep_requests=False)
    print(f"fake OpenAI-compatible server at {server.base_url} (Ctrl+C to stop)", flush=True)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.stop()
    return EXIT_OK
```

- [ ] **Step 4: Run**

Run: `cd engine && uv run pytest tests/test_cli.py -q --no-cov`
Expected: all pass. `test_run_blank_statement_is_usage_error` passes because `_statement` runs before any model call.

- [ ] **Step 5: Lint, commit**

```bash
make lint && cd engine && uv run pytest -q
git add -A && git commit -m "feat(cli): run, discover, pack validate/show, fake-openai"
```

---

### Task 17: Example config, schema export, README, followups, coverage sweep

**Files:**
- Create: `engine/corelata.example.yaml`, `engine/corelata/schema/export.py`, `schema/` (generated), `engine/tests/schema/test_export.py`
- Modify: `README.md`, `docs/m1-followups.md`, `Makefile` (already has `schema`)

**Interfaces:**
- `python -m corelata.schema.export DIR` writes `report.schema.json`, `run-record.schema.json`, `resolved-pack.schema.json`, `discovery-result.schema.json`.

- [ ] **Step 1: Write the failing test**

`engine/tests/schema/test_export.py`:

```python
import json

from corelata.schema.export import EXPORTED, export, main


def test_export_writes_one_file_per_model(tmp_path):
    written = export(tmp_path)
    assert {p.name for p in written} == {f"{n}.schema.json" for n in EXPORTED}
    report = json.loads((tmp_path / "report.schema.json").read_text())
    assert "claims" in report["properties"]


def test_main_prints_paths(tmp_path, capsys):
    assert main([str(tmp_path)]) == 0
    assert "report.schema.json" in capsys.readouterr().out
```

- [ ] **Step 2: Write `schema/export.py`**

```python
"""Export JSON Schema for the canonical models. Usage: python -m corelata.schema.export DIR"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from corelata.schema import DiscoveryResult, Report, RunRecord
from corelata.standards.schema import ResolvedPack

EXPORTED: dict[str, type[BaseModel]] = {
    "report": Report,
    "run-record": RunRecord,
    "resolved-pack": ResolvedPack,
    "discovery-result": DiscoveryResult,
}


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTED.items():
        path = out_dir / f"{name}.schema.json"
        text = json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False)
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out_dir = Path(args[0]) if args else Path("../schema")
    for path in export(out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run `make schema` and commit the generated `schema/*.json`.

- [ ] **Step 3: Write `engine/corelata.example.yaml`**

```yaml
# Corelata configuration — copy to corelata.yaml and point it at your model servers.
# Any OpenAI-compatible server works: vLLM, Ollama, TGI, llama.cpp server, LM Studio.
backends:
  local:
    base_url: http://127.0.0.1:8000/v1   # e.g. vLLM; Ollama is http://host:11434/v1
    # api_key_env: CORELATA_LOCAL_KEY    # name of an environment variable, if the server needs a key
    max_concurrency: 4
    timeout_s: 120

models:
  strong:                          # the key is how roles refer to the model
    backend: local
    # name: Qwen/Qwen3-32B         # model id the server expects, if different from the key
    context_window: 32768
    structured_output: json_schema # json_schema | json_object | none
    max_output_tokens: 8192
    temperature: 0.2

roles:                             # spec §4.4; one model per role
  gate:     { model: strong }
  writer:   { model: strong }
  conveyor: { model: strong }
  auditor:  { model: strong }      # a different model family from the writer is better when you have one
  # profiler: { model: strong }    # only for `corelata profile extract` (M6)

standards:                         # spec §6
  # packs_dir: ./packs             # your packs; the built-in icd203-base is always available
  default_pack: icd203-base
  # default_profile: team-east

pipeline:                          # spec §7
  max_iterations: 2                # audit loop bound; the report is delivered either way
  digest_threshold_tokens: 6000    # sources longer than this are digested before drafting
  gate_unit_budget_tokens: 12000   # how much source text the gate sees in full

# retry: { max_attempts: 4, base_delay_s: 2, max_delay_s: 60 }
# audit: { store_llm_io: true }    # keep every prompt and reply in the trace
# prompts_dir: ./prompts           # override templates: prompts/<id>/v<N>.j2

# The sections below are for the queued/API deployment (M3+). `corelata run` needs none of them.
# database: { url_env: CORELATA_DATABASE_URL }
# storage: { kind: local, path: /data/files }
# worker: { concurrency: 2, stalled_after_s: 900 }
# api: { max_upload_mb: 200 }
# auth: { mode: trusted_header, header: X-Remote-User }
# integrations:
#   coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
```

Add a test that the example config loads: in `tests/test_config.py`:

```python
def test_example_config_loads():
    cfg, issues = load_config(Path(__file__).parents[1] / "corelata.example.yaml")
    assert cfg.standards.default_pack == "icd203-base" and issues == []
```

- [ ] **Step 4: README and followups**

`README.md` (repo root), replacing the one-line placeholder:

```markdown
# Corelata

Standards-enforced intelligence report production with a full trace. An analyst supplies
source material and a statement of its intelligence value; Corelata gates the statement
against the sources, drafts an ICD 203-shaped assessment, reviews it for the reader, audits
it rule by rule against a replaceable standards pack, and delivers the report with every
claim linked to its evidence.

Design: `docs/superpowers/specs/2026-10-12-corelata-v1-design.md`. Plans: `docs/superpowers/plans/`.

## M1: engine and CLI

    cd engine && uv sync --all-groups
    uv run corelata fake-openai &                      # a synthetic model for a smoke test
    cp corelata.example.yaml corelata.yaml             # points at 127.0.0.1:8000 by default
    uv run corelata run ../docs/examples/*.txt --statement "..." --out /tmp/run1
    uv run corelata pack show icd203-base

Exit codes: 0 clean, 3 findings open, 4 gate rejected, 1 failed, 2 usage.

## Development

    make lint && make test-engine      # ruff + pytest with a 95% branch-coverage gate
```

Create `docs/examples/varna-port.txt` with the three `PORT` paragraphs from the tests so the README command works.

Finish `docs/m1-followups.md`: confirm the Divergences list covers config, llm, prompts/library, testing fakes, ingest, text; Spec deviations covers the Coglossa schema validation and invariant 1; add under **Later**: `doctor command (M3, needs the database)`, `DOCX/HTML render (M2)`, `profile extract (M6)`, `shared foundation package extraction (after both products deploy)`.

- [ ] **Step 5: Full verification**

```bash
make lint && make test-engine && make schema && git status --short
cd engine && uv run corelata fake-openai --port 8765 &
sleep 1
cd engine && sed 's#127.0.0.1:8000#127.0.0.1:8765#' corelata.example.yaml > /tmp/smoke.yaml && \
  uv run corelata run ../docs/examples/varna-port.txt --statement "Varna port capacity expansion matters to shippers" --config /tmp/smoke.yaml --out /tmp/corelata-smoke; echo "exit $?"
kill %1
```

Expected: lint clean; pytest green with total branch coverage ≥ 95%; `make schema` produces four files; the smoke run exits 0 and `/tmp/corelata-smoke/report.md` starts with `UNCLASSIFIED`.

- [ ] **Step 6: Commit, push, open PR**

```bash
git add -A && git commit -m "docs(m1): example config, schema export, README, followups"
git push -u origin HEAD
gh pr create --title "M1: engine and CLI" --body "Implements docs/superpowers/plans/2026-10-12-m1-engine-cli.md (spec §14 M1). corelata run produces a report, Markdown render and trace against the fake model; ICD 203 base pack; Coglossa export adapter."
```

Merge when CI is green (user rule).

---

## Self-review notes (completed while writing)

- **Spec coverage, M1 scope (§14):** config §11 → Task 2; LLM layer and prompts §4.3 → Tasks 3, 10; schemas §8 → Task 5; standards pack §6 → Tasks 6, 7; ingest and Coglossa adapter §5 → Tasks 8, 9; digests §5.4 and gate/discovery §7.1 → Task 11; writer and conveyor §4.4 → Task 12; auditor and loop §6.2, §7.3, §8.2 → Task 13; state machine and error ladder §7.2, §7.5 → Task 14; Markdown render §9 → Task 15; CLI §10.2 (M1 subset) → Task 16; example config and schema export → Task 17. Out of M1 by design: `doctor`, DOCX/HTML, `profile extract`, database, API, web, bundle.
- **Type consistency checked:** `Finding.severity`/`route_to` are `str` (values of `Severity`/`RouteTo`) everywhere; `StageContext.check_refs` is used by all four validators; `open_findings` lives in `stages.audit` and is imported by the pipeline and the CLI; `key_terms` moves to `corelata.text` in Task 11 and both `testing.synthetic` and `stages.gate` import it from there; `RunRecord.status` is `ReportStatus | None`; `ReportBody` is the LLM output type and `Report` adds `metadata`.
- **Review Focus mapping:** blank statement → Task 16 `test_run_blank_statement_is_usage_error` and Task 14 `test_empty_inputs_are_usage_errors`; no usable text → Task 8 copied registry test with the new wording; duplicate file names → Task 9 `test_make_sources_ids_in_order_and_duplicate_names_stay_distinct`; unknown unit ref from the writer → Task 12 `test_writer_validator_rejects_unknown_ref_then_fails`; unknown rule id in profile and duplicate across chain → Task 6 `test_disable_or_override_unknown_rule_is_error`, `test_duplicate_rule_id_across_chain_is_error`.
