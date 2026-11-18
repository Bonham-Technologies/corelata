"""Spec §10.1 `GET /runs/{id}/events`: progress as server-sent events. One reader per run however
many streams watch it (`ProgressFeed`, CRL-8), woken by the worker's NOTIFY (CRL-22) and polling
at api.progress_poll_s while the API's LISTEN connection is down. Copied from Coglossa."""

import asyncio
import uuid
from collections.abc import AsyncIterator

from corelata import service
from corelata.schema import TERMINAL_STATES, RunProgress
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from corelata_api.context import ApiContext, Ctx
from corelata_api.progress_feed import Deleted, Ended

router = APIRouter(tags=["runs"])

HEARTBEAT_S = 15.0  # comment lines keep proxies from closing a quiet stream


def _event(progress: RunProgress) -> str:
    return f"event: progress\ndata: {progress.model_dump_json()}\n\n"


async def _stream(ctx: ApiContext, run_id: uuid.UUID, first: RunProgress) -> AsyncIterator[str]:
    yield "retry: 3000\n\n"
    yield _event(first)
    last = first
    if last.state in TERMINAL_STATES:
        return
    queue = ctx.progress.subscribe(run_id, last)
    try:
        while last.state not in TERMINAL_STATES:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if isinstance(update, Deleted):
                yield "event: deleted\ndata: {}\n\n"
                return
            if isinstance(update, Ended):
                return  # the browser reconnects after `retry`
            if update != last:
                yield _event(update)
                last = update
    finally:
        ctx.progress.unsubscribe(run_id, queue)


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def run_events(run_id: uuid.UUID, ctx: Ctx) -> StreamingResponse:
    first = await service.run_progress(
        ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s
    )  # an unknown run is a plain 404
    return StreamingResponse(
        _stream(ctx, run_id, first),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
