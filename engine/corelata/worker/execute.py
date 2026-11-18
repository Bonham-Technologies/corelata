"""Worker job bodies (spec §7.2, §7.5). A run is one job: the pipeline executes in-process with
an observer that writes every state change, stage result and model call to Postgres as it
happens, so progress is visible and a cancel is honoured at the next stage. A job delivered
again for a finished run does nothing; one delivered for a run whose earlier execution died
starts the run over (model calls are not replayable, and a run is minutes, spec §16). No
transaction is held across a model call."""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.config import CorelataConfig, config_hash
from corelata.exports import render_outputs
from corelata.llm.agent import AGENT_FAILURES, CallLog
from corelata.llm.types import Backend
from corelata.pipeline import RunOptions, discover, load_run_pack, run_report
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    TERMINAL_STATES,
    DiscoveryState,
    PriorReport,
    RunRecord,
    RunState,
    Source,
    StageResult,
)
from corelata.service import (
    TASK_DISCOVER,
    TASK_RUN,
    JobQueue,
    discovery_deadline_error,
    discovery_start_error,
    reruns_ended,
)
from corelata.stages.context import StageError
from corelata.standards.loader import PackError
from corelata.standards.schema import ResolvedPack
from corelata.storage import Storage, StorageError, storage_call
from corelata.store import discoveries, records, runs
from corelata.store.db import Database
from corelata.store.models import Run

log = logging.getLogger("corelata.worker")

DB_ERRORS: tuple[type[Exception], ...] = (OperationalError, InterfaceError)


@dataclass
class WorkerServices:
    cfg: CorelataConfig
    db: Database
    storage: Storage
    queue: JobQueue
    backends: dict[str, Backend]
    prompts: PromptLibrary

    def call_log(self) -> CallLog:
        return CallLog(store_io=self.cfg.audit.store_llm_io)

    async def aclose(self) -> None:
        for backend in self.backends.values():
            await backend.aclose()
        await self.db.dispose()


def _internal(e: BaseException) -> str:
    return f"internal error: {type(e).__name__}: {e}"


class RunEnded(Exception):
    """The run ended while this execution still held it: a cancel found its worker gone and
    ended it (R-M17-2). The execution stops and writes nothing more."""


class AttemptSuperseded(RunEnded):
    """The run was started over by a later attempt while this execution still ran: its worker's
    heartbeat stalled, the requeue gave the job to another worker, and that worker claimed the
    run (CRL-56). The run is not over, but it is no longer this execution's: it stops and writes
    nothing more, so the run never has two executions past this one's next write."""


class DbObserver:
    """The pipeline's observer for a queued run: short transactions between model calls, each
    announcing the change on the run channel when it commits (CRL-22). Every write first checks,
    under the run's row lock, that the run has not ended (`RunEnded`), so a worker that was taken
    for dead can never write over the ending it was given, and that the run is still on this
    execution's attempt (`AttemptSuperseded`), so a worker whose run was started over elsewhere
    never writes into the new attempt's trace."""

    def __init__(self, db: Database, run_id: uuid.UUID, calls: CallLog, attempt: int) -> None:
        self.db = db
        self.run_id = run_id
        self.calls = calls
        self.attempt = attempt
        self.stages_saved = 0
        self.calls_saved = 0

    async def locked(self, s: AsyncSession) -> Run:
        """The run under its row lock, while it has not ended and is still on this attempt."""
        run = await runs.get_run(s, self.run_id, lock=True)
        if run.attempts != self.attempt:
            raise AttemptSuperseded(
                f"run {self.run_id} was started over as attempt {run.attempts}; "
                f"this execution was attempt {self.attempt}"
            )
        if RunState(run.state) in TERMINAL_STATES:
            raise RunEnded(f"run {self.run_id} is already {run.state}")
        return run

    async def state_changed(self, record: RunRecord) -> None:
        async with self.db.session() as s, s.begin():
            run = await self.locked(s)
            run.state = record.state.value
            await runs.notify_run(s, self.run_id)

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None:
        new = self.calls.records[self.calls_saved :]
        async with self.db.session() as s, s.begin():
            run = await self.locked(s)
            run.state = record.state.value
            run.iteration = result.iteration
            run.token_usage = self.calls.usage().model_dump()
            await runs.add_stage(s, self.run_id, self.stages_saved, result)
            await runs.add_llm_calls(s, self.run_id, self.calls_saved, new, stage=result.stage)
            await runs.notify_run(s, self.run_id)
        self.stages_saved += 1
        self.calls_saved += len(new)

    async def cancel_requested(self) -> bool:
        async with self.db.session() as s:
            return await runs.cancel_flag(s, self.run_id)


