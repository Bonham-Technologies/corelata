"""Data access for projects, sources, runs and everything a run produces (spec §8.3). Functions
take an AsyncSession and never commit: the caller owns the transaction
(`async with db.session() as s, s.begin(): ...`)."""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Row,
    Text,
    and_,
    cast,
    delete,
    func,
    null,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from corelata.schema import (
    TERMINAL_STATES,
    BlockKind,
    DraftRecord,
    Finding,
    LatestRun,
    LLMCallRecord,
    PriorJudgment,
    PriorReport,
    ProjectSummary,
    Report,
    ReviewDecision,
    RunState,
    Source,
    SourceKind,
    SourceStatement,
    SourceUnit,
    StageResult,
    Verdict,
    split_ref,
)
from corelata.store.db import error_reason
from corelata.store.models import (
    AuditFindingRow,
    ClaimEvidenceRow,
    ClaimRow,
    DraftRow,
    ExportRow,
    LLMCall,
    Project,
    ReviewEvent,
    Run,
    RunSource,
    SourceRow,
    SourceUnitRow,
    StageResultRow,
)

log = logging.getLogger("corelata.store")

_BATCH = 1000

# The channel every change to a run's progress is announced on; the payload is the run id. The
# API's progress listener LISTENs on it (CRL-22, R-M14-3).
RUN_CHANNEL = "corelata_run"
_NOTIFY = text("SELECT pg_notify(:channel, :payload)")


class NotFoundError(LookupError):
    """A requested row does not exist; the message is safe to show to a user."""


