"""A run's rows as the trace record and back (spec §8.4 invariant 5: every export is derived
from stored rows). `load_record` rebuilds the `RunRecord` that `corelata run` would have
written; `save_outcome` stores what a finished (or cancelled, or failed) run produced."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.llm.agent import CallLog
from corelata.schema import (
    Digest,
    GateVerdict,
    PriorReport,
    Report,
    ReportStatus,
    RunRecord,
    RunState,
    Source,
)
from corelata.store import runs
from corelata.store.models import Run


async def load_sources(s: AsyncSession, run_id: uuid.UUID) -> list[Source]:
    """The run's sources, named src1, src2, … by their position (RunSource.ordinal)."""
    ids = await runs.run_source_ids(s, run_id)
    return [
        await runs.load_source(s, await runs.get_source(s, sid), as_id=f"src{i}")
        for i, sid in enumerate(ids, start=1)
    ]


async def load_report(s: AsyncSession, run_id: uuid.UUID) -> tuple[RunState, Report | None]:
    """The run's state and delivered report, and nothing else of the run row (CRL-103)."""
    row = (await s.execute(select(Run.state, Run.report).where(Run.id == run_id))).one_or_none()
    if row is None:
        raise runs.NotFoundError(f"run {run_id} not found")
    return RunState(row.state), Report.model_validate(row.report) if row.report else None


async def load_record(s: AsyncSession, run_id: uuid.UUID, *, with_io: bool = True) -> RunRecord:
    """`with_io=False`: the model calls without their stored request and response
    (`runs.load_llm_calls`), for readers that do not show them (CRL-103)."""
    run = await runs.get_run(s, run_id)
    calls = await runs.load_llm_calls(s, run_id, with_io=with_io)
    return RunRecord(
        corelata_version=run.corelata_version,
        run_id=str(run.id),
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
        sources=await load_sources(s, run_id),
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