@dataclass
class _Inputs:
    sources: list[Source]
    source_ids: list[uuid.UUID]
    pack_snapshot: dict
    value_statement: str
    profile: str | None
    max_iterations: int
    extra_guidance: str
    parent_run_id: str | None
    docx_reference_key: str | None
    created_at: datetime
    restarted: bool
    attempt: int
    prior_reports: list[PriorReport] | None


async def _begin(svc: WorkerServices, run_id: uuid.UUID) -> _Inputs | None:
    """Claim the run under its row lock. None: nothing to do (finished, or cancelled before any
    work). A run left mid-flight by a dead worker is wiped and started over."""
    async with svc.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        if RunState(run.state) in TERMINAL_STATES:
            log.info("run %s is already %s", run_id, run.state, extra={"run_id": str(run_id)})
            return None
        if run.cancel_requested:
            run.state, run.finished_at = RunState.CANCELLED.value, await runs.db_now(s)
            await runs.notify_run(s, run_id)
            await reruns_ended(s, [run_id])
            return None
        restarted = bool(run.attempts)
        if restarted:
            log.warning(
                "run %s restarted: its earlier execution did not finish",
                run_id,
                extra={"run_id": str(run_id)},
            )
            await runs.clear_trace(s, run_id)
        run.attempts += 1
        run.state = RunState.INGESTING.value  # the claim: a cancel from here only sets the flag
        run.started_at, run.finished_at = await runs.db_now(s), None
        run.error = run.export_error = run.status = run.report = run.gate = None
        run.digests, run.token_usage, run.iteration = [], None, 0
        run.prior_reports = None
        live = config_hash(svc.cfg)
        if live != run.config_hash:
            log.warning(
                "run %s: configuration changed since it was queued (%s -> %s); running with the "
                "current configuration",
                run_id,
                run.config_hash,
                live,
                extra={"run_id": str(run_id)},
            )
            run.config_hash = live
            run.config_snapshot = svc.cfg.model_dump(mode="json")
        await runs.notify_run(s, run_id)
        return _Inputs(
            sources=await records.load_sources(s, run_id),
            source_ids=await runs.run_source_ids(s, run_id),
            pack_snapshot=run.pack_snapshot,
            value_statement=run.value_statement,
            profile=run.profile,
            max_iterations=run.max_iterations,
            extra_guidance=run.extra_guidance,
            parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
            docx_reference_key=run.docx_reference_key,
            created_at=run.created_at,
            restarted=restarted,
            attempt=run.attempts,
            prior_reports=await _accepted_reports(svc.cfg, s, run),
        )


async def _accepted_reports(
    cfg: CorelataConfig, s: AsyncSession, run: Run
) -> list[PriorReport] | None:
    """The earlier accepted reports of the run's project the pipeline is given (CRL-97), read
    in the claim's transaction; None when `pipeline.prior_judgments.max_reports` is 0."""
    limit = cfg.pipeline.prior_judgments.max_reports
    if limit == 0:
        return None
    return await runs.accepted_reports(s, run.project_id, limit=limit, exclude=run.id)


def _stray_files(storage: Storage, prefix: str, keep: set[str]) -> list[str]:
    return [k for k in storage.list_keys(prefix) if k not in keep]


