"""Spec §10.1: projects and their sources."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from corelata import service
from corelata.schema import LatestRun, ProjectSummary, SourceKind
from corelata.store.models import Project, SourceRow
from fastapi import APIRouter, Form, UploadFile
from pydantic import BaseModel, Field

from corelata_api.context import Ctx
from corelata_api.uploads import UploadRoute, read_upload

router = APIRouter(tags=["projects"])


class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)


_SUMMARY = {name: str(f.description) for name, f in ProjectSummary.model_fields.items()}


class ProjectView(BaseModel):
    """A project and what the sidebar shows for it (M18 spec §7.1)."""

    id: str
    name: str
    created_at: datetime
    last_activity_at: datetime = Field(description=_SUMMARY["last_activity_at"])
    reports_writing: int = Field(description=_SUMMARY["reports_writing"])
    reports_to_review: int = Field(description=_SUMMARY["reports_to_review"])
    latest_run: LatestRun | None = Field(description=_SUMMARY["latest_run"])

    @classmethod
    def of(cls, project: Project, summary: ProjectSummary) -> "ProjectView":
        return cls(
            id=str(project.id),
            name=project.name,
            created_at=project.created_at,
            **summary.model_dump(),
        )


class SourceView(BaseModel):
    id: str
    project_id: str
    kind: SourceKind
    name: str
    format: str
    sha256: str
    provenance: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, row: SourceRow) -> "SourceView":
        return cls(
            id=str(row.id),
            project_id=str(row.project_id),
            kind=SourceKind(row.kind),
            name=row.name,
            format=row.format,
            sha256=row.sha256,
            provenance=dict(row.provenance or {}),
            created_at=row.created_at,
        )


async def source_views(ctx: Ctx, project_id: uuid.UUID, ids: list[uuid.UUID]) -> list[SourceView]:
    """The views of `ids` in that order (what an upload just created)."""
    by_id = {row.id: row for row in await service.list_sources(ctx.db, project_id)}
    return [SourceView.of(by_id[i]) for i in ids]


@router.get("/projects")
async def list_projects(ctx: Ctx) -> list[ProjectView]:
    return [ProjectView.of(p, s) for p, s in await service.list_project_summaries(ctx.db)]


@router.post("/projects", status_code=201)
async def create_project(body: CreateProject, ctx: Ctx) -> ProjectView:
    project = await service.new_project(ctx.db, body.name)
    return ProjectView.of(project, service.new_project_summary(project))


@router.get("/projects/{project_id}")
async def get_project(project_id: uuid.UUID, ctx: Ctx) -> ProjectView:
    return ProjectView.of(*await service.get_project_summary(ctx.db, project_id))


@router.get("/projects/{project_id}/sources")
async def list_sources(project_id: uuid.UUID, ctx: Ctx) -> list[SourceView]:
    return [SourceView.of(r) for r in await service.list_sources(ctx.db, project_id)]


async def upload_source(
    project_id: uuid.UUID,
    ctx: Ctx,
    file: UploadFile,
    kind: Annotated[SourceKind, Form()] = SourceKind.FILE,
) -> list[SourceView]:
    """Store and parse one upload (spec §5): one source, or two for a Coglossa export that
    carries a translation guide. Nothing is kept when the file cannot be parsed."""
    await service.get_project(ctx.db, project_id)  # 404 before reading the body
    data = await read_upload(file, ctx.cfg.api.max_upload_mb)
    ids = await service.add_source(
        ctx.db,
        ctx.storage,
        project_id,
        file.filename or "",
        data,
        coglossa_export=kind is SourceKind.COGLOSSA_EXPORT,
    )
    return await source_views(ctx, project_id, ids)


# UploadRoute answers 413 for an over-limit body before it is spooled (CRL-88, CRL-104).
router.add_api_route(
    "/projects/{project_id}/sources",
    upload_source,
    methods=["POST"],
    status_code=201,
    route_class_override=UploadRoute,
)
