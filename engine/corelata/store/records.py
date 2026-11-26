"""A run's rows as the trace record and back (spec §8.4 invariant 5: every export is derived
from stored rows). `load_record` rebuilds the `RunRecord` that `corelata run` would have
written; `save_outcome` stores what a finished (or cancelled, or failed) run produced."""

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.llm.agent import CallLog
from corelata.schema import (
    Digest,
    Finding,
    GateVerdict,
    PriorReport,
    Report,
    ReportStatus,
    RunKind,
    RunRecord,
    RunState,
    Source,
    SourceKind,
)
from corelata.schema.source import lowest_tier
from corelata.stages.structure import REPORT_ID
from corelata.store import runs
from corelata.store.models import Run, RunSource, SourceRow, SourceUnitRow
from corelata.trace import UnitCount


async def load_sources(
    s: AsyncSession, run_id: uuid.UUID, *, refs: Iterable[str] | None = None
) -> list[Source]:
    """The run's sources, named src1, src2, … by their position (RunSource.ordinal). `refs`
    ("src2/u14"): each source with only the units these name, none for a source they do not
    name; a claim read fetches its evidence and not the whole source (CRL-124)."""
    wanted: dict[str, set[str]] = {}
    for ref in refs or ():
        source_id, _, unit_id = ref.partition("/")
        wanted.setdefault(source_id, set()).add(unit_id)
    return [
        await runs.load_source(
            s,
            await runs.get_source(s, sid),
            as_id=f"src{i}",
            unit_ids=None if refs is None else wanted.get(f"src{i}", set()),
            stated=stated,  # as the run was queued with it (CRL-138)
        )
        for i, (sid, stated) in enumerate(await runs.run_sources(s, run_id), start=1)
    ]


async def load_checked_report(
    s: AsyncSession, run: Run, *, with_units: bool = True
) -> Source | None:
    """A check run's report as the pipeline reads it (source id `report`, CRL-94); None for a
    report run."""
    if run.report_source_id is None:
        return None
    row = await runs.get_source(s, run.report_source_id)
    return await runs.load_source(s, row, as_id=REPORT_ID, unit_ids=None if with_units else ())


async def unit_counts(s: AsyncSession, run_id: uuid.UUID) -> dict[str, UnitCount]:
    """Each of the run's sources' unit count, Coglossa reliability tier and hidden and suspect
    units (CRL-137), counted in the database without reading a unit's text (CRL-124): what the
    trace summary shows of them."""
    tiers = func.array_agg(func.distinct(SourceUnitRow.meta["reliability"].astext)).filter(
        SourceRow.kind == SourceKind.COGLOSSA_EXPORT.value
    )
    hidden = func.count(SourceUnitRow.ordinal).filter(SourceUnitRow.meta["hidden"].astext == "true")
    suspect = func.count(SourceUnitRow.ordinal).filter(
        SourceUnitRow.meta["suspect"].astext == "true"
    )
    rows = await s.execute(
        select(func.count(SourceUnitRow.ordinal), tiers, hidden, suspect)
        .select_from(RunSource)
        .join(SourceRow, SourceRow.id == RunSource.source_id)
        .outerjoin(SourceUnitRow, SourceUnitRow.source_id == RunSource.source_id)
        .where(RunSource.run_id == run_id)
        .group_by(RunSource.ordinal)
        .order_by(RunSource.ordinal)
    )
    return {
        f"src{i}": UnitCount(
            units=count,
            reliability_tier=lowest_tier(found or ()),
            hidden=n_hidden,
            suspect=n_suspect,
        )
        for i, (count, found, n_hidden, n_suspect) in enumerate(rows, start=1)
    }


async def load_report(s: AsyncSession, run_id: uuid.UUID) -> tuple[RunState, Report | None]:
    """The run's state and delivered report, and nothing else of the run row (CRL-103)."""
    row = (await s.execute(select(Run.state, Run.report).where(Run.id == run_id))).one_or_none()
    if row is None:
        raise runs.NotFoundError(f"run {run_id} not found")
    return RunState(row.state), Report.model_validate(row.report) if row.report else None


async def load_record(
    s: AsyncSession, run_id: uuid.UUID, *, with_io: bool = True, with_units: bool = True
) -> RunRecord:
    """`with_io=False`: the model calls without their stored request and response
    (`runs.load_llm_calls`), for readers that do not show them (CRL-103). `with_units=False`: the
    sources without their units, for the trace, which counts them (`unit_counts`, CRL-124)."""
    run = await runs.get_run(s, run_id)
    calls = await runs.load_llm_calls(s, run_id, with_io=with_io)
    return RunRecord(
        corelata_version=run.corelata_version,
        run_id=str(run.id),
        kind=RunKind(run.kind),
        created_at=run.created_at,
        state=RunState(run.state),
        status=ReportStatus(run.status) if run.status else None,
        value_statement=run.value_statement,
        profile=run.profile,
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        extra_guidance=run.extra_guidance,
        pack_name=run.pack_name,
        pack_hash=run.pack_hash,
        pack_snapshot=run.pack_snapshot,
        config_hash=run.config_hash,
        prompt_versions=run.prompt_versions,
        sources=await load_sources(s, run_id, refs=None if with_units else ()),
        checked_report=await load_checked_report(s, run, with_units=with_units),
        digests=[Digest.model_validate(d) for d in run.digests],
        prior_reports=[PriorReport.model_validate(p) for p in run.prior_reports or []],
        gate=GateVerdict.model_validate(run.gate) if run.gate else None,
        stages=await runs.load_stages(s, run_id),
        drafts=await runs.load_drafts(s, run_id),
        findings=await runs.load_findings(s, run_id),
        report=Report.model_validate(run.report) if run.report else None,
        iterations=run.iteration,
        max_iterations=run.max_iterations,
        usage=CallLog(records=calls).usage(),
        llm_calls=calls,
        error=run.error,
        reviewer_findings=[Finding.model_validate(f) for f in run.reviewer_findings or []],
        review_marks=await runs.load_review_marks(s, run_id),
    )


async def save_outcome(
    s: AsyncSession,
    run: Run,
    record: RunRecord,
    *,
    source_ids: list[uuid.UUID],
    stages_from: int = 0,
    calls_from: int = 0,
) -> None:
    """Store a finished run. `stages_from` and `calls_from` are how many stage results and
    model calls the observer already persisted while the run executed; the rest is appended.
    Drafts, findings and claims are written here in full. The caller holds the run row lock."""
    run.state = record.state.value
    run.status = record.status.value if record.status else None
    run.error = record.error
    run.gate = record.gate.model_dump(mode="json") if record.gate else None
    run.digests = [d.model_dump(mode="json") for d in record.digests]
    run.prior_reports = [p.model_dump(mode="json") for p in record.prior_reports]
    run.report = record.report.model_dump(mode="json") if record.report else None
    run.iteration = record.iterations
    run.token_usage = record.usage.model_dump()
    # The trace states what the run executed with, not what was current when it was queued.
    run.prompt_versions = record.prompt_versions
    run.corelata_version = record.corelata_version
    run.finished_at = await runs.db_now(s)
    for i, stage in enumerate(record.stages[stages_from:], start=stages_from):
        await runs.add_stage(s, run.id, i, stage)
    await runs.add_drafts(s, run.id, 0, record.drafts)
    await runs.add_findings(s, run.id, 0, record.findings)
    await runs.add_llm_calls(
        s, run.id, calls_from, record.llm_calls[calls_from:], stage=record.state.value
    )
    if record.report is not None:
        await runs.replace_claims(s, run.id, record.report, source_ids)
    await s.flush()
