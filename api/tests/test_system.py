import asyncio

import pytest
from corelata.schema import CheckStatus, DoctorCheck, DoctorReport
from corelata.testing.fake_openai import FakeOpenAIServer

from corelata_api.routes import system


@pytest.fixture
def server():
    with FakeOpenAIServer() as srv:
        yield srv


async def test_doctor_is_healthy_against_the_fake_server(make_api, server):
    backends = {"fake": {"base_url": server.base_url, "max_concurrency": 2, "timeout_s": 5}}
    async with make_api(backends=backends) as api:
        response = await api.client.get("/api/system/doctor")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["ok"] is True
    names = {c["name"] for c in report["checks"]}
    assert {"config", "prompts", "pack", "database", "storage"} <= names
    assert all(c["status"] in ("pass", "warn") for c in report["checks"])


async def test_doctor_reports_an_unreachable_model_server_without_probing(api):
    response = await api.client.get("/api/system/doctor", params={"probe": "false"})
    assert response.status_code == 200
    report = response.json()
    assert report["ok"] is False
    failed = [c for c in report["checks"] if c["status"] == "fail"]
    assert [c["name"] for c in failed] == ["backend fake"]


async def test_info_reports_the_configured_revision_rounds(make_api, api):
    """CRL-67: the web app starts Revision rounds from the operator's pipeline.max_iterations."""
    assert (await api.client.get("/api/system/info")).json()["max_iterations"] == 2  # the default
    async with make_api(pipeline={"max_iterations": 3}) as configured:
        response = await configured.client.get("/api/system/info")
    assert response.status_code == 200
    assert response.json()["max_iterations"] == 3


class CountingDoctor:
    """Stands in for run_doctor: counts calls by probe value and holds each probing call until
    released, so concurrent requests overlap."""

    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.release = asyncio.Event()

    async def __call__(self, config_path, *, probe: bool = True) -> DoctorReport:
        self.calls.append(probe)
        if probe:
            await self.release.wait()
        return DoctorReport.of([DoctorCheck(name="config", status=CheckStatus.PASS, message="ok")])


@pytest.fixture
def counting_doctor(monkeypatch) -> CountingDoctor:
    doctor = CountingDoctor()
    monkeypatch.setattr(system, "run_doctor", doctor)
    return doctor


async def test_doctor_does_not_probe_by_default(api, counting_doctor):
    """CRL-112: a bare GET runs the checks without test completions."""
    counting_doctor.release.set()  # a probing call would not hang the test
    response = await api.client.get("/api/system/doctor")
    assert response.status_code == 200, response.text
    assert counting_doctor.calls == [False]


async def test_concurrent_probes_share_one_run_and_reuse_it(api, counting_doctor):
    """CRL-112: two concurrent probe calls give one backend call, and a call inside the window
    is served the same report without another."""

    async def probe():
        return await api.client.get("/api/system/doctor", params={"probe": "true"})

    first = asyncio.create_task(probe())
    second = asyncio.create_task(probe())
    while not counting_doctor.calls:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # the second request reaches the route while the first is held
    counting_doctor.release.set()
    responses = await asyncio.gather(first, second)
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert (await probe()).status_code == 200
    assert counting_doctor.calls == [True]
