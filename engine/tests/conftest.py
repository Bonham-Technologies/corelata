import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from corelata.config import CorelataConfig
from corelata.llm.agent import AgentRunner, CallLog
from corelata.pipeline import RunOptions, run_report
from corelata.prompts.library import PromptLibrary
from corelata.store import models
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT

pytest_plugins = ["corelata.testing.pytest_db"]

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


def skew_clock(monkeypatch: pytest.MonkeyPatch, ahead: timedelta) -> None:
    """Run this host's clock (`corelata.store.models.utcnow`) `ahead` of the database's: an API
    or worker host whose clock is skewed (CRL-53, CRL-87)."""

    class Skewed(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.now(tz) + ahead

    monkeypatch.setattr(models, "datetime", Skewed)


async def db_now(db) -> datetime:
    async with db.session() as s:
        now = await s.scalar(select(func.now()))
    assert now is not None
    return now


def on_db_clock(value: datetime | None, now: datetime) -> bool:
    """`value` was written by the database's clock: within a minute of its `now`, where a skewed
    host would be ten minutes off."""
    return value is not None and abs(value - now) < timedelta(minutes=1)


def build_config(**overrides) -> CorelataConfig:
    return CorelataConfig.model_validate({**BASE_CONFIG, **overrides})


@pytest.fixture
def make_config():
    return build_config


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
            PromptLibrary(cfg.prompts_dir or Path(__file__).parent / "fixtures" / "prompts"),
            CallLog(store_io=store_io),
            sleep=_no_sleep,
        )

    return _make


@pytest.fixture
def run(make_config, fake_backend):
    """Execute a whole run in-process against the fake backend with a frozen clock."""

    async def _run(
        *sources,
        statement="Varna port capacity expansion matters to shippers",
        cfg=None,
        observer=None,
        **opts,
    ):
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return await run_report(
            cfg,
            sources,
            RunOptions(value_statement=statement, **opts),
            backends={"fake": fake_backend},
            prompts=PromptLibrary(),
            log=CallLog(),
            now=lambda: datetime(2026, 10, 12, tzinfo=UTC),
            observer=observer,
        )

    return _run


@pytest.fixture(autouse=True)
def _restore_log_handlers() -> Iterator[None]:
    """A JSON log handler a test installs writes to that test's captured stream; detach it
    afterwards so later tests don't log to a closed stream."""
    loggers = [logging.getLogger(name) for name in ("corelata", "procrastinate")]
    saved = [(lg.handlers[:], lg.level) for lg in loggers]
    yield
    for lg, (handlers, level) in zip(loggers, saved, strict=True):
        lg.handlers = handlers
        lg.setLevel(level)


@pytest.fixture
def hermetic_aws(monkeypatch, tmp_path) -> None:
    """boto3 reads the machine's AWS setup into every client (CRL-45): a ~/.aws/config with
    `s3 = payload_signing_enabled = false`, a profile or a checksum variable changes what the S3
    tests see. Drop every AWS_* variable and point the config and credentials files at nothing."""
    for name in [n for n in os.environ if n.startswith("AWS_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
