"""Spec §10.1 report and trace views. The report is served from the worker's stored export
(spec §8.4 invariant 5) unless claim ids are requested, which re-renders from the stored record
once per run and format (CRL-9); every byte here comes from the database and storage, never from
a model."""

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from corelata import service
from corelata.exports import render_outputs
from corelata.schema import Finding, RunRecord, RunState
from corelata.service import InvalidRunStateError
from corelata.standards.schema import ResolvedPack
from corelata.store.runs import NotFoundError
from corelata.trace import ClaimProvenance, RunTrace, run_trace
from fastapi import APIRouter, Response

from corelata_api.context import ApiContext, Ctx
from corelata_api.headers import REPORT_CSP
from corelata_api.uploads import content_disposition

router = APIRouter(tags=["reports"])

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MEDIA = {
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "docx": DOCX,
}
Format = Literal["json", "md", "html", "docx"]
ExportName = Literal[
    "trace.json", "gate.json", "report.json", "report.md", "report.html", "report.docx"
]


def _file(content: bytes, *, media: str, filename: str, attachment: bool) -> Response:
    headers = {"Content-Disposition": content_disposition(filename, inline=not attachment)}
    if media == MEDIA["html"]:
        headers["Content-Security-Policy"] = REPORT_CSP  # CRL-68
    return Response(content=content, media_type=media, headers=headers)


async def _record_with_report(ctx: ApiContext, run_id: uuid.UUID) -> RunRecord:
    record = await service.get_run_record(ctx.db, run_id)
    if record.report is None:
        raise InvalidRunStateError(f"run {run_id} has no report (state {record.state.value})")
    return record


def _render(record: RunRecord, fmt: str, *, with_claim_ids: bool, reference: bytes | None) -> bytes:
    """One export from the stored record, off the event loop; the DOCX reads the run's stored
    reference document from a temporary file."""
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        path: Path | None = None
        if fmt == "docx" and reference is not None:
            path = Path(tmp) / "reference.docx"
            path.write_bytes(reference)
        out = render_outputs(
            record,
            pack,
            with_claim_ids=with_claim_ids,
            docx_claim_ids=with_claim_ids,
            docx_reference=path,
            formats=(fmt,),
        )[f"report.{fmt}"]
    return out if isinstance(out, bytes) else out.encode("utf-8")


async def _claim_ids_render(ctx: ApiContext, run_id: uuid.UUID, fmt: str) -> bytes:
    """The re-render, once per (run, format) for the life of the process (R-M9-5): the record is
    loaded only here, and only on a miss."""
    cached = ctx.renders.get(str(run_id), fmt)
    if cached is not None:
        return cached
    record = await _record_with_report(ctx, run_id)
    reference = None
    if fmt == "docx":
        reference = await service.reference_document(ctx.db, ctx.storage, run_id)
    try:
        content = await asyncio.to_thread(
            _render, record, fmt, with_claim_ids=True, reference=reference
        )
    except Exception as e:
        if fmt != "docx":
            raise
        raise InvalidRunStateError(f"DOCX export failed: {str(e) or type(e).__name__}") from e
    ctx.renders.put(str(run_id), fmt, content)
    return content


@router.get(
    "/runs/{run_id}/report",
    response_class=Response,
    responses={200: {"content": {media: {} for media in MEDIA.values()}}},
)
async def get_report(
    run_id: uuid.UUID,
    ctx: Ctx,
    format: Format = "html",
    with_claim_ids: bool = False,
    download: bool = False,
) -> Response:
    """The delivered report. Without claim ids: the worker's stored file, byte for byte (404 if
    none is stored). With them: re-rendered from the stored record (spec §9). 409 while the run
    has no report, or when its DOCX export failed."""
    progress = await service.run_progress(ctx.db, run_id)  # an unknown run is a plain 404
    if progress.state is not RunState.COMPLETED:
        raise InvalidRunStateError(f"run {run_id} has no report (state {progress.state.value})")
    if format == "docx" and progress.export_error:
        raise InvalidRunStateError(progress.export_error)
    if with_claim_ids:
        content = await _claim_ids_render(ctx, run_id, format)
    else:
        stored = await service.stored_export(ctx.db, ctx.storage, run_id, f"report.{format}")
        if stored is None:
            raise NotFoundError(f"run {run_id} has no stored export report.{format}")
        content = stored
    return _file(
        content,
        media=MEDIA[format],
        filename=f"report-{str(run_id)[:8]}.{format}",
        attachment=download or format == "docx",
    )


@router.get(
    "/runs/{run_id}/exports/{name}",
    response_class=Response,
    responses={200: {"content": {media: {} for media in MEDIA.values()}}},
)
async def get_export(run_id: uuid.UUID, name: ExportName, ctx: Ctx) -> Response:
    """A file the worker stored for the run, as stored (the trace JSON download among them)."""
    content = await service.stored_export(ctx.db, ctx.storage, run_id, name)
    if content is None:
        raise NotFoundError(f"run {run_id} has no stored export {name}")
    stem, ext = name.rsplit(".", 1)
    return _file(
        content,
        media=MEDIA[ext],
        filename=f"{stem}-{str(run_id)[:8]}.{ext}",
        attachment=True,
    )


@router.get("/runs/{run_id}/trace")
async def get_trace(run_id: uuid.UUID, ctx: Ctx) -> RunTrace:
    """Summary, draft-to-draft changes and model calls (spec §10.3 Process tab), any state."""
    # The calls are summaries without their bodies: the stored request and response are not
    # read (CRL-103). The docstrings here are the OpenAPI descriptions.
    return run_trace(await service.get_run_record(ctx.db, run_id, with_io=False))


@router.get("/runs/{run_id}/findings")
async def get_findings(run_id: uuid.UUID, ctx: Ctx) -> list[Finding]:
    """Every audit finding, all iterations (spec §10.3 Audit tab)."""
    # the finding rows alone (CRL-103)
    return await service.get_findings(ctx.db, run_id)


@router.get("/runs/{run_id}/claims/{claim_id}")
async def get_claim(run_id: uuid.UUID, claim_id: str, ctx: Ctx) -> ClaimProvenance:
    """A claim with its evidence units (spec §10.3 Provenance tab). 409 without a report, 404
    for a claim the report does not have."""
    # the report and the sources' units alone (CRL-103)
    return await service.get_claim_provenance(ctx.db, run_id, claim_id)
