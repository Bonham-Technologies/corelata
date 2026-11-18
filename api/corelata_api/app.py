"""The FastAPI application (spec §10.1): one ApiContext per process, every /api route behind
current_user except health, openapi.json served behind auth. Copied from Coglossa."""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import corelata
import httpx
from corelata import service
from corelata.config import CorelataConfig
from corelata.integrations.coglossa import CoglossaClient
from corelata.prompts.library import PromptLibrary
from corelata.service import JobQueue
from corelata.storage import build_storage
from corelata.store.db import Database, database_url
from corelata.version import build_version
from corelata.worker.app import ProcrastinateQueue, open_app
from corelata.worker.kick import KickingQueue, build_kicker
from fastapi import APIRouter, Depends, FastAPI, Request

from corelata_api.auth import current_user
from corelata_api.context import ApiContext
from corelata_api.errors import ErrorBody, install_error_handlers
from corelata_api.pack_index import PackIndex
from corelata_api.progress_feed import ProgressFeed
from corelata_api.proxy import ProxySecretMiddleware
from corelata_api.render_cache import RenderCache
from corelata_api.routes import ROUTERS
from corelata_api.run_listener import Connect, RunListener, listen_connection
from corelata_api.web import mount_web

log = logging.getLogger("corelata.api")

QueueOpener = Callable[[str], AbstractAsyncContextManager[JobQueue]]
ListenerConnect = Callable[[str], Connect]


@contextlib.asynccontextmanager
async def procrastinate_queue(url: str) -> AsyncIterator[JobQueue]:
    """The job queue. open_app swaps the connector of procrastinate's shared app, so a process
    opens it once, here for the app's lifetime; any other opening (a worker in the same
    process, in tests) nests inside this one and is closed first."""
    async with open_app(url) as opened:
        yield ProcrastinateQueue(opened)


async def stop_listener(listener: asyncio.Task[None]) -> None:
    """Cancel the LISTEN task and wait for it to end (CRL-37). Its own cancellation is the
    expected end; a cancellation of the task stopping it (the lifespan, cancelled while it
    waits) is not ours to swallow and propagates. A listener that had died of an error is
    logged, so the rest of the shutdown still runs."""
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except Exception:
        log.exception("progress listener had stopped with an error")


health = APIRouter(prefix="/api", tags=["system"])
documents = APIRouter()


@documents.get("/openapi.json", include_in_schema=False)
async def get_openapi(request: Request) -> dict[str, Any]:
    return request.app.openapi()


@health.get("/health")
async def get_health() -> dict[str, str]:
    """Liveness: answers without the database and without a signed-in user."""
    # The bundle's version when the image carries one (spec §12); the docstring is the OpenAPI text.
    return {"status": "ok", "version": build_version()}


def create_app(
    cfg: CorelataConfig,
    config_path: Path,
    *,
    open_queue: QueueOpener = procrastinate_queue,
    coglossa_transport: httpx.AsyncBaseTransport | None = None,
    listener_connect: ListenerConnect = listen_connection,
) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(database_url(cfg))
        stalled_after_s = cfg.worker.stalled_after_s
        feed = ProgressFeed(
            lambda run_id: service.run_progress(db, run_id, stalled_after_s=stalled_after_s),
            cfg.api.progress_poll_s,
        )
        # One LISTEN connection for the process; the feed polls until it connects (CRL-22).
        listener = asyncio.create_task(RunListener(listener_connect(db.url), feed).run())
        try:
            async with open_queue(db.url) as queue:
                # the hosted demo: each queued job also starts an on-demand worker (M19)
                kicker = build_kicker(cfg.worker)
                if kicker is not None:
                    queue = KickingQueue(queue, kicker)
                try:
                    app.state.ctx = ApiContext(
                        cfg=cfg,
                        config_path=config_path,
                        db=db,
                        storage=build_storage(cfg.storage),
                        prompts=PromptLibrary(cfg.prompts_dir),
                        queue=queue,
                        coglossa=(
                            CoglossaClient(cfg.integrations.coglossa, transport=coglossa_transport)
                            if cfg.integrations.coglossa is not None
                            else None
                        ),
                        renders=RenderCache(max_bytes=cfg.api.render_cache_mb * 1024 * 1024),
                        progress=feed,
                        packs=PackIndex(cfg.standards.packs_dir),
                    )
                except BaseException:
                    if kicker is not None:  # nothing else would close its HTTP client
                        await kicker.aclose()
                    raise
                try:
                    yield
                finally:
                    if kicker is not None:
                        await kicker.aclose()
        finally:
            try:
                await stop_listener(listener)
            finally:
                await feed.close()
                await db.dispose()

    app = FastAPI(
        title="Corelata",
        version=corelata.__version__,
        summary="Standards-enforced intelligence report production with a full trace.",
        lifespan=lifespan,
        openapi_url=None,  # served below, behind auth
        docs_url=None,  # Swagger UI loads its assets from a CDN: blank on an air-gapped site
        redoc_url=None,
    )
    install_error_handlers(app)
    if cfg.auth.proxy_secret_env is not None:
        # validate_config refused an unset variable; the middleware refuses an empty one anyway
        secret = os.environ.get(cfg.auth.proxy_secret_env, "")
        app.add_middleware(ProxySecretMiddleware, secret=secret)
    app.include_router(health)
    protected = APIRouter(
        prefix="/api",
        dependencies=[Depends(current_user)],
        responses={
            401: {"model": ErrorBody, "description": "missing trusted header"},
            404: {"model": ErrorBody, "description": "not found"},
            409: {"model": ErrorBody, "description": "conflicts with the current data"},
            413: {"model": ErrorBody, "description": "upload too large"},
            422: {"description": "invalid request"},
            503: {"model": ErrorBody, "description": "the database or job queue is unavailable"},
        },
    )
    for router in [documents, *ROUTERS]:
        protected.include_router(router)
    app.include_router(protected)
    if cfg.api.web_dir is not None:
        mount_web(app, cfg.api.web_dir)
    return app
