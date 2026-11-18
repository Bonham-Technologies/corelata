"""M19 (spec §12.1): every storage call on the API's and the worker's event loop runs in a
thread, because on the hosted demo each one is a request to S3; and `storage_call` waits for its
thread even when cancelled, so a cleanup never runs beside the call it undoes (R-M19-4)."""

import asyncio
import contextlib
import contextvars
import dataclasses
import threading
import time
from pathlib import Path

import pytest

from corelata import service
from corelata.ingest.base import IngestError
from corelata.schema import ReviewAction, RunState
from corelata.storage import LocalStorage, storage_call
from corelata.store import runs
from corelata.worker.execute import _reference
from tests.worker.conftest import drain, make_services, submit
from tests.worker.test_execute import _house_pack


async def test_storage_call_returns_the_result_and_raises_the_calls_error():
    assert await storage_call(lambda a, b: a + b, 2, 3) == 5

    def broken():
        raise OSError("disk gone")

    with pytest.raises(OSError, match="disk gone"):
        await storage_call(broken)


async def test_a_cancelled_storage_call_waits_for_its_thread_then_raises_the_cancellation():
    started, release, done = threading.Event(), threading.Event(), []

    def slow_put():
        started.set()
        release.wait(5)
        done.append("stored")

    task = asyncio.create_task(storage_call(slow_put))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()  # still waiting for the thread: a cleanup must not start yet
    task.cancel()  # a second cancellation changes nothing
    await asyncio.sleep(0.05)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["stored"]


async def test_a_cancelled_call_that_failed_still_raises_the_cancellation():
    started, release = threading.Event(), threading.Event()

    def failing():
        started.set()
        release.wait(5)
        raise OSError("refused")

    task = asyncio.create_task(storage_call(failing))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_loop_teardown_cancelling_every_task_does_not_end_the_wait():
    """`asyncio.run` cancels all tasks when it shuts down; the call's thread is still waited for."""
    started, release, done = threading.Event(), threading.Event(), []

    def slow_put():
        started.set()
        release.wait(5)
        done.append("stored")

    task = asyncio.create_task(storage_call(slow_put))
    await asyncio.to_thread(started.wait, 5)
    threading.Timer(0.2, release.set).start()
    me = asyncio.current_task()
    for t in asyncio.all_tasks():
        if t is not me:
            t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["stored"]  # finished before the cancellation surfaced


async def test_storage_call_keeps_the_callers_context_variables():
    var = contextvars.ContextVar("var", default="unset")
    var.set("set")
    assert await storage_call(var.get) == "set"


class _TrackedFile:
    """A `local_file` context manager that records entering and leaving."""

    def __init__(self, log: list, gate: threading.Event | None) -> None:
        self.log, self.gate = log, gate

    def __enter__(self):
        self.log.append("enter")
        if self.gate is not None:
            self.gate.wait(5)
        return Path("copy")

    def __exit__(self, *exc):
        self.log.append(("exit", exc[0]))


class _TrackedStorage:
    def __init__(self, gate: threading.Event | None = None) -> None:
        self.log: list = []
        self.gate = gate

    def local_file(self, key):
        return _TrackedFile(self.log, self.gate)


async def test_the_reference_copy_is_removed_when_the_body_raises():
    storage = _TrackedStorage()
    with pytest.raises(RuntimeError, match="body"):
        async with _reference(storage, "k") as path:  # type: ignore[arg-type]
            assert path == Path("copy")
            raise RuntimeError("body")
    assert storage.log == ["enter", ("exit", RuntimeError)]


async def test_the_reference_copy_is_removed_when_the_download_is_cancelled():
    gate = threading.Event()
    storage = _TrackedStorage(gate)

    async def use():
        async with _reference(storage, "k"):  # type: ignore[arg-type]
            raise AssertionError("not reached")

    task = asyncio.create_task(use())
    await asyncio.to_thread(lambda: [time.sleep(0.01) for _ in range(500) if not storage.log])
    task.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert storage.log == ["enter", ("exit", asyncio.CancelledError)]


async def test_no_reference_key_gives_no_path():
    async with _reference(_TrackedStorage(), None) as path:  # type: ignore[arg-type]
        assert path is None


class LoopWatchingStorage(LocalStorage):
    """Local storage that records each call and whether it ran on an event loop's thread."""

    def __init__(self, root) -> None:
        super().__init__(root)
        self.calls: list[str] = []
        self.on_loop: list[str] = []

    def _seen(self, name: str) -> None:
        self.calls.append(name)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # a worker thread: what we want
        self.on_loop.append(name)

    def put(self, key, data):
        self._seen("put")
        super().put(key, data)

    def get(self, key):
        self._seen("get")
        return super().get(key)

    @contextlib.contextmanager
    def local_file(self, key):
        self._seen("local_file")  # when it is entered: S3Storage downloads the file then
        with super().local_file(key) as path:
            yield path

    def delete_prefix(self, prefix):
        self._seen("delete_prefix")
        super().delete_prefix(prefix)

    def list_keys(self, prefix):
        self._seen("list_keys")
        return super().list_keys(prefix)


async def test_service_and_worker_storage_calls_run_off_the_event_loop(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    storage = LoopWatchingStorage(tmp_path / "watched")
    svc = dataclasses.replace(svc, storage=storage)
    # an upload, and one that is refused after it was stored (its file is deleted)
    run_id = await submit(svc, profile="east")  # stores the source and the reference document
    pid = (await service.run_progress(db, run_id)).project_id
    with pytest.raises(IngestError):
        await service.add_source(db, storage, pid, "empty.pdf", b"not a pdf")
    # the worker: a restarted run clears its stale files, reads the reference, stores exports
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts = "drafting", 1
    await asyncio.to_thread(storage.put, f"runs/{run_id}/stale.bin", b"x")
    await drain(svc)
    assert (await service.run_progress(db, run_id)).state is RunState.COMPLETED
    # the API's reads, and a return that copies the reference document
    assert await service.reference_document(db, storage, run_id)
    assert await service.stored_export(db, storage, run_id, "report.json")
    child = await service.review_run(
        db,
        storage,
        svc.queue,
        svc.cfg,
        svc.prompts,
        run_id,
        ReviewAction.RETURN,
        note="Tighten it.",
    )
    assert child is not None
    assert {"put", "get", "local_file", "delete_prefix", "list_keys"} <= set(storage.calls)
    assert storage.on_loop == []


async def test_a_failed_return_removes_the_reruns_reference_copy_off_the_loop(
    db, fake_backend, tmp_path, monkeypatch
):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    storage = LoopWatchingStorage(tmp_path / "watched")
    svc = dataclasses.replace(svc, storage=storage)
    run_id = await submit(svc, profile="east")
    await drain(svc)

    async def refused(*args, **kwargs):
        raise RuntimeError("the review event could not be written")

    monkeypatch.setattr(runs, "add_review_event", refused)
    with pytest.raises(RuntimeError, match="could not be written"):
        await service.review_run(
            db, storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN, note="n"
        )
    assert [k for k in storage.list_keys("runs") if not k.startswith(f"runs/{run_id}/")] == []
    # every other call, the submit's puts included, ran in a thread: only the line above, the
    # test's own, ran on the loop
    assert storage.on_loop == ["list_keys"]
