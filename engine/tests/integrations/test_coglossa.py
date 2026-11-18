import json

import httpx
import pytest

from corelata.config import CoglossaIntegration
from corelata.integrations.coglossa import CoglossaClient, CoglossaFetchError

EXPORT = {"schema_version": "1", "spans": []}


def _client(handler, **cfg) -> CoglossaClient:
    integration = CoglossaIntegration(base_url="http://coglossa.test/", **cfg)
    return CoglossaClient(integration, transport=httpx.MockTransport(handler))


async def test_fetch_export_forwards_the_user_and_the_key(monkeypatch):
    monkeypatch.setenv("COGLOSSA_KEY", "s3cret")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=EXPORT)

    client = _client(handler, api_key_env="COGLOSSA_KEY")
    data = await client.fetch_export("run-42", user="ana")
    assert json.loads(data) == EXPORT
    assert seen["url"] == "http://coglossa.test/api/runs/run-42/exports/json"
    assert seen["headers"]["x-remote-user"] == "ana"
    assert seen["headers"]["authorization"] == "Bearer s3cret"
    assert seen["headers"]["accept"] == "application/json"


async def test_fetch_export_sends_a_non_ascii_user_as_utf8():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw"] = request.headers.raw
        seen["user"] = request.headers["x-remote-user"]  # httpx decodes as UTF-8
        return httpx.Response(200, content=b"{}")

    assert await _client(handler).fetch_export("run-42", user="José") == b"{}"
    assert seen["user"] == "José"
    assert (b"X-Remote-User", "José".encode()) in seen["raw"]


async def test_fetch_export_without_a_user_or_key_sends_neither():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, content=b"{}")

    assert await _client(handler).fetch_export("run-42", user=None) == b"{}"
    assert "x-remote-user" not in seen["headers"] and "authorization" not in seen["headers"]


@pytest.mark.parametrize(
    ("status", "body", "want_status", "want_text"),
    [
        (404, {"detail": "run not found"}, 404, "Coglossa run run-42 not found"),
        (
            409,
            {"detail": "run is sweeping"},
            409,
            "Coglossa run run-42 is not complete: run is sweeping",
        ),
        (
            401,
            {"detail": "missing X-Remote-User header"},
            502,
            "Coglossa answered 401 for run run-42: missing X-Remote-User header",
        ),
        (
            500,
            "<html>boom</html>",
            502,
            "Coglossa answered 500 for run run-42: <html>boom</html>",
        ),
        (500, ["boom"], 502, 'Coglossa answered 500 for run run-42: ["boom"]'),
        (500, "null", 502, "Coglossa answered 500 for run run-42: null"),
    ],
)
async def test_fetch_export_maps_coglossa_answers(status, body, want_status, want_text):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, dict | list):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)

    with pytest.raises(CoglossaFetchError) as info:
        await _client(handler).fetch_export("run-42", user=None)
    assert info.value.status == want_status and str(info.value) == want_text


async def test_fetch_export_reports_an_unreachable_coglossa():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(CoglossaFetchError) as info:
        await _client(handler).fetch_export("run-42", user=None)
    assert info.value.status == 502
    assert str(info.value) == "cannot reach Coglossa at http://coglossa.test/: connection refused"


async def test_fetch_export_names_an_exception_that_has_no_message():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    with pytest.raises(CoglossaFetchError) as info:
        await _client(handler).fetch_export("run-42", user=None)
    assert info.value.status == 502
    assert str(info.value).endswith(": ReadTimeout")


@pytest.mark.parametrize("run_id", ["", "   ", "a/b", "a b", "x" * 65, "../etc"])
async def test_fetch_export_rejects_run_ids_that_are_not_path_safe(run_id):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("no request expected")

    with pytest.raises(CoglossaFetchError, match="Coglossa run id") as info:
        await _client(handler).fetch_export(run_id, user=None)
    assert info.value.status == 422


async def test_fetch_export_fails_clearly_when_the_key_variable_is_unset(monkeypatch):
    monkeypatch.delenv("COGLOSSA_KEY", raising=False)
    client = _client(lambda request: httpx.Response(200, json={}), api_key_env="COGLOSSA_KEY")
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 409
    assert "COGLOSSA_KEY is not set" in str(e.value)


async def test_fetch_export_reports_an_invalid_base_url():
    # the config refuses this shape now (CRL-55); the client still reports one httpx refuses
    integration = CoglossaIntegration.model_construct(base_url="http://[bad]")
    client = CoglossaClient(
        integration, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 502 and "cannot reach Coglossa" in str(e.value)


async def test_fetch_export_refuses_an_oversized_body():
    body = b"x" * 2048

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    client = _client(handler)
    client.max_bytes = 1024
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 502 and "larger than 1024 bytes" in str(e.value)