@contextlib.asynccontextmanager
async def _reference(storage: Storage, key: str | None) -> AsyncIterator[Path | None]:
    """The run's stored reference document as a local file. Fetching it (a download from S3 on
    the hosted demo) runs off the event loop; the local copy is removed on the way out, a file
    operation that needs no thread (R-M19-5)."""
    if key is None:
        yield None
        return
    # The stack closes the copy when the download is cancelled after it began (storage_call has
    # waited for it by then) and when the body raises, with that exception.
    with contextlib.ExitStack() as stack:
        path = await storage_call(stack.enter_context, storage.local_file(key))
        yield path


def _render(record: RunRecord, pack: ResolvedPack) -> tuple[dict[str, bytes], str | None]:
    """Every export as bytes. The DOCX is the only render that reads a file (the reference
    document); its failure is reported, not fatal: the trace and the other renders stand."""
    files = {
        name: content if isinstance(content, bytes) else content.encode("utf-8")
        for name, content in render_outputs(
            record, pack, with_claim_ids=False, formats=("json", "md", "html")
        ).items()
    }
    if record.report is None:
        return files, None
    try:
        docx = render_outputs(
            record,
            pack,
            with_claim_ids=False,
            docx_reference=pack.docx_reference_path,
            formats=("docx",),
        )["report.docx"]
    except Exception as e:  # noqa: BLE001 - whatever the reference document provokes
        return files, f"DOCX export failed: {e or type(e).__name__}"
    assert isinstance(docx, bytes)
    files["report.docx"] = docx
    return files, None


def _log_ended(run_id: uuid.UUID, e: RunEnded, observer: DbObserver) -> None:
    """The fence stopped this execution. The model calls it has not written are dropped, never
    recorded on the run (docs/trace-format.md), so the log line says what they spent. A
    superseded attempt's written calls went too: the new attempt cleared the trace."""
    superseded = isinstance(e, AttemptSuperseded)
    dropped = observer.calls.records[0 if superseded else observer.calls_saved :]
    tokens_in = sum(r.tokens_in or 0 for r in dropped)
    tokens_out = sum(r.tokens_out or 0 for r in dropped)
    # a superseded attempt is the expected end of a worker taken for dead that was not
    log.log(
        logging.INFO if superseded else logging.WARNING,
        "run %s %s (%s); stopping without writing, %d model calls (%d tokens in, %d out) of "
        "this attempt not recorded",
        run_id,
        "was started over elsewhere" if superseded else "ended while this worker ran it",
        e,
        len(dropped),
        tokens_in,
        tokens_out,
        extra={"run_id": str(run_id)},
    )


async def _end_failed(
    svc: WorkerServices, observer: DbObserver, message: str, *, with_calls: bool
) -> None:
    async with svc.db.session() as s, s.begin():
        run = await observer.locked(s)
        if with_calls:
            new = observer.calls.records[observer.calls_saved :]
            await runs.add_llm_calls(s, observer.run_id, observer.calls_saved, new, stage=run.state)
            run.token_usage = observer.calls.usage().model_dump()
        run.state, run.error = RunState.FAILED.value, message
        run.finished_at = await runs.db_now(s)
        await runs.notify_run(s, observer.run_id)
        await reruns_ended(s, [observer.run_id])


async def _fail_run(
    svc: WorkerServices, run_id: uuid.UUID, message: str, observer: DbObserver
) -> None:
    """End the run failed with its leftover model calls. A run that already ended (a cancel
    found this worker gone, R-M17-2) or was started over elsewhere (CRL-56) is left as it is:
    nothing is written or announced."""
    try:
        try:
            await _end_failed(svc, observer, message, with_calls=True)
        except (RunEnded, *DB_ERRORS):
            raise
        except Exception:
            # The leftover calls could not be written; the run must still end, so record only that.
            log.exception("run %s: leftover calls not saved", run_id, extra={"run_id": str(run_id)})
            await _end_failed(svc, observer, message, with_calls=False)
    except RunEnded as e:
        _log_ended(run_id, e, observer)