async def notify_run(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Announce a change to the run in the caller's transaction: Postgres delivers
    `NOTIFY corelata_run, '<run_id>'` to every listener when the transaction commits, never if
    it rolls back, and once however often one transaction calls this. Call it after the
    transaction's writes to the run. The flush comes first, so a failing write still fails here;
    the notification itself runs in a savepoint, and its failure is logged and swallowed: a
    progress stream falls back to its heartbeat, a run never fails for it (R-M14-3)."""
    await s.flush()
    try:
        async with s.begin_nested():
            await s.execute(_NOTIFY, {"channel": RUN_CHANNEL, "payload": str(run_id)})
    except SQLAlchemyError as e:
        if isinstance(e, DBAPIError) and e.connection_invalidated:
            raise  # a lost connection is the caller's DB error, not a notification failure
        log.warning(
            "run %s: progress notification not sent: %s",
            run_id,
            error_reason(e),
            extra={"run_id": str(run_id)},
        )


# ---------------------------------------------------------------- projects


async def get_or_create_project(s: AsyncSession, name: str) -> Project:
    await s.execute(
        pg_insert(Project)
        .values(id=uuid.uuid4(), name=name)
        .on_conflict_do_nothing(index_elements=[Project.name])
    )
    return await find_project(s, name)


async def find_project(s: AsyncSession, name: str) -> Project:
    project = await s.scalar(select(Project).where(Project.name == name))
    if project is None:
        raise NotFoundError(f"project '{name}' not found")
    return project


async def get_project(s: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await s.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project


async def list_projects(s: AsyncSession) -> list[Project]:
    return list(await s.scalars(select(Project).order_by(Project.created_at, Project.name)))


# A return whose revision ended in one of these produced no report, so the run is to review
# again (R-M15-1); the same set as `service.FREED_BY`, which a test pins.
FREED_BY = TERMINAL_STATES - {RunState.COMPLETED}
_TERMINAL = sorted(state.value for state in TERMINAL_STATES)
_FREED = sorted(state.value for state in FREED_BY)


def _review_field(name: str) -> Any:
    """A field of the stored `ReviewState` JSON as text; NULL when the run has none."""
    return func.jsonb_extract_path_text(Run.review_state, name)


# Each project's newest run, by the run list's order (CRL-24), which `ix_run_project_created`
# serves. Written out: SQLAlchemy 2.1 deprecates `.distinct(column)` for DISTINCT ON, and its
# replacement does not exist in 2.0, which the engine's dependency floor still allows.
_LATEST_RUN = (
    "SELECT DISTINCT ON (project_id) project_id, id, state, status, "
    "review_state->>'decision' AS decision, review_state->>'child_state' AS child_state "
    "FROM run {where}"
    "ORDER BY project_id, created_at DESC, id DESC"
)


def _to_review() -> Any:
    """A completed run nobody decided on, or whose return's revision ended without a report. A
    check run (CRL-94) is never to review: it takes no decision (R-CRL94-6)."""
    decision = _review_field("decision")
    freed = and_(decision == "returned", _review_field("child_state").in_(_FREED))
    return and_(
        Run.state == RunState.COMPLETED.value,
        Run.kind == "report",
        or_(decision.is_(None), freed),
    )


async def project_summaries(
    s: AsyncSession, project_id: uuid.UUID | None = None
) -> list[tuple[Project, ProjectSummary]]:
    """Every project (or the one `project_id` names) with its summary, in `list_projects`'s
    order: three statements whatever the number of projects, never one per project (M18 spec
    §7.1, R-M18-3). (1) the projects with their newest source's `created_at`; (2) one aggregate
    over `run` grouped by project, with FILTER clauses; (3) each project's newest run by
    `DISTINCT ON (project_id)`, which `ix_run_project_created` serves."""
    newest_source = (
        select(SourceRow.project_id, func.max(SourceRow.created_at).label("at"))
        .group_by(SourceRow.project_id)
        .subquery()
    )
    projects = (
        select(Project, newest_source.c.at)
        .outerjoin(newest_source, newest_source.c.project_id == Project.id)
        .order_by(Project.created_at, Project.name)
    )
    counts = select(
        Run.project_id,
        func.count().filter(Run.state.not_in(_TERMINAL)).label("writing"),
        func.count().filter(_to_review()).label("to_review"),
        func.max(Run.created_at).label("created"),
        func.max(Run.finished_at).label("finished"),
    ).group_by(Run.project_id)
    where, params = "", {}
    if project_id is not None:
        projects = projects.where(Project.id == project_id)
        counts = counts.where(Run.project_id == project_id)
        where, params = "WHERE project_id = :project_id ", {"project_id": project_id}
    latest = text(_LATEST_RUN.format(where=where))
    rows = (await s.execute(projects)).all()
    by_project = {r.project_id: r for r in await s.execute(counts)}
    newest = {r.project_id: r for r in await s.execute(latest, params)}
    found: list[tuple[Project, ProjectSummary]] = []
    for project, source_at in rows:
        count = by_project.get(project.id)
        run = newest.get(project.id)
        stamps = [project.created_at, source_at]
        if count is not None:
            stamps += [count.created, count.finished]
        found.append(
            (
                project,
                ProjectSummary(
                    last_activity_at=max(t for t in stamps if t is not None),
                    reports_writing=count.writing if count else 0,
                    reports_to_review=count.to_review if count else 0,
                    latest_run=LatestRun(
                        run_id=str(run.id),
                        state=RunState(run.state),
                        status=run.status,
                        decision=run.decision,
                        child_state=run.child_state,
                    )
                    if run
                    else None,
                ),
            )
        )
    return found


async def delete_project(s: AsyncSession, project_id: uuid.UUID) -> None:
    await s.delete(await get_project(s, project_id))
    await s.flush()


# ---------------------------------------------------------------- sources


async def _insert_many(s: AsyncSession, table: Any, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), _BATCH):
        await s.execute(pg_insert(table).values(rows[start : start + _BATCH]))


async def add_source(
    s: AsyncSession,
    project_id: uuid.UUID,
    source: Source,
    *,
    storage_key: str,
    source_id: uuid.UUID | None = None,
) -> SourceRow:
    """Store a parsed source and its units. `source.id` (the in-run name) is not kept: a run
    names its sources src1, src2, … by position (see RunSource). `source.stated` is kept
    (CRL-138), NULL when nothing is stated."""
    row = SourceRow(
        id=source_id or uuid.uuid4(),
        project_id=project_id,
        kind=source.kind.value,
        name=source.name,
        format=source.format,
        sha256=source.sha256,
        storage_key=storage_key,
        provenance=dict(source.provenance),
        stated=stated_json(source.stated),
    )
    s.add(row)
    await s.flush()
    await _insert_many(
        s,
        SourceUnitRow.__table__,
        [
            {
                "source_id": row.id,
                "ordinal": i,
                "unit_id": u.id,
                "text": u.text,
                "locator": u.locator,
                "kind": u.kind.value,
                "meta": u.meta,
            }
            for i, u in enumerate(source.units, start=1)
        ],
    )
    return row


async def find_source(
    s: AsyncSession, project_id: uuid.UUID, sha256: str, kind: SourceKind
) -> list[uuid.UUID]:
    """The ids of the project's earliest source of this kind made from a file with this
    sha256, with the rows that share its stored file (a Coglossa export's guide), in list
    order; empty when the project has none (CRL-126). A project from before CRL-126 may hold
    the file twice: the first one answers."""
    key = await s.scalar(
        select(SourceRow.storage_key)
        .where(
            SourceRow.project_id == project_id,
            SourceRow.sha256 == sha256,
            SourceRow.kind == kind.value,
        )
        .order_by(SourceRow.created_at, SourceRow.id)
        .limit(1)
    )
    if key is None:
        return []
    return list(
        await s.scalars(
            select(SourceRow.id)
            .where(SourceRow.project_id == project_id, SourceRow.storage_key == key)
            .order_by(SourceRow.created_at, SourceRow.id)
        )
    )


async def lock_project(s: AsyncSession, project_id: uuid.UUID) -> None:
    """Hold the project row until the transaction ends, so two uploads of one file cannot both
    find nothing and both insert (CRL-126). FOR NO KEY UPDATE: inserting runs and sources,
    which takes KEY SHARE on the project, is not held up."""
    await s.execute(
        select(Project.id).where(Project.id == project_id).with_for_update(key_share=True)
    )


async def get_source(s: AsyncSession, source_id: uuid.UUID) -> SourceRow:
    row = await s.get(SourceRow, source_id)
    if row is None:
        raise NotFoundError(f"source {source_id} not found")
    return row


async def list_sources(s: AsyncSession, project_id: uuid.UUID) -> list[SourceRow]:
    return list(
        await s.scalars(
            select(SourceRow)
            .where(SourceRow.project_id == project_id)
            .order_by(SourceRow.created_at, SourceRow.id)
        )
    )


def stated_json(stated: SourceStatement) -> dict[str, str] | None:
    """A statement as its column holds it: NULL when nothing is stated (CRL-138)."""
    return stated.values() or None


async def set_source_statement(
    s: AsyncSession, source_id: uuid.UUID, stated: SourceStatement
) -> SourceRow:
    """Replace what the analyst states about a source (CRL-138); a run already queued keeps the
    statement it was queued with (`RunSource.stated`)."""
    row = await get_source(s, source_id)
    row.stated = stated_json(stated)
    await s.flush()
    return row


async def load_source(
    s: AsyncSession,
    row: SourceRow,
    *,
    as_id: str,
    unit_ids: Collection[str] | None = None,
    stated: dict[str, Any] | None = None,
) -> Source:
    """`unit_ids`: only the units with those ids, and none (nor a query) when it is empty
    (CRL-124). `stated`: what the analyst stated about the source as a run snapshot it
    (`RunSource.stated`, CRL-138); nothing stated when None. The units are read as plain rows,
    their `meta` as JSON text, and parsed and validated off the event loop, which a source of
    tens of thousands of units would otherwise hold for most of a second."""
    rows: Sequence[Row[Any]] = ()
    if unit_ids is None or unit_ids:
        query = select(
            SourceUnitRow.unit_id,
            SourceUnitRow.text,
            SourceUnitRow.locator,
            SourceUnitRow.kind,
            cast(SourceUnitRow.meta, Text),
        ).where(SourceUnitRow.source_id == row.id)
        if unit_ids is not None:
            query = query.where(SourceUnitRow.unit_id.in_(sorted(unit_ids)))
        rows = (await s.execute(query.order_by(SourceUnitRow.ordinal))).all()
    head = {
        "id": as_id,
        "kind": SourceKind(row.kind),
        "name": row.name,
        "format": row.format,
        "sha256": row.sha256,
        "provenance": dict(row.provenance),
        "stated": SourceStatement.model_validate(stated or {}),
    }
    return await asyncio.to_thread(_source, head, rows)


def _source(head: dict[str, Any], rows: Sequence[Row[Any]]) -> Source:
    units = [
        SourceUnit(
            id=unit_id, text=body, locator=locator, kind=BlockKind(kind), meta=json.loads(meta)
        )
        for unit_id, body, locator, kind, meta in rows
    ]
    return Source(**head, units=units)


# ---------------------------------------------------------------- runs


async def db_now(s: AsyncSession) -> datetime:
    """The database's `now()`, the start of `s`'s transaction. Every time written on a run or a
    discovery is the database's (CRL-53, CRL-87), so hosts whose clocks disagree agree on ages."""
    now = await s.scalar(select(func.now()))
    assert now is not None
    return now


async def create_run(
    s: AsyncSession,
    *,
    project_id: uuid.UUID,
    value_statement: str,
    profile: str | None,
    max_iterations: int,
    extra_guidance: str,
    config_hash: str,
    config_snapshot: dict[str, Any],
    pack_name: str,
    pack_hash: str,
    pack_snapshot: dict[str, Any],
    prompt_versions: dict[str, int],
    corelata_version: str,
    docx_reference_key: str | None,
    parent_run_id: uuid.UUID | None,
    source_ids: list[uuid.UUID],
    run_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    kind: str = "report",
    report_source_id: uuid.UUID | None = None,
) -> Run:
    """A run row plus its ordered sources; every source, and a check run's report (CRL-94),
    must belong to the project. Each source's statement is copied as it stands now (CRL-138),
    so a later edit does not change the run."""
    rows = {r.id: r for r in await list_sources(s, project_id)}
    for sid in [*source_ids, *([report_source_id] if report_source_id else [])]:
        if sid not in rows:
            raise NotFoundError(f"source {sid} not in project {project_id}")
    run = Run(
        id=run_id or uuid.uuid4(),
        project_id=project_id,
        kind=kind,
        report_source_id=report_source_id,
        parent_run_id=parent_run_id,
        value_statement=value_statement,
        extra_guidance=extra_guidance,
        profile=profile,
        max_iterations=max_iterations,
        config_hash=config_hash,
        config_snapshot=config_snapshot,
        pack_name=pack_name,
        pack_hash=pack_hash,
        pack_snapshot=pack_snapshot,
        prompt_versions=prompt_versions,
        corelata_version=corelata_version,
        docx_reference_key=docx_reference_key,
        digests=[],
    )
    if created_at is not None:
        run.created_at = created_at
    s.add(run)
    await s.flush()
    s.add_all(
        RunSource(
            run_id=run.id,
            ordinal=i,
            source_id=sid,
            # a check run audits a report as its author wrote it: nothing is written over it
            stated=rows[sid].stated if kind == "report" else None,
        )
        for i, sid in enumerate(source_ids, start=1)
    )
    await s.flush()
    return run


async def get_run(s: AsyncSession, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    query = select(Run).where(Run.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = await s.scalar(query)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run


HEAVY_RUN_COLUMNS = (
    Run.report,
    Run.pack_snapshot,
    Run.config_snapshot,
    Run.digests,
    Run.gate,
    Run.prior_reports,
)


async def get_run_brief(s: AsyncSession, run_id: uuid.UUID) -> Run:
    """The run row without its large JSON columns, for progress views (CRL-8, R-M9-3). The
    deferred attributes must not be read: in an async session a lazy load raises."""
    query = select(Run).where(Run.id == run_id).options(*(defer(c) for c in HEAVY_RUN_COLUMNS))
    run = await s.scalar(query)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run


async def list_runs(
    s: AsyncSession,
    project_id: uuid.UUID,
    *,
    limit: int,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[Run]:
    """A project's runs, newest first: `(created_at, id)` descending, so runs created in the same
    microsecond keep one order. `before` is the `(created_at, id)` of the last run of the previous
    page; the page holds the runs after it in that order (keyset paging, CRL-24). The large JSON
    columns are deferred, as in `get_run_brief`: a summary never reads them (CRL-51)."""
    query = (
        select(Run)
        .where(Run.project_id == project_id)
        .options(*(defer(c) for c in HEAVY_RUN_COLUMNS))
    )
    if before is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < tuple_(*before))
    return list(await s.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit)))


async def accepted_reports(
    s: AsyncSession, project_id: uuid.UUID, *, limit: int, exclude: uuid.UUID | None = None
) -> list[PriorReport]:
    """The project's newest accepted reports (CRL-97): its completed runs whose stored review
    decision is an accept (`ReviewState`; a live return wins over an accept, R-M9-1), newest
    accept first (ties by id), at most `limit`, never `exclude` (the run that reads them). Only
    each report's title and key judgments are read, not the report."""
    at = _review_field("at")
    query = (
        select(
            Run.id,
            func.jsonb_extract_path_text(Run.report, "title").label("title"),
            func.jsonb_extract_path(Run.report, "key_judgments", type_=JSONB).label("judgments"),
            at.label("at"),
        )
        .where(
            Run.project_id == project_id,
            Run.state == RunState.COMPLETED.value,
            _review_field("decision") == ReviewDecision.ACCEPTED.value,
        )
        .order_by(cast(at, TIMESTAMP(timezone=True)).desc(), Run.id.desc())
        .limit(limit)
    )
    if exclude is not None:
        query = query.where(Run.id != exclude)
    return [
        PriorReport(
            run_id=str(row.id),
            title=row.title or "",
            accepted_at=row.at,
            key_judgments=[
                PriorJudgment(text=kj["text"], confidence=kj["confidence"])
                for kj in row.judgments or []
            ],
        )
        for row in await s.execute(query)
    ]


async def run_sources(
    s: AsyncSession, run_id: uuid.UUID
) -> list[tuple[uuid.UUID, dict[str, Any] | None]]:
    """The run's sources in order, each with the statement it was queued with (CRL-138)."""
    rows = await s.execute(
        select(RunSource.source_id, RunSource.stated)
        .where(RunSource.run_id == run_id)
        .order_by(RunSource.ordinal)
    )
    return [(sid, stated) for sid, stated in rows]


async def run_source_ids(s: AsyncSession, run_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await s.scalars(
            select(RunSource.source_id)
            .where(RunSource.run_id == run_id)
            .order_by(RunSource.ordinal)
        )
    )


async def require_run(s: AsyncSession, run_id: uuid.UUID) -> None:
    """NotFoundError unless the run exists; reads its id alone."""
    if await s.scalar(select(Run.id).where(Run.id == run_id)) is None:
        raise NotFoundError(f"run {run_id} not found")


async def cancel_flag(s: AsyncSession, run_id: uuid.UUID) -> bool:
    flag = await s.scalar(select(Run.cancel_requested).where(Run.id == run_id))
    if flag is None:
        raise NotFoundError(f"run {run_id} not found")
    return bool(flag)


# The run's job that a worker took ('doing') and whose worker is gone: its row deleted
# (worker_id NULL) or its heartbeat older than `stalled_after_s`. That is procrastinate's own
# stalled-job test, the one the requeue uses (R-M17-2). A run has at most one 'doing' job: every
# job carries the lock run:<id>, and procrastinate never starts a job whose lock a 'doing' job
# holds. FOR UPDATE OF j: the requeue cannot move the job while this transaction closes it.
_ABANDONED = (
    "SELECT j.id FROM procrastinate_jobs j "
    "LEFT JOIN procrastinate_workers w ON w.id = j.worker_id "
    "WHERE j.args->>'run_id' = :run_id AND j.status = 'doing' "
    "AND (w.id IS NULL OR w.last_heartbeat < now() - make_interval(secs => :stalled_after_s))"
)
_ABANDONED_JOB = text(_ABANDONED + " FOR UPDATE OF j")
_HAS_ABANDONED_JOB = text(f"SELECT EXISTS ({_ABANDONED})")
_ABORT_JOB = text(
    "SELECT procrastinate_finish_job_v1(:job_id, CAST('aborted' AS procrastinate_job_status), "
    "false)"
)


async def close_abandoned_job(
    s: AsyncSession, run_id: uuid.UUID, *, stalled_after_s: float
) -> bool:
    """Close the run's job as `aborted` if the worker that took it is gone; True if it was.
    Call it with the run's row lock held."""
    job_id = await s.scalar(
        _ABANDONED_JOB, {"run_id": str(run_id), "stalled_after_s": stalled_after_s}
    )
    if job_id is None:
        return False
    await s.execute(_ABORT_JOB, {"job_id": job_id})
    return True


async def has_abandoned_job(s: AsyncSession, run_id: uuid.UUID, *, stalled_after_s: float) -> bool:
    """Whether the run's job was taken by a worker that is gone: what `close_abandoned_job` would
    close now (CRL-49). It locks nothing."""
    return bool(
        await s.scalar(
            _HAS_ABANDONED_JOB, {"run_id": str(run_id), "stalled_after_s": stalled_after_s}
        )
    )


# ---------------------------------------------------------------- what a run produces


async def add_stage(s: AsyncSession, run_id: uuid.UUID, ordinal: int, result: StageResult) -> None:
    s.add(
        StageResultRow(
            run_id=run_id,
            ordinal=ordinal,
            stage=result.stage,
            iteration=result.iteration,
            ok=result.ok,
            output=result.model_dump(mode="json")["output"],  # JSONB: JSON-native values only
            error=result.error,
            started_at=result.started_at,
            finished_at=result.finished_at,
        )
    )
    await s.flush()


async def load_stages(s: AsyncSession, run_id: uuid.UUID) -> list[StageResult]:
    rows = await s.scalars(
        select(StageResultRow)
        .where(StageResultRow.run_id == run_id)
        .order_by(StageResultRow.ordinal)
    )
    return [
        StageResult(
            stage=r.stage,
            iteration=r.iteration,
            ok=r.ok,
            output=r.output,
            error=r.error,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in rows
    ]


async def add_drafts(
    s: AsyncSession, run_id: uuid.UUID, start: int, drafts: Iterable[DraftRecord]
) -> None:
    s.add_all(
        DraftRow(
            run_id=run_id,
            ordinal=start + i,
            role=d.role,
            iteration=d.iteration,
            report=d.report.model_dump(mode="json"),
        )
        for i, d in enumerate(drafts)
    )
    await s.flush()


async def load_drafts(s: AsyncSession, run_id: uuid.UUID) -> list[DraftRecord]:
    rows = await s.scalars(
        select(DraftRow).where(DraftRow.run_id == run_id).order_by(DraftRow.ordinal)
    )
    return [DraftRecord(role=r.role, iteration=r.iteration, report=r.report) for r in rows]


async def add_findings(
    s: AsyncSession, run_id: uuid.UUID, start: int, findings: Iterable[Finding]
) -> None:
    s.add_all(
        AuditFindingRow(
            run_id=run_id,
            ordinal=start + i,
            iteration=f.iteration,
            rule_id=f.rule_id,
            verdict=f.verdict.value,
            severity=f.severity,
            route_to=f.route_to,
            evidence=f.evidence,
            cited_units=list(f.cited_units),
            claim_ids=list(f.claim_ids),
            recommendation=f.recommendation,
        )
        for i, f in enumerate(findings)
    )
    await s.flush()


async def load_findings(s: AsyncSession, run_id: uuid.UUID) -> list[Finding]:
    rows = await s.scalars(
        select(AuditFindingRow)
        .where(AuditFindingRow.run_id == run_id)
        .order_by(AuditFindingRow.ordinal)
    )
    return [
        Finding(
            rule_id=r.rule_id,
            verdict=Verdict(r.verdict),
            evidence=r.evidence,
            cited_units=list(r.cited_units),
            claim_ids=list(r.claim_ids),
            recommendation=r.recommendation,
            severity=r.severity,
            route_to=r.route_to,
            iteration=r.iteration,
        )
        for r in rows
    ]


async def add_llm_calls(
    s: AsyncSession,
    run_id: uuid.UUID,
    start: int,
    records: Iterable[LLMCallRecord],
    *,
    stage: str,
) -> None:
    s.add_all(
        LLMCall(run_id=run_id, ordinal=start + i, stage=stage, **r.model_dump(mode="json"))
        for i, r in enumerate(records)
    )
    await s.flush()


async def load_llm_calls(
    s: AsyncSession, run_id: uuid.UUID, *, with_io: bool = True
) -> list[LLMCallRecord]:
    """The run's model calls in order. `with_io=False` leaves each call's stored request and
    response unread, and None (CRL-103): with `audit.store_llm_io` they are most of the run's
    bytes, and the trace view shows neither."""
    query = select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.ordinal)
    if not with_io:
        query = query.options(defer(LLMCall.request), defer(LLMCall.response))
    rows = await s.scalars(query)
    return [
        LLMCallRecord(
            role=r.role,
            backend=r.backend,
            model=r.model,
            prompt_id=r.prompt_id,
            prompt_version=r.prompt_version,
            attempt=r.attempt,
            ok=r.ok,
            latency_ms=r.latency_ms,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            error=r.error,
            request=r.request if with_io else None,
            response=r.response if with_io else None,
        )
        for r in rows
    ]


async def replace_claims(
    s: AsyncSession, run_id: uuid.UUID, report: Report, source_ids: list[uuid.UUID]
) -> None:
    """Index the delivered report's claims and evidence (spec §8.3 `claim`, `claim_evidence`).
    `source_ids` is the run's sources in order, so "src<n>" resolves to source_ids[n-1]; a ref
    that does not resolve keeps its text and no source id."""
    await s.execute(delete(ClaimRow).where(ClaimRow.run_id == run_id))
    for claim in report.claims:
        row = ClaimRow(
            run_id=run_id,
            claim_id=claim.id,
            text=claim.text,
            kind=claim.kind.value,
            likelihood_term=claim.likelihood_term,
        )
        s.add(row)
        await s.flush()
        for i, ref in enumerate(claim.evidence):
            src, unit = split_ref(ref)
            resolved: uuid.UUID | None = None
            if src.startswith("src") and src[3:].isdigit():
                n = int(src[3:])
                if 1 <= n <= len(source_ids):
                    resolved = source_ids[n - 1]
            s.add(
                ClaimEvidenceRow(
                    claim_pk=row.id, ordinal=i, unit_ref=ref, source_id=resolved, unit_id=unit
                )
            )
    await s.flush()


async def add_export(
    s: AsyncSession, run_id: uuid.UUID, name: str, storage_key: str, data: bytes
) -> ExportRow:
    row = ExportRow(
        run_id=run_id,
        name=name,
        storage_key=storage_key,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )
    s.add(row)
    await s.flush()
    return row


async def list_exports(s: AsyncSession, run_id: uuid.UUID) -> list[ExportRow]:
    return list(
        await s.scalars(
            select(ExportRow).where(ExportRow.run_id == run_id).order_by(ExportRow.name)
        )
    )


async def add_review_event(
    s: AsyncSession,
    run_id: uuid.UUID,
    action: str,
    note: str,
    actor: str | None,
    child_run_id: uuid.UUID | None,
) -> ReviewEvent:
    event = ReviewEvent(
        run_id=run_id, action=action, note=note, actor=actor, child_run_id=child_run_id
    )
    s.add(event)
    await s.flush()
    return event


async def load_review_events(s: AsyncSession, run_id: uuid.UUID) -> list[ReviewEvent]:
    """Every review action on the run, oldest first."""
    return list(
        await s.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.run_id == run_id)
            .order_by(ReviewEvent.at, ReviewEvent.id)
        )
    )


