import uuid

import httpx

from tests.conftest import coglossa_export

COGLOSSA = {"coglossa": {"base_url": "http://coglossa.test"}}


def _coglossa(status: int = 200, body: dict | None = None):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else coglossa_export())

    return httpx.MockTransport(handler), seen


async def _project(api) -> str:
    response = await api.client.post("/api/projects", json={"name": "p"})
    return response.json()["id"]


async def _project_with(api, headers) -> str:
    response = await api.client.post("/api/projects", json={"name": "p"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_from_coglossa_imports_the_run_export(make_api):
    transport, seen = _coglossa()
    async with make_api(
        integrations=COGLOSSA, auth={"mode": "trusted_header"}, coglossa_transport=transport
    ) as api:
        headers = {"X-Remote-User": "ana"}
        pid = await _project_with(api, headers)
        response = await api.client.post(
            f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "run-42"}, headers=headers
        )
        assert response.status_code == 201, response.text
        translation, guide = response.json()
        assert translation["kind"] == "coglossa_export"
        assert translation["name"] == "coglossa-run-42.json"
        assert translation["provenance"]["coglossa_run_id"] == "run-42"
        assert guide["format"] == "coglossa-guide"
        assert (await api.client.get(f"/api/projects/{pid}/sources", headers=headers)).json() == [
            translation,
            guide,
        ]
        info = (await api.client.get("/api/system/info", headers=headers)).json()
        assert info["coglossa"] is True
        # CRL-126 (AC3): the same run again is the import the project has
        again = await api.client.post(
            f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "run-42"}, headers=headers
        )
        assert again.status_code == 200, again.text
        assert again.json() == [
            {**translation, "already_in_project": True},
            {**guide, "already_in_project": True},
        ]
        listed = await api.client.get(f"/api/projects/{pid}/sources", headers=headers)
        assert len(listed.json()) == 2
    request = seen[0]
    assert str(request.url) == "http://coglossa.test/api/runs/run-42/exports/json"
    assert request.headers["x-remote-user"] == "ana"


async def test_from_coglossa_is_409_when_not_configured(api):
    pid = await _project(api)
    response = await api.client.post(
        f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "run-42"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "integrations.coglossa is not configured"


async def test_from_coglossa_passes_coglossa_answers_through(make_api):
    transport, _ = _coglossa(404, {"detail": "run not found"})
    async with make_api(integrations=COGLOSSA, coglossa_transport=transport) as api:
        pid = await _project(api)
        response = await api.client.post(
            f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "run-42"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Coglossa run run-42 not found"
        bad_id = await api.client.post(
            f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "a/b"}
        )
        assert bad_id.status_code == 422
        unknown = await api.client.post(
            f"/api/projects/{uuid.uuid4()}/sources/from-coglossa", json={"run_id": "run-42"}
        )
        assert unknown.status_code == 404
        assert (await api.client.get(f"/api/projects/{pid}/sources")).json() == []


async def test_from_coglossa_rejects_an_export_it_cannot_read(make_api):
    transport, _ = _coglossa(200, {"schema_version": "2"})
    async with make_api(integrations=COGLOSSA, coglossa_transport=transport) as api:
        pid = await _project(api)
        response = await api.client.post(
            f"/api/projects/{pid}/sources/from-coglossa", json={"run_id": "run-42"}
        )
        assert response.status_code == 422
        assert "schema_version '2' is not supported" in response.json()["detail"]
        assert not [p for p in api.storage_root.rglob("*") if p.is_file()]
