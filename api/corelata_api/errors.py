"""Engine exceptions → HTTP statuses, in one table; the body is always {"detail": "<one line>"}.
Copied from Coglossa with Corelata's exception types."""

import logging
from collections.abc import Awaitable, Callable

from corelata.config import ConfigError
from corelata.ingest.base import IngestError
from corelata.integrations.coglossa import CoglossaFetchError
from corelata.service import ConflictError, InvalidRequestError, QueueUnavailableError
from corelata.standards.loader import PackError
from corelata.storage import StorageError
from corelata.store.db import error_reason
from corelata.store.runs import NotFoundError
from corelata.trace import TraceError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import InterfaceError, OperationalError

from corelata_api.headers import SECURITY_HEADERS

log = logging.getLogger("corelata.api")

Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


class ErrorBody(BaseModel):
    detail: str


class UploadTooLargeError(Exception):
    """The upload is larger than api.max_upload_mb (HTTP 413)."""


_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (NotFoundError, 404),
    (TraceError, 404),  # a claim id the report does not have
    (ConflictError, 409),  # includes InvalidRunStateError
    (UploadTooLargeError, 413),
    (InvalidRequestError, 422),
    (IngestError, 422),
    (ConfigError, 500),
)

# An outage's driver message names hosts, ports and database roles: the log gets it, the
# client a fixed sentence (CRL-86).
DATABASE_DOWN = "the database is unavailable; the operator's log has the reason"
QUEUE_DOWN = "the job queue is unavailable; the operator's log has the reason"
# A storage message names local paths, buckets and endpoints: same rule (CRL-75).
STORAGE_DOWN = "the file store is unavailable; see the server log"


def _response(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": " ".join(message.split())})


def _handler(status: int) -> Handler:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return _response(status, str(exc))

    return handle


# Deadlock, serialization failure, lock not available: concurrent changes, not an outage.
_BUSY_SQLSTATES = frozenset({"40P01", "40001", "55P03"})


async def _database_down(request: Request, exc: Exception) -> JSONResponse:
    if getattr(getattr(exc, "orig", None), "sqlstate", None) in _BUSY_SQLSTATES:
        log.warning("database conflict: %s", error_reason(exc))
        return _response(409, "the database was busy with a conflicting change; try again")
    log.warning("database unavailable: %s", error_reason(exc))
    return _response(503, DATABASE_DOWN)


async def _queue_down(request: Request, exc: Exception) -> JSONResponse:
    # the job queue is the database; the message already carries the driver's reason
    log.warning("%s", exc)
    return _response(503, QUEUE_DOWN)


async def _storage_down(request: Request, exc: Exception) -> JSONResponse:
    log.error("file store unavailable on %s %s: %s", request.method, request.url.path, exc)
    return _response(500, STORAGE_DOWN)


async def _coglossa_failed(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CoglossaFetchError)
    if exc.log_detail is not None:
        log.warning("%s", exc.log_detail)
    return _response(exc.status, str(exc))


async def _pack_failed(request: Request, exc: Exception) -> JSONResponse:
    """An unknown pack or profile on POST /runs (422). A message that names server paths goes
    to the log; the client gets the pack's own name (CRL-114)."""
    assert isinstance(exc, PackError)
    if exc.public != str(exc):
        log.warning("%s", exc)
    return _response(422, exc.public)


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """A body, query or path that fails validation (422). Each error keeps its type, field and
    message, but not FastAPI's echo of the input: a lone surrogate pasted from a broken export
    cannot be encoded back, and the default handler failed with a 500 (CRL-128)."""
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


async def _internal(request: Request, exc: Exception) -> JSONResponse:
    log.error("internal error on %s %s", request.method, request.url.path, exc_info=exc)
    # sent by ServerErrorMiddleware, outside SecurityHeadersMiddleware (CRL-68)
    response = _response(500, "internal error")
    response.headers.update(SECURITY_HEADERS)
    return response


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status in _STATUS:
        app.add_exception_handler(exc_type, _handler(status))
    app.add_exception_handler(CoglossaFetchError, _coglossa_failed)
    app.add_exception_handler(PackError, _pack_failed)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(QueueUnavailableError, _queue_down)
    app.add_exception_handler(StorageError, _storage_down)
    # Mirrors corelata.worker.execute.DB_ERRORS (not imported: the API does not import the worker).
    app.add_exception_handler(OperationalError, _database_down)
    app.add_exception_handler(InterfaceError, _database_down)
    app.add_exception_handler(Exception, _internal)
