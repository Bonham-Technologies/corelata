"""Spec §5.3: import a Coglossa run by id when integrations.coglossa is configured."""

import uuid

from corelata import service
from corelata.service import ConflictError
from fastapi import APIRouter
from pydantic import BaseModel, Field

from corelata_api.auth import User
from corelata_api.context import Ctx
from corelata_api.routes.projects import SourceView, source_views

router = APIRouter(tags=["projects"])


class FromCoglossa(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)


@router.post("/projects/{project_id}/sources/from-coglossa", status_code=201)
async def source_from_coglossa(
    project_id: uuid.UUID, body: FromCoglossa, ctx: Ctx, user: User
) -> list[SourceView]:
    """Fetch the run's export from Coglossa and add it like an uploaded export: the translation
    and, when it has one, its guide. 409 when the integration is not configured."""
    if ctx.coglossa is None:
        raise ConflictError("integrations.coglossa is not configured")
    await service.get_project(ctx.db, project_id)
    data = await ctx.coglossa.fetch_export(body.run_id, user=user)
    ids = await service.add_source(
        ctx.db,
        ctx.storage,
        project_id,
        f"coglossa-{body.run_id}.json",
        data,
        coglossa_export=True,
    )
    return await source_views(ctx, project_id, ids)
