import asyncio

import pytest
from corelata.schema import CheckStatus, DoctorCheck, DoctorReport

from corelata_api.doctor_cache import DoctorCache


def report(message: str) -> DoctorReport:
    return DoctorReport.of([DoctorCheck(name="config", status=CheckStatus.PASS, message=message)])


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def test_a_report_is_reused_inside_the_window_and_rerun_after_it():
    clock = Clock()
    cache = DoctorCache(ttl_s=30, clock=clock)
    calls = []

    async def run():
        calls.append(clock.now)
        return report(str(len(calls)))

    assert (await cache.get(run)).checks[0].message == "1"
    clock.now += 29.9
    assert (await cache.get(run)).checks[0].message == "1"
    clock.now += 0.1
    assert (await cache.get(run)).checks[0].message == "2"
    assert len(calls) == 2


async def test_a_failed_run_is_not_kept():
    cache = DoctorCache()
    attempts = 0

    async def run():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("model server went away")
        return report("ok")

    with pytest.raises(RuntimeError):
        await cache.get(run)
    assert (await cache.get(run)).checks[0].message == "ok"
    assert attempts == 2


async def test_a_caller_that_goes_away_does_not_cancel_the_run_for_the_others():
    cache = DoctorCache()
    release = asyncio.Event()
    calls = 0

    async def run():
        nonlocal calls
        calls += 1
        await release.wait()
        return report("shared")

    leaver = asyncio.create_task(cache.get(run))
    stayer = asyncio.create_task(cache.get(run))
    await asyncio.sleep(0)
    leaver.cancel()
    await asyncio.sleep(0)
    release.set()
    assert (await stayer).checks[0].message == "shared"
    assert leaver.cancelled()
    assert calls == 1


async def test_a_run_that_fails_after_every_caller_left_is_not_reported_as_unretrieved():
    cache = DoctorCache()
    release = asyncio.Event()

    async def run():
        await release.wait()
        raise RuntimeError("late failure")

    caller = asyncio.create_task(cache.get(run))
    await asyncio.sleep(0)
    caller.cancel()
    await asyncio.sleep(0)
    release.set()
    for _ in range(3):
        await asyncio.sleep(0)
    assert (await cache.get(lambda: _ok())).checks[0].message == "ok"


async def _ok() -> DoctorReport:
    return report("ok")
