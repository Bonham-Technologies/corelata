"""Spec §10.1: projects and their sources."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from corelata import service
from corelata.schema import LatestRun, ProjectSummary, SourceKind, SourceStatement
from corelata.schema.source import STATED_MAX_LENGTH
from corelata.store.models import Project, SourceRow
from fastapi import APIRouter, Form, Response, UploadFile
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
    stated: SourceStatement = Field(
        default_factory=SourceStatement,
        description=(
            "What the analyst states about the source for its entry in a report (CRL-138); a run "
            "writes each stated value over the model's. Left out when nothing is stated."
        ),
        exclude_if=lambda stated: not stated.values(),
    )
    created_at: datetime
    already_in_project: bool = Field(
        default=False,
        description=(
            "True on an upload's or a Coglossa import's answer (200, not 201) when the project "
            "had this file already, by sha256: the source it has, and nothing was added "
            "(CRL-126). Always false in a list."
        ),
    )

    @classmethod
    def of(cls, row: SourceRow, *, already_in_project: bool = False) -> "SourceView":
        return cls(
            id=str(row.id),
            project_id=str(row.project_id),
            kind=SourceKind(row.kind),
            name=row.name,
            format=row.format,
            sha256=row.sha256,
            provenance=dict(row.provenance or {}),
            stated=SourceStatement.model_validate(row.stated or {}),
            created_at=row.created_at,
            already_in_project=already_in_project,
        )


# An upload or an import of a file the project has already answers 200 with that source.
ADDED_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": list[SourceView],
        "description": "the project had this file already: its source, already_in_project",
    },
}


async def added_views(
    ctx: Ctx, project_id: uuid.UUID, added: service.AddedSources, response: Response
) -> list[SourceView]:
    """The views of what an upload gave, in its order; 200 when the project had the file."""
    if added.existing:
        response.status_code = 200
    by_id = {row.id: row for row in await service.list_sources(ctx.db, project_id)}
    return [SourceView.of(by_id[i], already_in_project=added.existing) for i in added.ids]


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


def _stated(name: str, description: str) -> Any:
    return Field(None, max_length=STATED_MAX_LENGTH[name], description=description)


class SourceEdit(BaseModel):
    """What the analyst states about a source (CRL-138). A field left out stays as it is; an
    empty string clears it, and the model infers it again."""

    descriptor: str | None = _stated(
        "descriptor", "A source descriptor phrase from the pack's lexicon"
    )
    reliability_note: str | None = _stated(
        "reliability_note", "The source's reliability, currency and completeness"
    )
    date_of_information: str | None = _stated(
        "date_of_information", "When the source's information was issued or current"
    )
    origin: str | None = _stated("origin", "Who originated, authored or published the information")
    access: str | None = _stated(
        "access", "The source's access to what it reports, a term from the lexicon's source_access"
    )

    def changes(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)


@router.patch("/projects/{project_id}/sources/{source_id}")
async def edit_source(
    project_id: uuid.UUID, source_id: uuid.UUID, body: SourceEdit, ctx: Ctx
) -> SourceView:
    """Set what the analyst states about a source (CRL-138): its descriptor and access are
    checked against the default pack's lexicon, and a run checks them again against its own. A
    run already queued keeps the values it was queued with."""
    return SourceView.of(
        await service.edit_source(ctx.db, ctx.cfg, project_id, source_id, body.changes())
    )


def _form(name: str) -> Any:
    return Form(max_length=STATED_MAX_LENGTH[name])


async def upload_source(
    project_id: uuid.UUID,
    ctx: Ctx,
    response: Response,
    file: UploadFile,
    kind: Annotated[SourceKind, Form()] = SourceKind.FILE,
    descriptor: Annotated[str | None, _form("descriptor")] = None,
    reliability_note: Annotated[str | None, _form("reliability_note")] = None,
    date_of_information: Annotated[str | None, _form("date_of_information")] = None,
    origin: Annotated[str | None, _form("origin")] = None,
    access: Annotated[str | None, _form("access")] = None,
) -> list[SourceView]:
    """Store and parse one upload (spec §5): one source, or two for a Coglossa export that
    carries a translation guide. Nothing is kept when the file cannot be parsed. With
    `ingest.ocr: auto` a PDF's scanned pages are read by OCR before the answer (CRL-95). A file
    the project has already (same sha256 and kind) is not added again: 200 with that source
    (CRL-126). The optional `descriptor`, `reliability_note`, `date_of_information`, `origin`
    and `access` are what the analyst states about the source, as `PATCH` sets them (CRL-138);
    for a file the project has already they are set on that source."""
    given = {
        "descriptor": descriptor,
        "reliability_note": reliability_note,
        "date_of_information": date_of_information,
        "origin": origin,
        "access": access,
    }
    stated = {k: v for k, v in given.items() if v is not None}
    await service.get_project(ctx.db, project_id)  # 404 before reading the body
    statement = await service.check_statement(ctx.cfg, stated) if stated else None
    data = await read_upload(file, ctx.cfg.api.max_upload_mb)
    added = await service.store_source(
        ctx.db,
        ctx.storage,
        project_id,
        file.filename or "",
        data,
        coglossa_export=kind is SourceKind.COGLOSSA_EXPORT,
        ocr=ctx.cfg.ingest.ocr_settings(),  # scanned PDF pages are read here, off the loop
        statement=statement,
    )
    return await added_views(ctx, project_id, added, response)


# UploadRoute answers 413 for an over-limit body before it is spooled (CRL-88, CRL-104).
router.add_api_route(
    "/projects/{project_id}/sources",
    upload_source,
    methods=["POST"],
    status_code=201,
    responses=ADDED_RESPONSES,
    route_class_override=UploadRoute,
)