async def rerun_states(
    s: AsyncSession, run_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[RunState, str | None]]:
    """The state and error of each run in `run_ids` (the reruns returns created), by id: what
    decides whether a return is spent (R-M15-1). A run that no longer exists is left out."""
    ids = list(run_ids)
    if not ids:
        return {}
    rows = await s.execute(select(Run.id, Run.state, Run.error).where(Run.id.in_(ids)))
    return {row.id: (RunState(row.state), row.error) for row in rows}


async def parent_ids(s: AsyncSession, run_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """The distinct parents of the runs in `run_ids`, sorted: the order every transaction that
    locks several parents takes their row locks in (R-M15-2)."""
    found = await s.scalars(
        select(Run.parent_run_id)
        .where(Run.id.in_(list(run_ids)), Run.parent_run_id.is_not(None))
        .distinct()
    )
    return sorted(pid for pid in found if pid is not None)


async def lock_run(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Take the run row's lock for the rest of the transaction without loading the row."""
    await s.execute(select(Run.id).where(Run.id == run_id).with_for_update())


async def set_review_state(
    s: AsyncSession, run_id: uuid.UUID, state: dict[str, Any] | None
) -> None:
    """The run's review decision as `ReviewState` JSON (CRL-17, R-M10-1); None is SQL NULL."""
    await s.execute(
        update(Run).where(Run.id == run_id).values(review_state=state if state else null())
    )


async def clear_trace(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Remove everything an earlier execution of the run produced (a worker that died mid-run);
    the run row itself stays."""
    for table in (StageResultRow, DraftRow, ClaimRow, AuditFindingRow, LLMCall, ExportRow):
        await s.execute(delete(table).where(table.run_id == run_id))
