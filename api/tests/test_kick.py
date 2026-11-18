"""M19 (spec §12.1): with worker.kick_url set, every job the API queues also kicks a worker."""

import pytest
from corelata.worker.kick import KickingQueue

from tests.conftest import start_run


async def test_the_queue_kicks_a_worker_only_when_configured(make_api, monkeypatch):
    async with make_api() as plain:
        assert not isinstance(plain.app.state.ctx.queue, KickingQueue)
    monkeypatch.setenv("KICK_TOKEN", "t")
    # port 9 refuses at once: the kick fails, is logged, and the request is not held up
    worker = {"kick_url": "http://127.0.0.1:9/", "kick_token_env": "KICK_TOKEN"}
    async with make_api(worker=worker) as api:
        queue = api.app.state.ctx.queue
        assert isinstance(queue, KickingQueue) and queue.kicker.token == "t"
        assert queue.inner is api.queue
        run = await start_run(api)  # 202: the kick's failure never reaches the caller
        assert [j.kwargs for j in api.queue.jobs] == [{"run_id": run["run_id"]}]
        await queue.kicker.drain()
    assert queue.kicker._client.is_closed  # closed with the app


async def test_a_failed_start_closes_the_kicker(make_api, monkeypatch):
    import corelata_api.app as app_module

    built = []
    real = app_module.build_kicker

    def build(cfg):
        built.append(real(cfg))
        return built[-1]

    def broken(cfg):
        raise RuntimeError("storage down")

    monkeypatch.setattr(app_module, "build_kicker", build)
    monkeypatch.setattr(app_module, "build_storage", broken)
    worker = {"kick_url": "http://127.0.0.1:9/"}
    with pytest.raises(RuntimeError, match="storage down"):
        async with make_api(worker=worker):
            pass  # pragma: no cover
    assert len(built) == 1 and built[0]._client.is_closed
