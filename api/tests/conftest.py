"""The API under test: a real Postgres (the engine's pytest plugin), the real lifespan, an
in-memory job queue and the fake model backend. Copied from Coglossa."""

import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import yaml
from corelata.config import CorelataConfig, load_config
from corelata.store.db import Database
from corelata.testing.queue import RecordingQueue
from fastapi import FastAPI

from corelata_api.app import create_app
from corelata_api.run_listener import listen_connection

pytest_plugins = ["corelata.testing.pytest_db"]

# The fake backend never answers over HTTP (port 9 is discard); routes that would need a model
# are not exercised through the network, and the worker tests inject FakeBackend directly.
API_CONFIG: dict = {
    "backends": {"fake": {"base_url": "http://127.0.0.1:9/v1", "max_concurrency": 4}},
    "models": {"fake-model": {"backend": "fake", "context_window": 32768}},
    "roles": {
        "gate": {"model": "fake-model"},
        "writer": {"model": "fake-model"},
        "conveyor": {"model": "fake-model"},
        "auditor": {"model": "fake-model"},
    },
    "retry": {"max_attempts": 2, "base_delay_s": 0.01, "max_delay_s": 0.02},
}


@pytest.fixture
def write_config(tmp_path, pg_url, monkeypatch) -> Callable[..., Path]:
    """Writes corelata.yaml (storage under tmp_path, a fast progress stream) and points
    CORELATA_DATABASE_URL at the test database."""
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)

    def write(**overrides) -> Path:
        data = {
            **API_CONFIG,
            "storage": {"path": str(tmp_path / "files")},
            "api": {"progress_poll_s": 0.02},
            **overrides,
        }
        path = tmp_path / "corelata.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    return write


@contextlib.asynccontextmanager
async def serve(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Runs the app's lifespan and talks to it in-process. raise_app_exceptions=False: a 500
    reaches the test as a response, as it would reach a browser."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://corelata.test") as c:
            yield c


@dataclass
class Api:
    app: FastAPI
    client: httpx.AsyncClient
    queue: RecordingQueue
    cfg: CorelataConfig
    db: Database
    storage_root: Path


def _recording(queue: RecordingQueue):
    @contextlib.asynccontextmanager
    async def opener(url: str) -> AsyncIterator[RecordingQueue]:
        yield queue

    return opener


@pytest.fixture
def make_api(db, write_config):
    @contextlib.asynccontextmanager
    async def make(
        coglossa_transport=None, queue=None, listener_connect=None, **overrides
    ) -> AsyncIterator[Api]:
        path = write_config(**overrides)
        cfg, _ = load_config(path)
        queue = queue or RecordingQueue()
        app = create_app(
            cfg,
            path,
            open_queue=_recording(queue),
            coglossa_transport=coglossa_transport,
            listener_connect=listener_connect or listen_connection,
        )
        async with serve(app) as client:
            yield Api(
                app=app, client=client, queue=queue, cfg=cfg, db=db, storage_root=cfg.storage.path
            )

    return make


@pytest.fixture
async def api(make_api) -> AsyncIterator[Api]:
    async with make_api() as opened:
        yield opened


def coglossa_export(run_id: str = "run-42") -> dict:
    """A minimal Coglossa report export (schema_version 1) with a translation guide."""
    return {
        "schema_version": "1",
        "coglossa_version": "0.1.0",
        "run_id": run_id,
        "document": {"source_path": "letter.docx", "format": "docx", "sha256": "0" * 64},
        "spans": [
            {
                "id": "p1",
                "text": "The port of Varna will add a second grain terminal in 2027.",
                "agreement": "high",
                "chosen_from": "contextual",
                "score": {"reliability": "high"},
                "flags": [],
            },
            {
                "id": "p2",
                "text": "Shippers expect waiting times at Varna to fall by a third.",
                "agreement": "medium",
                "chosen_from": "literal",
                "score": {"reliability": "medium"},
                "flags": [{"code": "ambiguity"}],
            },
        ],
        "guide": {
            "summary": "Trade correspondence, formal register.",
            "style_guide": "",
            "glossary": [{"term": "пристанище", "rendering": "port", "locked": True}],
        },
    }


PORT_TEXT = (
    "The port of Varna handles grain, containers and general cargo.\n\n"
    "A second grain terminal is planned for 2027.\n\n"
    "Shippers expect waiting times at Varna to fall by a third."
)
STATEMENT = "Varna port capacity expansion matters to shippers"


async def project_with_source(api: Api, name: str = "p") -> tuple[str, str]:
    """A project with one uploaded text source; returns (project_id, source_id)."""
    project = await api.client.post("/api/projects", json={"name": name})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    upload = await api.client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("port.txt", PORT_TEXT.encode("utf-8"), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    return pid, upload.json()[0]["id"]


async def start_run(api: Api, **overrides) -> dict:
    pid, sid = await project_with_source(api)
    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT, **overrides}
    response = await api.client.post("/api/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()


async def set_run_state(db: Database, run_id: str, state: str, *, notify: bool = True) -> None:
    """Move a run on without a worker (tests of routes that need a finished run), announcing the
    change as the worker does (CRL-22) unless `notify` is False."""
    from corelata.store import runs
    from corelata.store.models import utcnow

    async with db.session() as s, s.begin():
        run = await runs.get_run(s, uuid.UUID(run_id), lock=True)
        run.state = state
        run.started_at = run.started_at or utcnow()
        if state in ("completed", "gate_rejected", "failed", "cancelled"):
            run.finished_at = utcnow()
        if notify:
            await runs.notify_run(s, run.id)


async def complete_queued(api: Api, *, backend=None) -> int:
    """Execute every job the API queued, in order, in this process against the fake backend —
    a deterministic worker for tests of routes that need a finished run. Returns the count."""
    from corelata.prompts.library import PromptLibrary
    from corelata.storage import LocalStorage
    from corelata.testing.fake_backend import FakeBackend
    from corelata.worker.execute import WorkerServices, run_job

    svc = WorkerServices(
        cfg=api.cfg,
        db=api.db,
        storage=LocalStorage(api.cfg.storage.path),
        queue=api.queue,
        backends={"fake": backend or FakeBackend(name="fake")},
        prompts=PromptLibrary(api.cfg.prompts_dir),
    )
    count = 0
    while (job := api.queue.pop()) is not None:
        await run_job(svc, job.task, job.kwargs)
        count += 1
        assert count < 20, "job loop did not settle"
    return count