async def execute_run(svc: WorkerServices, run_id: uuid.UUID) -> None:
    inputs = await _begin(svc, run_id)
    if inputs is None:
        return
    if inputs.restarted:
        # The dead attempt's files: its rows are gone (clear_trace), its files must follow, but
        # never the reference document, which the new attempt renders with.
        keep = {inputs.docx_reference_key} if inputs.docx_reference_key else set()
        for key in await storage_call(_stray_files, svc.storage, f"runs/{run_id}/", keep):
            with contextlib.suppress(StorageError):
                await storage_call(svc.storage.delete_prefix, key)
    observer = DbObserver(svc.db, run_id, svc.call_log(), inputs.attempt)
    phase = "failed"
    try:
        pack = ResolvedPack.model_validate(inputs.pack_snapshot)
        async with _reference(svc.storage, inputs.docx_reference_key) as reference:
            pack.docx_reference_path = reference
            record = await run_report(
                svc.cfg,
                inputs.sources,
                RunOptions(
                    value_statement=inputs.value_statement,
                    profile=inputs.profile,
                    max_iterations=inputs.max_iterations,
                    extra_guidance=inputs.extra_guidance,
                    run_id=str(run_id),
                    parent_run_id=inputs.parent_run_id,
                    created_at=inputs.created_at,
                    prior_reports=inputs.prior_reports,
                ),
                backends=svc.backends,
                prompts=svc.prompts,
                log=observer.calls,
                pack=pack,
                observer=observer,
            )
            phase = "failed while saving"
            async with svc.db.session() as s, s.begin():
                run = await observer.locked(s)
                await records.save_outcome(
                    s,
                    run,
                    record,
                    source_ids=inputs.source_ids,
                    stages_from=observer.stages_saved,
                    calls_from=observer.calls_saved,
                )
                # Render from the record as stored, not the in-memory one: JSONB reorders object
                # keys, and the exports must be reproducible from the database (spec §8.4 inv. 5).
                await s.flush()
                s.expire_all()
                files, export_error = _render(await records.load_record(s, run_id), pack)
                run.export_error = export_error
                for name, data in files.items():
                    key = f"runs/{run_id}/{name}"
                    await storage_call(svc.storage.put, key, data)
                    await runs.add_export(s, run_id, name, key, data)
                await runs.notify_run(s, run_id)
                await reruns_ended(s, [run_id])  # every outcome is terminal (R-M15-2)
    except RunEnded as e:
        _log_ended(run_id, e, observer)
        return
    except DB_ERRORS:
        raise
    except Exception as e:
        log.exception("run %s %s", run_id, phase, extra={"run_id": str(run_id)})
        await _fail_run(svc, run_id, _internal(e), observer)
        return
    log.info(
        "run %s finished: %s",
        run_id,
        record.state.value,
        extra={"run_id": str(run_id), "state": record.state.value},
    )


_ENDED = (DiscoveryState.COMPLETED, DiscoveryState.FAILED)


