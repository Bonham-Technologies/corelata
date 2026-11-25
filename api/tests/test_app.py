import asyncio
import logging
from pathlib import Path

import corelata
import pytest
from corelata.config import ConfigError, CorelataConfig, load_config
from corelata.ingest.base import IngestError
from corelata.integrations.coglossa import CoglossaFetchError
from corelata.service import (
    ConflictError,
    InvalidRequestError,
    InvalidRunStateError,
    QueueUnavailableError,
)
from corelata.standards.loader import PackError
from corelata.storage import StorageError
from corelata.store.runs import NotFoundError
from corelata.trace import TraceError
from sqlalchemy.exc import InterfaceError, OperationalError

from corelata_api import app as app_module
from corelata_api.app import create_app
from corelata_api.errors import UploadTooLargeError
from tests.conftest import API_CONFIG, serve


async def test_health_needs_no_user_and_no_database(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        response = await api.client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": corelata.__version__}


def _protected_routes() -> list[tuple[str, str]]:
    # From the OpenAPI document: FastAPI >= 0.14x keeps included routers lazy, so `app.routes`
    # no longer lists the leaf routes. /api/openapi.json is hidden from the schema; added by hand.
    app = create_app(CorelataConfig.model_validate(API_CONFIG), Path("corelata.yaml"))
    routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    routes.discard(("GET", "/api/health"))
    assert ("GET", "/api/system/info") in routes
    routes.add(("GET", "/api/openapi.json"))
    assert len(routes) > 1, "route discovery found nothing: the 401 gate would not run"
    return sorted(routes)


@pytest.mark.parametrize(("method", "path"), _protected_routes())
async def test_trusted_header_required_on_every_route(make_api, method, path):
    url = path.replace("{run_id}", "00000000-0000-0000-0000-000000000000")
    for name in ("project_id", "discovery_id", "claim_id", "name"):
        url = url.replace("{" + name + "}", "x")
    async with make_api(auth={"mode": "trusted_header"}) as api:
        for headers in ({}, {"X-Remote-User": ""}, {"X-Remote-User": "   "}):
            response = await api.client.request(method, url, headers=headers)
            assert response.status_code == 401, (method, path, headers)
            assert response.json()["detail"].startswith("missing X-Remote-User header")


async def test_trusted_header_user_is_trimmed_and_custom_header_names_work(make_api):
    async with make_api(auth={"mode": "trusted_header", "header": "X-Forwarded-User"}) as api:
        assert (await api.client.get("/api/system/info")).status_code == 401
        response = await api.client.get("/api/system/info", headers={"X-Forwarded-User": "  ana  "})
    assert response.status_code == 200
    assert response.json()["user"] == "ana" and response.json()["auth_mode"] == "trusted_header"


async def test_auth_none_has_no_user(api):
    response = await api.client.get("/api/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["user"] is None and body["auth_mode"] == "none"
    assert body["coglossa"] is False and body["default_pack"] == "icd203-base"
    assert body["version"] == corelata.__version__ and body["max_upload_mb"] == 200
    assert body["logout_url"] is None  # no Sign out on the air-gapped install (M18 spec §7.3)


async def test_info_reports_the_proxys_sign_out_page(make_api):
    auth = {"mode": "trusted_header", "logout_url": "/oauth2/sign_out"}
    async with make_api(auth=auth) as api:
        response = await api.client.get("/api/system/info", headers={"X-Remote-User": "ana"})
    assert response.status_code == 200
    assert response.json()["logout_url"] == "/oauth2/sign_out"


async def test_openapi_is_behind_auth_and_the_doc_pages_are_off(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        assert (await api.client.get("/api/openapi.json")).status_code == 401
        response = await api.client.get("/api/openapi.json", headers={"X-Remote-User": "ana"})
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "Corelata"
        assert "/api/system/info" in response.json()["paths"]
        for path in ("/docs", "/api/docs", "/openapi.json", "/redoc", "/api/redoc"):
            assert (await api.client.get(path, headers={"X-Remote-User": "ana"})).status_code == 404


class _Busy(Exception):
    sqlstate = "40P01"


_BUSY = "the database was busy with a conflicting change; try again"
_DATABASE_DOWN = "the database is unavailable; the operator's log has the reason"
_QUEUE_DOWN = "the job queue is unavailable; the operator's log has the reason"
_STORAGE_DOWN = "the file store is unavailable; see the server log"

ERRORS = {
    "not_found": (NotFoundError("run 1 not found"), 404, "run 1 not found"),
    "trace": (TraceError("claim c9 is not in the report"), 404, "claim c9 is not in the report"),
    "conflict": (
        ConflictError("a project named 'p' already exists"),
        409,
        "a project named 'p' already exists",
    ),
    "coglossa": (
        CoglossaFetchError("Coglossa run r not found", status=404),
        404,
        "Coglossa run r not found",
    ),
    "coglossa_down": (
        CoglossaFetchError(
            "cannot reach Coglossa; the operator's log has the reason",
            status=502,
            log_detail="cannot reach Coglossa at http://c: refused",
        ),
        502,
        "cannot reach Coglossa; the operator's log has the reason",
    ),
    "state": (InvalidRunStateError("run 1 is failed"), 409, "run 1 is failed"),
    "too_large": (
        UploadTooLargeError("a.pdf is larger than the 1 MB upload limit"),
        413,
        "a.pdf is larger than the 1 MB upload limit",
    ),
    "invalid": (
        InvalidRequestError("a run needs a value statement"),
        422,
        "a run needs a value statement",
    ),
    "ingest": (
        IngestError("x.png: unsupported file type '.png'"),
        422,
        "x.png: unsupported file type '.png'",
    ),
    "pack": (
        PackError("profile 'z' not found in pack 'icd203-base'"),
        422,
        "profile 'z' not found in pack 'icd203-base'",
    ),
    "pack_missing": (
        PackError(
            "pack 'acme' not found (looked in /srv/packs, /opt/corelata/site-packages)",
            public="pack 'acme' not found",
        ),
        422,
        "pack 'acme' not found",
    ),
    "config": (ConfigError("bad\n  config"), 500, "bad config"),
    "storage": (StorageError("disk full"), 500, _STORAGE_DOWN),
    "queue": (
        QueueUnavailableError("cannot reach the job queue: connection refused"),
        503,
        _QUEUE_DOWN,
    ),
    "busy": (OperationalError("stmt", {}, _Busy()), 409, _BUSY),
    "outage": (
        OperationalError("stmt", {}, ConnectionRefusedError("refused")),
        503,
        _DATABASE_DOWN,
    ),
    "internal": (RuntimeError("secret internals"), 500, "internal error"),
}


@pytest.mark.parametrize("kind", sorted(ERRORS))
async def test_engine_errors_map_to_statuses(write_config, kind, caplog):
    exc, status, detail = ERRORS[kind]
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def boom() -> dict:
        raise exc

    app.add_api_route("/api/boom", boom, methods=["GET"])
    with caplog.at_level(logging.WARNING, logger="corelata.api"):
        async with serve(app) as client:
            response = await client.get("/api/boom")
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "secret internals" not in response.text
    # CRL-68: an internal error's 500 too, which is sent outside the middleware
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"  # CRL-131
    assert response.headers["cache-control"] == "no-store"
    if kind == "internal":
        [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert record.exc_info is not None and "secret internals" in str(record.exc_info[1])


_DRIVER_LINE = (
    'connection to server at "10.0.0.5", port 5432 failed: '
    'FATAL:  password authentication failed for user "corelata"'
)


@pytest.mark.parametrize(
    ("exc", "detail"),
    [
        (OperationalError("stmt", {}, ConnectionError(_DRIVER_LINE)), _DATABASE_DOWN),
        (InterfaceError("stmt", {}, ConnectionError(_DRIVER_LINE)), _DATABASE_DOWN),
        (QueueUnavailableError(f"cannot reach the job queue: {_DRIVER_LINE}"), _QUEUE_DOWN),
    ],
    ids=["operational", "interface", "queue"],
)
async def test_an_outage_keeps_the_driver_message_in_the_log_not_the_response(
    write_config, caplog, exc, detail
):
    """CRL-86: the driver's line names hosts, ports and roles, so only the log gets it."""
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def boom() -> dict:
        raise exc

    app.add_api_route("/api/boom", boom, methods=["GET"])
    with caplog.at_level(logging.WARNING, logger="corelata.api"):
        async with serve(app) as client:
            response = await client.get("/api/boom")
    assert (response.status_code, response.json()) == (503, {"detail": detail})
    for secret in ("10.0.0.5", "5432", "corelata"):
        assert secret not in response.text
    [record] = [r for r in caplog.records if r.name == "corelata.api"]
    assert record.levelno == logging.WARNING
    assert _DRIVER_LINE in record.getMessage()


async def test_a_storage_failure_keeps_its_paths_in_the_log_not_the_response(write_config, caplog):
    """CRL-75: the message names paths, buckets and endpoints, so only the log gets it."""
    reason = "cannot write /srv/corelata/files/r1.pdf to bucket acme-reports at http://minio:9000"
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def boom() -> dict:
        raise StorageError(reason)

    app.add_api_route("/api/boom", boom, methods=["GET"])
    with caplog.at_level(logging.WARNING, logger="corelata.api"):
        async with serve(app) as client:
            response = await client.get("/api/boom")
    assert (response.status_code, response.json()) == (500, {"detail": _STORAGE_DOWN})
    for secret in ("/srv", "acme-reports", "minio", "9000"):
        assert secret not in response.text
    [record] = [r for r in caplog.records if r.name == "corelata.api"]
    assert record.levelno == logging.ERROR
    assert reason in record.getMessage() and "/api/boom" in record.getMessage()


@pytest.mark.parametrize(
    ("exc", "detail", "logged"),
    [
        (
            CoglossaFetchError(
                "cannot reach Coglossa; the operator's log has the reason",
                status=502,
                log_detail="cannot reach Coglossa at http://10.0.0.7:8081: connection refused",
            ),
            "cannot reach Coglossa; the operator's log has the reason",
            "cannot reach Coglossa at http://10.0.0.7:8081: connection refused",
        ),
        (
            PackError(
                "pack 'acme' not found (looked in /srv/packs, /opt/corelata/site-packages)",
                public="pack 'acme' not found",
            ),
            "pack 'acme' not found",
            "pack 'acme' not found (looked in /srv/packs, /opt/corelata/site-packages)",
        ),
    ],
    ids=["coglossa", "pack"],
)
async def test_hosts_and_paths_go_to_the_log_not_the_response(
    write_config, caplog, exc, detail, logged
):
    """CRL-114: the rest of CRL-75 and CRL-86."""
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def boom() -> dict:
        raise exc

    app.add_api_route("/api/boom", boom, methods=["GET"])
    with caplog.at_level(logging.WARNING, logger="corelata.api"):
        async with serve(app) as client:
            response = await client.get("/api/boom")
    assert response.json() == {"detail": detail}
    for secret in ("10.0.0.7", "8081", "/srv", "site-packages"):
        assert secret not in response.text
    [record] = [r for r in caplog.records if r.name == "corelata.api"]
    assert record.levelno == logging.WARNING and record.getMessage() == logged


async def test_a_coglossa_import_is_held_to_the_upload_limit(make_api):
    """CRL-114: the fetch honours min(50 MB, api.max_upload_mb)."""
    coglossa = {"base_url": "http://coglossa.test"}
    async with make_api(api={"max_upload_mb": 2}, integrations={"coglossa": coglossa}) as small:
        assert small.app.state.ctx.coglossa.max_bytes == 2 * 1024 * 1024
    async with make_api(api={"max_upload_mb": 500}, integrations={"coglossa": coglossa}) as big:
        assert big.app.state.ctx.coglossa.max_bytes == 50 * 1024 * 1024


async def test_a_utf8_user_name_survives_the_latin1_header_decoding(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        # httpx refuses non-ASCII str values, so send the wire bytes: UTF-8, which Starlette reads
        # as latin-1
        response = await api.client.get(
            "/api/system/info", headers=[(b"X-Remote-User", "José".encode())]
        )
        # a name that is not UTF-8 (latin-1 bytes) is kept as read
        raw = await api.client.get("/api/system/info", headers=[(b"X-Remote-User", b"Jos\xe9")])
    assert response.json()["user"] == "José"
    assert raw.json()["user"] == "José"


async def test_health_and_info_report_the_build_version(make_api, monkeypatch):
    """The image bakes the bundle version into CORELATA_BUILD_VERSION (spec §12); without it the
    package version stands, which the two tests above pin."""
    monkeypatch.setenv("CORELATA_BUILD_VERSION", "1.2.0-gabcdef0")
    async with make_api() as api:
        health = await api.client.get("/api/health")
        info = await api.client.get("/api/system/info")
    assert health.json() == {"status": "ok", "version": "1.2.0-gabcdef0"}
    assert info.json()["version"] == "1.2.0-gabcdef0"


@pytest.fixture
def shutdown(monkeypatch) -> list[str]:
    """What the lifespan closed at shutdown, in order: the progress feed and the database."""
    closed: list[str] = []
    real_close, real_dispose = app_module.ProgressFeed.close, app_module.Database.dispose

    async def close(self):
        closed.append("feed")
        await real_close(self)

    async def dispose(self):
        closed.append("db")
        await real_dispose(self)

    monkeypatch.setattr(app_module.ProgressFeed, "close", close)
    monkeypatch.setattr(app_module.Database, "dispose", dispose)
    return closed


async def test_a_listener_that_died_is_logged_and_the_shutdown_still_runs(
    write_config, monkeypatch, shutdown, caplog
):
    async def died(self):
        raise RuntimeError("listener bug")

    monkeypatch.setattr(app_module.RunListener, "run", died)
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)
    with caplog.at_level(logging.ERROR, logger="corelata.api"):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)  # the listener task runs and dies
    assert shutdown == ["feed", "db"]
    [record] = [r for r in caplog.records if "progress listener had stopped" in r.getMessage()]
    assert record.exc_info is not None and "listener bug" in str(record.exc_info[1])


async def test_a_cancelled_shutdown_is_not_swallowed(write_config, monkeypatch, shutdown):
    stopping, release = asyncio.Event(), asyncio.Event()
    listeners: list[asyncio.Task] = []

    async def slow_to_stop(self):  # a listener that takes a while to end once cancelled
        listeners.append(asyncio.current_task())
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await release.wait()
            raise

    monkeypatch.setattr(app_module.RunListener, "run", slow_to_stop)
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def lifespan() -> None:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    task = asyncio.create_task(lifespan())
    await stopping.wait()  # the listener is ending slowly: the shutdown is awaiting it
    task.cancel()  # the shutdown is cancelled while it awaits the listener (a second Ctrl-C)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()  # it ends cancelled: the cancellation is not swallowed
    assert shutdown == ["feed", "db"]  # and it still closed the feed and the database
    release.set()
    await asyncio.gather(*listeners, return_exceptions=True)
