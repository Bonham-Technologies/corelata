"""Spec §7.1, §10.1: a discovery proposes value statements; it never starts a run."""

import uuid

from corelata import service
from corelata.schema import DiscoveryView
from fastapi import APIRouter
from pydantic import BaseModel, Field

from corelata_api.context import ApiContext, Ctx

router = APIRouter(tags=["discoveries"])

AUDIENCE_HINT_MAX_LENGTH = 500  # a hint, not a document; it goes into the discovery prompt (CRL-83)


class CreateDiscovery(BaseModel):
    project_id: uuid.UUID
    source_ids: list[uuid.UUID] = Field(min_length=1)
    audience_hint: str = Field("", max_length=AUDIENCE_HINT_MAX_LENGTH)


@router.post("/discoveries", status_code=202)
async def create_discovery(body: CreateDiscovery, ctx: Ctx) -> DiscoveryView:
    discovery_id = await service.start_discovery(
        ctx.db, ctx.queue, body.project_id, body.source_ids, body.audience_hint
    )
    return await _read(ctx, discovery_id)


@router.get("/discoveries/{discovery_id}")
async def get_discovery(discovery_id: uuid.UUID, ctx: Ctx) -> DiscoveryView:
    return await _read(ctx, discovery_id)


async def _read(ctx: ApiContext, discovery_id: uuid.UUID) -> DiscoveryView:
    # past the limit that applies, the read fails it: the limits hold with no worker running
    # (R-M17-1, R-M17-26)
    return await service.get_discovery(
        ctx.db,
        discovery_id,
        deadline_s=ctx.cfg.worker.discovery_deadline_s,
        start_deadline_s=ctx.cfg.worker.discovery_start_deadline_s,
    )