async def execute_discovery(svc: WorkerServices, discovery_id: uuid.UUID) -> None:
    """One discovery job (spec §7.1). Finished discoveries are left alone; one a dead worker
    left `running` is done again. A discovery has two limits (R-M17-1, R-M17-26): claimed
    `worker.discovery_start_deadline_s` or more after its creation, it is failed without a model
    call; claimed in time, its work has `worker.discovery_deadline_s` from the first claim and is
    stopped when that is up (a redelivered job gets what is left, and none past it). An answer
    whose transaction finds the work limit passed, or the discovery already failed by the API's
    read or the sweep, is never kept; the agent's own error is (R-M17-30). Every decision is
    taken under the discovery's row lock on the database's clock."""
    limits = svc.cfg.worker
    deadline_s = limits.discovery_deadline_s
    too_late = discovery_deadline_error(deadline_s)
    loop = asyncio.get_running_loop()
    # the first claim records `now()`, its transaction's start, as `started_at`, and the budget's
    # ages are measured by that `now()`; the loop's clock read before that transaction anchors
    # the budget no later than the work limit, however long the claim takes
    t0 = loop.time()
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        state = DiscoveryState(row.state)
        if state in _ENDED:
            return
        ages = await discoveries.clock(s, discovery_id)
        if state is DiscoveryState.CREATED:
            if ages.since_created_s >= limits.discovery_start_deadline_s:
                row.state, row.finished_at = DiscoveryState.FAILED.value, ages.now
                row.error = discovery_start_error(limits.discovery_start_deadline_s)
                log.warning(
                    "discovery %s was past its start limit when claimed; failed", discovery_id
                )
                return
        elif ages.since_started_s >= deadline_s:
            row.state, row.error, row.finished_at = DiscoveryState.FAILED.value, too_late, ages.now
            log.warning(
                "discovery %s was past its work limit when claimed again; failed", discovery_id
            )
            return
        else:
            log.warning(
                "discovery %s restarted: its earlier execution did not finish", discovery_id
            )
        if row.started_at is None:  # the first claim starts the work limit; a redelivery keeps it
            row.started_at = ages.now
        # what is left of the work limit, on the database's clock: all of it at the first claim
        left = deadline_s - ages.since_started_s
        row.state, row.error = DiscoveryState.RUNNING.value, None
        ids = await discoveries.source_ids(s, discovery_id)
        sources = [
            await runs.load_source(s, await runs.get_source(s, sid), as_id=f"src{i}")
            for i, sid in enumerate(ids, start=1)
        ]
        audience_hint = row.audience_hint
    calls = svc.call_log()
    error: str | None = None
    result = None
    budget = asyncio.timeout_at(t0 + left)  # the work stops at its limit
    try:
        async with budget:
            result = await discover(
                svc.cfg,
                sources,
                backends=svc.backends,
                prompts=svc.prompts,
                log=calls,
                audience_hint=audience_hint,
                pack=load_run_pack(svc.cfg, None),
            )
    except DB_ERRORS:
        raise
    except (*AGENT_FAILURES, StageError, PackError, ValueError) as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001 - recorded, never raised out of a job
        if not budget.expired():  # the deadline's TimeoutError is recorded below
            log.exception("discovery %s failed", discovery_id)
        error = _internal(e)
    if budget.expired():
        log.warning(
            "discovery %s stopped at its deadline after %.0f s", discovery_id, loop.time() - t0
        )
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        row.llm_calls = [r.model_dump(mode="json") for r in calls.records]
        row.token_usage = calls.usage().model_dump()
        if DiscoveryState(row.state) in _ENDED:
            # failed at its deadline by the API's read or the sweep while this worked: it stays so
            log.warning("discovery %s ended while it ran; its result is not kept", discovery_id)
            return
        ages = await discoveries.clock(s, discovery_id)
        row.finished_at = ages.now  # the database's clock, like the expiry's (CRL-53)
        if budget.expired():
            row.state, row.error = DiscoveryState.FAILED.value, too_late
        elif result is None:  # the agent's error says more than the deadline would
            row.state, row.error = DiscoveryState.FAILED.value, error
        elif ages.since_started_s >= deadline_s:
            row.state, row.error = DiscoveryState.FAILED.value, too_late  # an answer too late
        else:
            await discoveries.set_candidates(s, discovery_id, result)
            row.state = DiscoveryState.COMPLETED.value


async def run_job(svc: WorkerServices, task: str, kwargs: dict[str, str]) -> None:
    """Dispatch one queue job. A job for a deleted run is skipped (not an error)."""
    try:
        if task == TASK_RUN:
            await execute_run(svc, uuid.UUID(kwargs["run_id"]))
        elif task == TASK_DISCOVER:
            await execute_discovery(svc, uuid.UUID(kwargs["discovery_id"]))
        else:
            raise ValueError(f"unknown job '{task}'")
    except runs.NotFoundError as e:
        log.info("job skipped: %s", e)
