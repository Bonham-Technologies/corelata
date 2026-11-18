import uuid

import pytest

from corelata import service
from corelata.llm.payload import parse_input
from corelata.prompts.library import PromptLibrary
from corelata.schema import RunState
from corelata.storage import LocalStorage
from corelata.testing.queue import RecordingQueue
from corelata.worker.execute import WorkerServices, run_job
from tests.conftest import build_config
from tests.stages.conftest import PORT

STATEMENT = "Varna port capacity expansion matters to shippers"


def make_services(db, fake_backend, tmp_path, **cfg_overrides) -> WorkerServices:
    cfg = build_config(**cfg_overrides)
    return WorkerServices(
        cfg=cfg,
        db=db,
        storage=LocalStorage(tmp_path / "files"),
        queue=RecordingQueue(),
        backends={"fake": fake_backend},
        prompts=PromptLibrary(cfg.prompts_dir),
    )


@pytest.fixture
def services(db, fake_backend, tmp_path):
    return make_services(db, fake_backend, tmp_path)


async def submit(svc, *texts: str, statement: str = STATEMENT, project: str = "p", **opts):
    """A project, one source per text (the Varna paragraphs by default) and a queued run."""
    pid = await service.create_project(svc.db, project)
    ids: list[uuid.UUID] = []
    for i, text in enumerate(texts or ["\n\n".join(PORT)]):
        ids += await service.add_source(svc.db, svc.storage, pid, f"s{i}.txt", text.encode())
    req = service.RunRequest(project_id=pid, source_ids=ids, value_statement=statement, **opts)
    return await service.start_run(svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, req)


async def drain(svc, *, limit: int = 50) -> int:
    """Run queued jobs in order until the queue is empty (a deterministic in-test worker)."""
    count = 0
    while (job := svc.queue.pop()) is not None:
        await run_job(svc, job.task, job.kwargs)
        count += 1
        assert count < limit, "job loop did not settle"
    return count


async def state(db, run_id) -> RunState:
    return (await service.run_progress(db, run_id)).state


def tasks_sent(fake_backend) -> list[str]:
    return [
        parse_input([m.model_dump() for m in r.messages])["task"] for r in fake_backend.requests
    ]
