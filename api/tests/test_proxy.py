"""M19 (spec §12.1): auth.proxy_secret_env and ProxySecretMiddleware, copied from Coglossa."""

import asyncio
import json
import logging

import pytest

from corelata_api.proxy import PROXY_SECRET_HEADER, ProxySecretMiddleware
from tests.conftest import set_run_state, start_run

SECRET = "s3cret-" * 5
AUTH = {"mode": "trusted_header", "proxy_secret_env": "CORELATA_PROXY_SECRET"}
SIGNED_IN = {"X-Remote-User": "ana"}
WITH_SECRET = {**SIGNED_IN, PROXY_SECRET_HEADER: SECRET}
REFUSED = {"detail": "this address only answers requests from the Corelata sign-in proxy"}


@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("CORELATA_PROXY_SECRET", SECRET)


async def test_requests_without_the_secret_are_refused(secret_env, make_api, tmp_path):
    web_dir = tmp_path / "dist"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<title>Corelata</title>", encoding="utf-8")
    async with make_api(auth=AUTH, api={"web_dir": str(web_dir), "progress_poll_s": 0.02}) as api:
        client = api.client
        missing = await client.get("/api/system/info", headers=SIGNED_IN)
        assert missing.status_code == 401 and missing.json() == REFUSED
        wrong_secret = {**SIGNED_IN, PROXY_SECRET_HEADER: "x"}
        wrong = await client.get("/api/system/info", headers=wrong_secret)
        assert wrong.status_code == 401
        ok = await client.get("/api/system/info", headers=WITH_SECRET)
        assert ok.status_code == 200 and ok.json()["user"] == "ana"
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/")).status_code == 401
        assert (await client.get("/", headers={PROXY_SECRET_HEADER: SECRET})).status_code == 200


async def test_a_forged_user_without_the_secret_reaches_nothing(secret_env, make_api):
    """Review Focus 3: a caller holding the Modal token Coglossa shares (spec §23.5) but not
    Corelata's own secret gets nothing, whatever user it claims, and changes nothing."""
    async with make_api(auth=AUTH) as api:
        forged = {"X-Remote-User": "people-first", "Modal-Key": "wk", "Modal-Secret": "ws"}
        for method, path in [
            ("GET", "/api/projects"),
            ("POST", "/api/projects"),
            ("GET", "/api/openapi.json"),
            ("GET", "/api/system/doctor"),
        ]:
            response = await api.client.request(method, path, headers=forged, json={"name": "x"})
            assert (response.status_code, response.json()) == (401, REFUSED), (method, path)
        listed = await api.client.get("/api/projects", headers=WITH_SECRET)
        assert listed.json() == []  # the refused POST created nothing


async def test_the_progress_stream_still_streams(secret_env, make_api):
    async with make_api(auth=AUTH) as api:
        api.client.headers.update(WITH_SECRET)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "completed")
        refused = await api.client.get(
            f"/api/runs/{run['run_id']}/events", headers={PROXY_SECRET_HEADER: ""}
        )
        assert refused.status_code == 401
        async with asyncio.timeout(5):
            response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    data = next(line for line in response.text.splitlines() if line.startswith("data: "))
    assert json.loads(data[len("data: ") :])["state"] == "completed"


async def test_the_middleware_passes_chunks_on_as_they_come():
    """httpx's in-process transport collects whole bodies, so check the streaming at the ASGI
    level: the first chunk must reach the client while the app is still producing the rest."""
    release = asyncio.Event()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await release.wait()
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    sent = []
    first = asyncio.Event()

    async def send(message):
        sent.append(message)
        if message.get("body") == b"first":
            first.set()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "path": "/api/runs/x/events",
        "headers": [(PROXY_SECRET_HEADER.lower().encode(), SECRET.encode())],
    }
    task = asyncio.create_task(ProxySecretMiddleware(app, SECRET)(scope, receive, send))
    async with asyncio.timeout(5):
        await first.wait()
    assert not task.done()  # still streaming
    release.set()
    await task
    assert [m.get("body") for m in sent[1:]] == [b"first", b"last"]


async def _drive(secret, scope):
    """Run the middleware over an app that records whether it was reached."""
    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(scope["type"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    await ProxySecretMiddleware(app, secret)(scope, receive, send)
    return reached, sent


async def test_only_lifespan_passes_without_the_secret():
    reached, _ = await _drive(SECRET, {"type": "lifespan"})
    assert reached == ["lifespan"]


async def test_a_websocket_without_the_secret_is_closed_before_the_app():
    scope = {"type": "websocket", "path": "/api/ws", "headers": []}
    reached, sent = await _drive(SECRET, scope)
    assert reached == [] and sent == [{"type": "websocket.close", "code": 1008}]
    good = {**scope, "headers": [(PROXY_SECRET_HEADER.lower().encode(), SECRET.encode())]}
    assert (await _drive(SECRET, good))[0] == ["websocket"]


async def test_an_unknown_scope_type_never_reaches_the_app(caplog):
    """CRL-57: refused before its headers are read, so a scope without them raises nothing, and
    one carrying the right secret is refused all the same; each refusal is logged."""
    good = [(PROXY_SECRET_HEADER.lower().encode(), SECRET.encode())]
    with caplog.at_level(logging.WARNING, logger="corelata.api"):
        for scope in ({"type": "unknown"}, {"type": "other", "headers": good}):
            reached, sent = await _drive(SECRET, scope)
            assert reached == [] and sent == [], scope
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "refused an ASGI scope of unknown type 'unknown'"),
        (logging.WARNING, "refused an ASGI scope of unknown type 'other'"),
    ]


async def test_an_empty_secret_refuses_everything_but_health():
    """A missing header must never compare equal to an empty secret."""
    secret = ""
    for scope in (
        {"type": "http", "path": "/api/projects", "headers": []},
        {"type": "http", "path": "/api/projects", "headers": [(b"x-corelata-proxy-secret", b"")]},
        {"type": "websocket", "path": "/api/ws", "headers": []},
    ):
        reached, _ = await _drive(secret, scope)
        assert reached == [], scope
    reached, _ = await _drive(secret, {"type": "http", "path": "/api/health", "headers": []})
    assert reached == ["http"]


@pytest.mark.parametrize(
    "path", ["/api/health/", "/api/healthz", "/api/health/../x", "/API/health", "/api/health/x"]
)
async def test_lookalike_health_paths_need_the_secret(path):
    reached, sent = await _drive(SECRET, {"type": "http", "path": path, "headers": []})
    assert reached == [] and sent[0]["status"] == 401


async def test_without_the_setting_nothing_changes(api):
    response = await api.client.get("/api/system/info")
    assert response.status_code == 200 and response.json()["user"] is None
