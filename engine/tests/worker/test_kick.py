import asyncio
import logging

import httpx

from corelata.config import WorkerConfig
from corelata.testing.queue import RecordingQueue
from corelata.worker.kick import HttpKicker, KickingQueue, build_kicker


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _recorder(status: int = 200, delay: float = 0.0):
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if delay:
            await asyncio.sleep(delay)
        return httpx.Response(status)

    return seen, httpx.MockTransport(handler)


async def test_kick_posts_with_the_token():
    seen, transport = _recorder()
    kicker = HttpKicker("https://kick.example/", "tok", transport=transport)
    kicker.kick()
    await kicker.drain()
    assert [(r.method, str(r.url)) for r in seen] == [("POST", "https://kick.example/")]
    assert seen[0].headers["authorization"] == "Bearer tok"
    await kicker.aclose()


async def test_kicks_close_together_are_merged():
    seen, transport = _recorder()
    clock = Clock()
    kicker = HttpKicker("https://k/", None, transport=transport, clock=clock)
    kicker.kick()
    clock.now += 1.0
    kicker.kick()  # within min_interval_s: merged
    clock.now += 2.5
    kicker.kick()
    await kicker.drain()
    assert len(seen) == 2 and "authorization" not in seen[0].headers
    await kicker.aclose()


async def test_a_failed_kick_is_logged_not_raised(caplog):
    seen, transport = _recorder(status=503)
    kicker = HttpKicker("https://k/", "t", transport=transport)
    with caplog.at_level(logging.WARNING, logger="corelata.worker"):
        kicker.kick()
        await kicker.drain()
    assert "worker kick failed" in caplog.text and "503" in caplog.text

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down = HttpKicker("https://k/", "t", transport=httpx.MockTransport(refuse))
    down.kick()
    await down.drain()  # no exception
    await kicker.aclose()
    await down.aclose()


async def test_queue_defers_then_kicks_without_waiting_for_the_kick():
    seen, transport = _recorder(delay=0.5)
    kicker = HttpKicker("https://k/", "t", transport=transport)
    inner = RecordingQueue()
    queue = KickingQueue(inner, kicker)
    async with asyncio.timeout(0.2):  # a slow kick endpoint does not hold up the request
        await queue.defer("run_job", lock="run:1", run_id="1")
    assert inner.jobs[-1].task == "run_job"
    assert inner.jobs[-1].kwargs == {"run_id": "1"}
    await kicker.drain()
    assert len(seen) == 1
    await kicker.aclose()


async def test_no_kick_when_the_inner_defer_fails():
    class Broken:
        async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None:
            raise RuntimeError("queue down")

    seen, transport = _recorder()
    kicker = HttpKicker("https://k/", "t", transport=transport)
    queue = KickingQueue(Broken(), kicker)
    try:
        await queue.defer("run_job", run_id="1")
    except RuntimeError as e:
        assert str(e) == "queue down"
    else:  # pragma: no cover
        raise AssertionError("defer should raise")
    await kicker.drain()
    assert seen == []
    await kicker.aclose()


def test_build_kicker(monkeypatch):
    assert build_kicker(WorkerConfig()) is None
    monkeypatch.setenv("KICK_TOKEN", "t")
    kicker = build_kicker(
        WorkerConfig(kick_url="https://k/", kick_token_env="KICK_TOKEN")  # type: ignore[call-arg]
    )
    assert kicker is not None and kicker.token == "t"
    assert build_kicker(WorkerConfig(kick_url="https://k/")).token is None  # type: ignore[union-attr]


async def test_a_non_httpx_error_is_logged_not_raised(caplog):
    def explode(request: httpx.Request) -> httpx.Response:
        raise ValueError("boom")

    kicker = HttpKicker("https://k/", "t", transport=httpx.MockTransport(explode))
    with caplog.at_level(logging.WARNING, logger="corelata.worker"):
        kicker.kick()
        await kicker.drain()
        await kicker.aclose()
    assert "worker kick failed" in caplog.text and "ValueError: boom" in caplog.text


async def test_a_malformed_url_is_logged_not_raised(caplog):
    kicker = HttpKicker("http://", None)
    with caplog.at_level(logging.WARNING, logger="corelata.worker"):
        kicker.kick()
        await kicker.drain()
        await kicker.aclose()
    assert "worker kick failed" in caplog.text


async def test_aclose_does_not_wait_for_a_slow_kick():
    _, transport = _recorder(delay=30)
    kicker = HttpKicker("https://k/", "t", transport=transport)
    kicker.kick()
    await asyncio.sleep(0.05)  # the POST is in flight
    async with asyncio.timeout(0.5):
        await kicker.aclose()


async def test_kick_sends_the_extra_headers():
    seen, transport = _recorder()
    extra = {"Modal-Key": "wk-1", "Modal-Secret": "ws-1"}
    kicker = HttpKicker("https://k/", "tok", extra_headers=extra, transport=transport)
    kicker.kick()
    await kicker.drain()
    assert seen[0].headers["modal-key"] == "wk-1" and seen[0].headers["modal-secret"] == "ws-1"
    assert seen[0].headers["authorization"] == "Bearer tok"
    await kicker.aclose()


def test_build_kicker_reads_the_extra_headers(monkeypatch):
    monkeypatch.setenv("PLATFORM_KEY", "wk-1")
    cfg = WorkerConfig(kick_url="https://k/", extra_headers_env={"Modal-Key": "PLATFORM_KEY"})  # type: ignore[call-arg]
    kicker = build_kicker(cfg)
    assert kicker is not None and kicker._client.headers["modal-key"] == "wk-1"
    assert "authorization" not in kicker._client.headers


# Corelata's own (spec §12.1): priority passes through, so a discovery still goes first.


async def test_the_queue_passes_the_priority_through():
    seen, transport = _recorder()
    kicker = HttpKicker("https://k/", None, transport=transport, min_interval_s=0)
    inner = RecordingQueue()
    queue = KickingQueue(inner, kicker)
    await queue.defer("corelata.discover", lock="discovery:1", priority=1, discovery_id="1")
    await queue.defer("corelata.run", lock="run:1", run_id="1")
    assert [(j.task, j.priority) for j in inner.jobs] == [
        ("corelata.discover", 1),
        ("corelata.run", 0),
    ]
    await kicker.drain()
    assert len(seen) == 2
    await kicker.aclose()


async def test_a_discovery_queued_through_the_service_keeps_its_priority(db, tmp_path):
    from corelata import service
    from corelata.storage import LocalStorage

    seen, transport = _recorder()
    kicker = HttpKicker("https://k/", None, transport=transport)
    inner = RecordingQueue()
    pid = await service.create_project(db, "p")
    sid = (await service.add_source(db, LocalStorage(tmp_path), pid, "a.txt", b"The port grew."))[0]
    await service.start_discovery(db, KickingQueue(inner, kicker), pid, [sid])
    assert [j.priority for j in inner.jobs] == [service.DISCOVERY_PRIORITY]
    await kicker.drain()
    assert len(seen) == 1
    await kicker.aclose()
