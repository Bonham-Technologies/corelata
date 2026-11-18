"""Spec §10.1 runs: start, list, progress, cancel, review."""

import uuid
from typing import Annotated

from corelata import service
from corelata.schema import ReviewAction, RunProgress, RunSummary
from corelata.service import GUIDANCE_MAX_LENGTH, VALUE_STATEMENT_MAX_LENGTH
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from corelata_api.auth import User
from corelata_api.context import Ctx

router = APIRouter(tags=["runs"])


# The text limits are the service's (CRL-83, CRL-111); declaring them here puts them in the
# OpenAPI schema, which the web app's textareas follow.
class CreateRun(BaseModel):
    project_id: uuid.UUID
    source_ids: list[uuid.UUID] = Field(min_length=1)
    value_statement: str = Field(min_length=1, max_length=VALUE_STATEMENT_MAX_LENGTH)
    profile: str | None = None
    max_iterations: int | None = Field(None, ge=0, le=10)
    extra_guidance: str = Field("", max_length=GUIDANCE_MAX_LENGTH)
    parent_run_id: uuid.UUID | None = None  # rerun after a gate rejection, by hand


class ReviewRequest(BaseModel):
    action: ReviewAction
    note: str = Field("", max_length=GUIDANCE_MAX_LENGTH)


class ReviewResult(BaseModel):
    action: ReviewAction
    child: RunProgress | None  # the linked rerun a `return` created (spec §10.1)


class RunPage(BaseModel):
    """One page of a project's runs, newest first (keyset paging on created_at and id)."""

    runs: list[RunSummary]
    next_before: str | None = Field(
        description="Pass as `before` for the next page; null when this page is the last."
    )


@router.post("/runs", status_code=202)
async def create_run(body: CreateRun, ctx: Ctx) -> RunProgress:
    """Snapshot the pack, store the run and queue it; the worker does the rest unattended."""
    req = service.RunRequest(
        project_id=body.project_id,
        source_ids=body.source_ids,
        value_statement=body.value_statement,
        profile=body.profile,
        max_iterations=body.max_iterations,
        extra_guidance=body.extra_guidance,
        parent_run_id=body.parent_run_id,
    )
    run_id = await service.start_run(ctx.db, ctx.storage, ctx.queue, ctx.cfg, ctx.prompts, req)
    return await service.run_progress(
        ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s
    )


@router.get("/runs")
async def list_runs(
    ctx: Ctx,
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: Annotated[str | None, Query(max_length=100)] = None,
) -> RunPage:
    """A project's runs, newest first, `limit` at a time; `before` is the previous page's
    `next_before`."""
    after = service.parse_run_cursor(before) if before is not None else None
    found = await service.list_runs(ctx.db, project_id, limit=limit + 1, before=after)
    page = found[:limit]
    more = len(found) > limit  # one row past the page says whether another page exists
    return RunPage(runs=page, next_before=service.run_cursor(page[-1]) if more else None)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, ctx: Ctx) -> RunProgress:
    return await service.run_progress(
        ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, ctx: Ctx) -> RunProgress:
    """A run nothing executes yet ends at once, and so does a run whose worker is gone (its job
    is closed, so it never runs again); a run a live worker holds stops at its next stage
    boundary."""
    await service.cancel_run(ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s)
    return await service.run_progress(
        ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s
    )


@router.post("/runs/{run_id}/review")
async def review_run(run_id: uuid.UUID, body: ReviewRequest, ctx: Ctx, user: User) -> ReviewResult:
    """`accept` records the decision; `return` records it and queues a linked run seeded with
    the note as additional writer guidance."""
    child = await service.review_run(
        ctx.db,
        ctx.storage,
        ctx.queue,
        ctx.cfg,
        ctx.prompts,
        run_id,
        body.action,
        note=body.note,
        actor=user,
    )
    progress = (
        await service.run_progress(ctx.db, child, stalled_after_s=ctx.cfg.worker.stalled_after_s)
        if child is not None
        else None
    )
    return ReviewResult(action=body.action, child=progress)
