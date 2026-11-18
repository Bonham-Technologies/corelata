import pytest
from corelata.testing.fake_openai import FakeOpenAIServer


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
