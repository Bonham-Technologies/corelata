"""Spec §5.3: import a Coglossa run by id when integrations.coglossa is configured."""

import uuid

from corelata import service
from corelata.service import ConflictError
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from corelata_api.auth import User
from corelata_api.context import Ctx
from corelata_api.routes.projects import ADDED_RESPONSES, SourceView, added_views

router = APIRouter(tags=["projects"])


class FromCoglossa(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)


@router.post(
    "/projects/{project_id}/sources/from-coglossa", status_code=201, responses=ADDED_RESPONSES
)
async def source_from_coglossa(
    project_id: uuid.UUID, body: FromCoglossa, ctx: Ctx, user: User, response: Response
) -> list[SourceView]:
    """Fetch the run's export from Coglossa and add it like an uploaded export: the translation
    and, when it has one, its guide; 200 with those when the project has that export already
    (CRL-126). 409 when the integration is not configured."""
    if ctx.coglossa is None:
        raise ConflictError("integrations.coglossa is not configured")
    await service.get_project(ctx.db, project_id)
    data = await ctx.coglossa.fetch_export(body.run_id, user=user)
    added = await service.store_source(
        ctx.db,
        ctx.storage,
        project_id,
        f"coglossa-{body.run_id}.json",
        data,
        coglossa_export=True,
    )
    return await added_views(ctx, project_id, added, response)
