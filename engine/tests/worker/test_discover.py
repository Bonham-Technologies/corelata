import logging
import uuid

import pytest

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import DiscoveryState
from corelata.store import discoveries
from corelata.worker.execute import run_job
from tests.stages.conftest import PORT
from tests.worker.conftest import drain, tasks_sent


async def _queue_discovery(svc, *texts, audience_hint=""):
    pid = await service.create_project(svc.db, "p")
    ids = []
    for i, text in enumerate(texts or ["\n\n".join(PORT), "Shippers welcomed the capacity."]):
        ids += await service.add_source(svc.db, svc.storage, pid, f"d{i}.txt", text.encode())
    did = await service.start_discovery(svc.db, svc.queue, pid, ids, audience_hint)
    return did, ids


async def test_a_discovery_runs_through_the_queue(services, fake_backend):
    did, ids = await _queue_discovery(services, audience_hint="port operators")
    assert [(j.task, j.lock, j.kwargs) for j in services.queue.jobs] == [
        (service.TASK_DISCOVER, f"discovery:{did}", {"discovery_id": str(did)})
    ]
    assert await drain(services) == 1
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and view.error is None
    assert len(view.candidates) == 2  # the synthetic gate proposes one per source
    assert view.source_ids == [str(i) for i in ids]
    assert view.usage is not None and view.usage.calls == 1
    assert view.started_at is not None and view.finished_at is not None
    assert tasks_sent(fake_backend) == ["discover"]
    from corelata.llm.payload import parse_input

    payload = parse_input([m.model_dump() for m in fake_backend.requests[0].messages])
    assert payload["audience_hint"] == "port operators"
    async with services.db.session() as s:
        row = await discoveries.get(s, did)
    assert len(row.llm_calls) == 1 and row.llm_calls[0]["role"] == "gate"


async def test_a_model_failure_ends_the_discovery_failed(services, fake_backend):
    fake_backend.script("discover", PermanentBackendError("down"), PermanentBackendError("down"))
    did, _ = await _queue_discovery(services)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and "down" in (view.error or "")
    assert view.candidates == [] and view.finished_at is not None


async def test_an_unexpected_error_is_recorded(services, monkeypatch):
    from corelata.worker import execute

    async def boom(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setattr(execute, "discover", boom)
    did, _ = await _queue_discovery(services)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED
    assert view.error == "internal error: RuntimeError: kaput"


async def test_a_redelivered_discovery_job_does_nothing(services, fake_backend):
    did, _ = await _queue_discovery(services)
    await drain(services)
    await run_job(services, service.TASK_DISCOVER, {"discovery_id": str(did)})
    assert len(fake_backend.requests) == 1


async def test_a_discovery_left_running_by_a_dead_worker_is_redone(services, fake_backend, caplog):
    did, _ = await _queue_discovery(services)
    async with services.db.session() as s, s.begin():
        (await discoveries.get(s, did, lock=True)).state = "running"
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and len(fake_backend.requests) == 1
    assert "restarted" in caplog.text


async def test_start_discovery_validates(services):
    pid = await service.create_project(services.db, "p")
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await service.start_discovery(services.db, services.queue, pid, [])
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await service.start_discovery(services.db, services.queue, pid, [], "x")
    ids = await service.add_source(services.db, services.storage, pid, "a.txt", b"x")
    with pytest.raises(service.InvalidRequestError, match="only once"):
        await service.start_discovery(services.db, services.queue, pid, [ids[0], ids[0]])
    assert services.queue.jobs == []


async def test_a_job_for_an_unknown_discovery_is_skipped(services, caplog):
    caplog.set_level(logging.INFO, logger="corelata.worker")
    await run_job(services, service.TASK_DISCOVER, {"discovery_id": str(uuid.uuid4())})
    assert "skipped" in caplog.text


async def test_a_database_blip_during_discovery_is_retried_not_recorded(services, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from corelata.worker import execute

    real = execute.discover
    calls = []

    async def blip_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("x", {}, Exception("blip"))
        return await real(*a, **k)

    monkeypatch.setattr(execute, "discover", blip_once)
    did, _ = await _queue_discovery(services)
    job = services.queue.pop()
    with pytest.raises(OperationalError):
        await run_job(services, job.task, job.kwargs)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.RUNNING and view.error is None
    await run_job(services, job.task, job.kwargs)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and len(view.candidates) == 2
