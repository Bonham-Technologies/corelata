"""Control plane (spec §10.1 semantics, §10.2 commands): projects, sources, queued runs,
cancel and review. The CLI uses it now and the REST API will in M4a. It never calls a model:
work reaches the worker through a JobQueue. Task 7 adds discoveries."""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Protocol

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from corelata import __version__
from corelata.config import CorelataConfig, WorkerConfig, config_hash
from corelata.ingest.base import IngestError
from corelata.ingest.coglossa import load_coglossa_export
from corelata.ingest.ocr import OcrSettings
from corelata.ingest.registry import check_extension
from corelata.ingest.units import make_source
from corelata.pipeline import load_run_pack
from corelata.prompts.check import run_prompt_ids
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    TERMINAL_STATES,
    DiscoveryState,
    DiscoveryView,
    Finding,
    ProjectSummary,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    RunProgress,
    RunRecord,
    RunState,
    RunSummary,
    Source,
    Usage,
)
from corelata.standards.loader import pack_hash
from corelata.storage import Storage, StorageError, display_name, safe_filename, storage_call
from corelata.store import discoveries, records, runs
from corelata.store.db import Database, error_reason
from corelata.store.models import Project, ReviewEvent, Run, SourceRow
from corelata.trace import ClaimProvenance, report_claim_provenance

log = logging.getLogger("corelata.service")

TASK_RUN = "corelata.run"
TASK_DISCOVER = "corelata.discover"
_MAX_FILENAME = 255
# The configuration's defaults, for callers without one (tests); the API and the CLI pass theirs.
DISCOVERY_DEADLINE_S = WorkerConfig().discovery_deadline_s
DISCOVERY_START_DEADLINE_S = WorkerConfig().discovery_start_deadline_s
STALLED_AFTER_S = WorkerConfig().stalled_after_s


# Runs, discoveries and the periodic tasks share one queue and `worker.concurrency`; a discovery
# takes the next free slot ahead of waiting runs (R-M17-29). Everything else keeps procrastinate's
# default priority, 0 (a higher one is fetched first).
DISCOVERY_PRIORITY = 1


class JobQueue(Protocol):
    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None: ...


class ConflictError(Exception):
    """The request conflicts with the current data; the message says why (HTTP 409)."""


class InvalidRunStateError(ConflictError):
    """The run is not in a state that allows the action; the message says why."""


class QueueUnavailableError(Exception):
    """The job queue (the database) could not be reached; the message says why (HTTP 503)."""


class InvalidRequestError(ValueError):
    """The request itself is invalid; the message says why (HTTP 422)."""


# CRL-83, CRL-111: the statement and the guidance go into every writer and auditor prompt and the
# trace, so a pasted document is refused here, for the API and the CLI alike, instead of
# overflowing a model's context after the spend. A return note becomes the revision's guidance.
# The API's request models and the web app's textareas use the same per-field limits.
VALUE_STATEMENT_MAX_LENGTH = 4000
GUIDANCE_MAX_LENGTH = 8000
# Each return appends its note to the parent's guidance, so a chain of returns grows it. The cap is
# three per-field limits (about 6,000 tokens): a run started with full guidance can always be
# returned with a full-length note, and many short notes fit after that.
RUN_GUIDANCE_MAX_LENGTH = 3 * GUIDANCE_MAX_LENGTH
GUIDANCE_CAP_MESSAGE = (
    f"this report's returns would carry more than {RUN_GUIDANCE_MAX_LENGTH} characters of writer "
    "guidance; start a new report with the guidance that still applies"
)


def check_run_text(value_statement: str, extra_guidance: str) -> None:
    """The CRL-83 limits on a run's free text; `corelata run` checks them before any model call."""
    if len(value_statement) > VALUE_STATEMENT_MAX_LENGTH:
        raise InvalidRequestError(
            f"a value statement is at most {VALUE_STATEMENT_MAX_LENGTH} characters"
        )
    if len(extra_guidance) > GUIDANCE_MAX_LENGTH:
        raise InvalidRequestError(
            f"the writer guidance is at most {GUIDANCE_MAX_LENGTH} characters"
        )


def run_lock(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


def discovery_lock(discovery_id: uuid.UUID) -> str:
    return f"discovery:{discovery_id}"


async def _mark_run_failed(db: Database, run_id: uuid.UUID, message: str) -> None:
    """Fail a run nothing has started: once it left `created` the worker owns its ending."""
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        if RunState(run.state) is not RunState.CREATED:
            return
        run.state = RunState.FAILED.value
        run.error = message
        run.finished_at = await runs.db_now(s)
        await runs.notify_run(s, run_id)
        await reruns_ended(s, [run_id])


async def _mark_discovery_failed(db: Database, discovery_id: uuid.UUID, message: str) -> None:
    async with db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        if row.state != DiscoveryState.CREATED.value:
            return
        row.state = DiscoveryState.FAILED.value
        row.error = message
        row.finished_at = await runs.db_now(s)


def _queue_reason(e: Exception) -> str:
    """The driver's reason. QueueUnavailableError wraps procrastinate's message-less
    ConnectorException, whose __cause__ is the driver error, and adds its own prefix."""
    if isinstance(e, QueueUnavailableError):
        wrapped = e.__cause__
        e = (wrapped.__cause__ if wrapped is not None else None) or wrapped or e  # type: ignore[assignment]
    return error_reason(e)


async def _defer_run(db: Database, queue: JobQueue, run_id: uuid.UUID) -> None:
    """Queue the run's job. The row committed before this call (M3 follow-up); if the queue
    refuses, the row says so instead of sitting `created` with no job."""
    try:
        await queue.defer(TASK_RUN, lock=run_lock(run_id), run_id=str(run_id))
    except Exception as e:
        try:
            await _mark_run_failed(db, run_id, f"could not queue the run: {_queue_reason(e)}")
        except Exception as marking:  # the queue and the database may be one outage
            log.warning(
                "could not mark %s %s failed after a queue failure: %s",
                "run",
                run_id,
                error_reason(marking),
            )
        raise


async def _defer_discovery(db: Database, queue: JobQueue, discovery_id: uuid.UUID) -> None:
    try:
        await queue.defer(
            TASK_DISCOVER,
            lock=discovery_lock(discovery_id),
            priority=DISCOVERY_PRIORITY,
            discovery_id=str(discovery_id),
        )
    except Exception as e:
        try:
            await _mark_discovery_failed(
                db, discovery_id, f"could not queue the discovery: {_queue_reason(e)}"
            )
        except Exception as marking:
            log.warning(
                "could not mark %s %s failed after a queue failure: %s",
                "discovery",
                discovery_id,
                error_reason(marking),
            )
        raise


@dataclass(frozen=True)
class RunRequest:
    project_id: uuid.UUID
    source_ids: list[uuid.UUID]
    value_statement: str
    profile: str | None = None
    max_iterations: int | None = None
    extra_guidance: str = ""
    parent_run_id: uuid.UUID | None = None


# ---------------------------------------------------------------- projects and sources


async def create_project(db: Database, name: str) -> uuid.UUID:
    async with db.session() as s, s.begin():
        return (await runs.get_or_create_project(s, name)).id


async def new_project(db: Database, name: str) -> Project:
    """`POST /api/projects`: a new project; an existing name is a conflict. (The CLI's
    `create_project` reuses an existing name instead: `run --project NAME` means "that project,
    created if needed".)"""
    name = name.strip()
    if not name:
        raise InvalidRequestError("a project needs a name")
    if len(name) > 200:
        raise InvalidRequestError("a project name is at most 200 characters")
    try:
        async with db.session() as s, s.begin():
            project = Project(name=name)
            s.add(project)
            await s.flush()
    except IntegrityError as e:
        raise ConflictError(f"a project named '{name}' already exists") from e
    return project


async def get_project(db: Database, project_id: uuid.UUID) -> Project:
    async with db.session() as s:
        return await runs.get_project(s, project_id)


async def list_projects(db: Database) -> list[Project]:
    async with db.session() as s:
        return await runs.list_projects(s)


async def list_project_summaries(db: Database) -> list[tuple[Project, ProjectSummary]]:
    """`GET /api/projects`: every project with what the sidebar shows (M18 spec §7.1)."""
    async with db.session() as s:
        return await runs.project_summaries(s)


async def get_project_summary(
    db: Database, project_id: uuid.UUID
) -> tuple[Project, ProjectSummary]:
    async with db.session() as s:
        found = await runs.project_summaries(s, project_id)
    if not found:
        raise runs.NotFoundError(f"project {project_id} not found")
    return found[0]


def new_project_summary(project: Project) -> ProjectSummary:
    """A project just created has no sources and no runs."""
    return ProjectSummary(last_activity_at=project.created_at)


async def list_sources(db: Database, project_id: uuid.UUID) -> list[SourceRow]:
    async with db.session() as s:
        await runs.get_project(s, project_id)
        return await runs.list_sources(s, project_id)


def _nothing_left(data: BinaryIO) -> bool:
    """Whether the file has nothing left to read; it is left where it stood."""
    start = data.tell()
    empty = not data.read(1)
    data.seek(start)
    return empty


def _parse_stored(
    storage: Storage, key: str, coglossa_export: bool, ocr: OcrSettings | None
) -> list[Source]:
    """Parsing a PDF can take seconds, and reading its scanned pages with OCR a second or two a
    page per CPU: it runs off the event loop so the API keeps answering."""
    with storage.local_file(key) as path:
        if coglossa_export:
            return load_coglossa_export("src1", path)
        return [make_source("src1", path, ocr=ocr)]


async def add_source(
    db: Database,
    storage: Storage,
    project_id: uuid.UUID,
    filename: str,
    data: bytes | BinaryIO,
    *,
    coglossa_export: bool = False,
    ocr: OcrSettings | None = None,
) -> list[uuid.UUID]:
    """Store an upload, parse it into units (spec §5) and record it. Returns the new source ids:
    one, or two for a Coglossa export that carries a translation guide. A file that cannot be
    parsed is not kept. `data` is the content, or a binary file read from where it stands (the
    API passes the file Starlette spooled the upload to, so the body is never held in memory).
    `ocr` is `ingest.ocr`'s settings when it is auto: a PDF's scanned pages are read on this
    request, off the event loop (CRL-95)."""
    name = display_name(filename)
    if not name:
        raise InvalidRequestError("the upload has no file name")
    if len(name) > _MAX_FILENAME:
        raise InvalidRequestError(f"the file name is longer than {_MAX_FILENAME} characters")
    if not coglossa_export:
        check_extension(name)
    if isinstance(data, bytes):
        empty = not data
    else:  # the spooled file of an upload may be on disk
        empty = await asyncio.to_thread(_nothing_left, data)
    if empty:
        raise IngestError(f"{name} is empty")
    async with db.session() as s:
        await runs.get_project(s, project_id)
    source_id = uuid.uuid4()
    prefix = f"projects/{project_id}/sources/{source_id}/"
    key = prefix + safe_filename(name)
    try:
        await storage_call(storage.put, key, data)
        parsed = await asyncio.to_thread(_parse_stored, storage, key, coglossa_export, ocr)
        parsed[0] = parsed[0].model_copy(update={"name": name})
        ids: list[uuid.UUID] = []
        async with db.session() as s, s.begin():
            for i, source in enumerate(parsed):
                row = await runs.add_source(
                    s,
                    project_id,
                    source,
                    storage_key=key,
                    source_id=source_id if i == 0 else None,
                )
                ids.append(row.id)
    except BaseException:
        with contextlib.suppress(StorageError):  # nothing points at the file
            await storage_call(storage.delete_prefix, prefix)
        raise
    return ids


# ---------------------------------------------------------------- runs


async def _create_run(
    db: Database,
    storage: Storage,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    req: RunRequest,
    *,
    pack_name: str,
    pack_hash_: str,
    pack_snapshot: dict[str, Any],
    profile: str | None,
    reference: bytes | None,
    session: AsyncSession | None = None,
) -> uuid.UUID:
    """The run row, its ordered sources and, when the profile has one, a copy of the reference
    document under runs/<id>/ so the run renders with the template it was queued with. With
    `session` the rows join the caller's transaction (a return, R-M15-3) and the caller removes
    runs/<id>/ if that transaction does not commit; without one they commit here."""
    run_id = uuid.uuid4()
    key = f"runs/{run_id}/reference.docx" if reference is not None else None

    async def insert(s: AsyncSession) -> None:
        if req.parent_run_id is not None:
            parent = await runs.get_run(s, req.parent_run_id)
            if parent.project_id != req.project_id:
                raise InvalidRequestError(
                    f"parent run {req.parent_run_id} belongs to another project"
                )
        await runs.create_run(
            s,
            project_id=req.project_id,
            value_statement=req.value_statement.strip(),
            profile=profile,
            max_iterations=(
                cfg.pipeline.max_iterations if req.max_iterations is None else req.max_iterations
            ),
            extra_guidance=req.extra_guidance,
            config_hash=config_hash(cfg),
            config_snapshot=cfg.model_dump(mode="json"),
            pack_name=pack_name,
            pack_hash=pack_hash_,
            pack_snapshot=pack_snapshot,
            prompt_versions=prompts.versions(run_prompt_ids()),
            corelata_version=__version__,
            docx_reference_key=key,
            parent_run_id=req.parent_run_id,
            source_ids=req.source_ids,
            run_id=run_id,
        )

    try:
        if key is not None:
            await storage_call(storage.put, key, reference)
        if session is not None:
            await insert(session)
        else:
            async with db.session() as s, s.begin():
                await insert(s)
    except BaseException:
        if key is not None:
            with contextlib.suppress(StorageError):
                await storage_call(storage.delete_prefix, f"runs/{run_id}/")
        raise
    return run_id


def _validate(req: RunRequest) -> None:
    if not req.value_statement.strip():
        raise InvalidRequestError("a run needs a value statement")
    check_run_text(req.value_statement, req.extra_guidance)
    if not req.source_ids:
        raise InvalidRequestError("a run needs at least one source")
    if len(set(req.source_ids)) != len(req.source_ids):
        raise InvalidRequestError("a source may be listed only once")
    if req.max_iterations is not None and not 0 <= req.max_iterations <= 10:
        raise InvalidRequestError("max_iterations must be between 0 and 10")


async def start_run(
    db: Database,
    storage: Storage,
    queue: JobQueue,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    req: RunRequest,
) -> uuid.UUID:
    """Snapshot the pack, store the run and queue it (spec §7.2 `created`)."""
    _validate(req)
    pack = load_run_pack(cfg, req.profile)  # PackError for an unknown or draft profile
    reference = (
        pack.docx_reference_path.read_bytes() if pack.docx_reference_path is not None else None
    )
    run_id = await _create_run(
        db,
        storage,
        cfg,
        prompts,
        req,
        pack_name=pack.name,
        pack_hash_=pack_hash(pack),
        pack_snapshot=pack.model_dump(mode="json"),
        profile=pack.profile,
        reference=reference,
    )
    await _defer_run(db, queue, run_id)
    return run_id


async def cancel_run(
    db: Database, run_id: uuid.UUID, *, stalled_after_s: float = STALLED_AFTER_S
) -> RunState:
    """Ask a run to stop. A run nothing is executing yet ends at once. So does a run whose job
    was taken by a worker that is gone, its heartbeat `stalled_after_s` old or its worker row
    deleted (R-M17-2): the job is closed as aborted in the same transaction, so it never runs
    again, and should that worker still be alive it stops at its next write (`RunEnded` in the
    worker). A run a live worker holds stops at its next stage boundary (the pipeline polls the
    flag). Returns the state after the call. Callers with a configuration pass
    `worker.stalled_after_s`."""
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        state = RunState(run.state)
        if state in TERMINAL_STATES:
            raise InvalidRunStateError(f"run {run_id} is already {state.value}")
        run.cancel_requested = True
        ends_now = state is RunState.CREATED or await runs.close_abandoned_job(
            s, run_id, stalled_after_s=stalled_after_s
        )
        if ends_now:
            run.state = RunState.CANCELLED.value
            run.finished_at = await runs.db_now(s)
        await runs.notify_run(s, run_id)  # the flag shows on the progress page at once
        if ends_now:
            await reruns_ended(s, [run_id])
        return RunState(run.state)


# A rerun that ends in one of these produced no report to review, so its return is not spent
# (R-M15-1, R-M15-9): the run can be returned, or accepted, again.
FREED_BY = TERMINAL_STATES - {RunState.COMPLETED}

Reruns = dict[uuid.UUID, tuple[RunState, str | None]]


async def _store_review_state(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Recompute the decision from the events and reruns this transaction sees and store it on
    the run (CRL-17, R-M10-1, R-M15-2): two indexed reads per review, none per progress read. The
    row lock comes first, so a concurrent review of the same run waits and then sees this one's
    events."""
    await runs.lock_run(s, run_id)
    events = await runs.load_review_events(s, run_id)
    state = _review_state(events, await _reruns(s, events))
    await runs.set_review_state(s, run_id, state.model_dump(mode="json") if state else None)


async def _reruns(s: AsyncSession, events: list[ReviewEvent]) -> Reruns:
    return await runs.rerun_states(s, [e.child_run_id for e in events if e.child_run_id])


async def reruns_ended(
    s: AsyncSession, run_ids: list[uuid.UUID], *, tolerate: bool = False
) -> None:
    """The runs in `run_ids` reached a terminal state in this transaction: recompute each one's
    parent's stored decision and announce the parent (R-M15-2), so an open Review page sees the
    rerun's fate. Call it after the runs' own writes, with their row locks held; the parents'
    locks come second, in sorted order, and no path holds a parent's lock while it waits for a
    child's (R-M15-10). A run without a parent costs one read. With `tolerate` (the orphan
    sweep, whose one transaction must not stall on one bad parent, R-M15-21) each parent runs in
    its own savepoint: a parent that cannot be recomputed is logged and skipped, but a lost
    connection still propagates (R-M14-15)."""
    for parent in await runs.parent_ids(s, run_ids):
        if not tolerate:
            await _store_review_state(s, parent)
            await runs.notify_run(s, parent)
            continue
        try:
            async with s.begin_nested():
                await _store_review_state(s, parent)
                await runs.notify_run(s, parent)
        except Exception as e:
            if isinstance(e, DBAPIError) and e.connection_invalidated:
                raise
            log.warning(
                "sweep: could not record a rerun's end on run %s: %s", parent, error_reason(e)
            )


def _live_return(events: list[ReviewEvent], reruns: Reruns) -> ReviewEvent | None:
    """The return that spends the run's one return (R-M8-1 as R-M15-1 reads it): the newest
    return whose rerun is being created, still running, or completed."""
    for event in reversed(events):
        if event.action != ReviewAction.RETURN.value:
            continue
        rerun = reruns.get(event.child_run_id) if event.child_run_id else None
        if rerun is None or rerun[0] not in FREED_BY:
            return event
    return None


async def review_run(
    db: Database,
    storage: Storage,
    queue: JobQueue,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    run_id: uuid.UUID,
    action: ReviewAction,
    *,
    note: str = "",
    actor: str | None = None,
) -> uuid.UUID | None:
    """Spec §10.1 review: `accept` records the decision; `return` records it and creates a
    linked run (`parent_run_id`) over the same sources, statement and pack snapshot, with the
    note appended to the writer guidance. Returns the new run's id for a return. A run whose
    rerun ended without a report can be returned again (R-M15-1); a run whose stored decision
    is an accept cannot be returned (R-M16-1). The rerun, the return event and the stored
    decision commit in one transaction under the run's row lock (R-M15-3): a second return, or
    a return racing an accept, waits for the lock and then sees the other's decision, and an
    interrupted return leaves nothing behind unless its commit landed. A rerun left without a
    queued job (a cancellation during `_defer_run`, after the commit) stays CREATED and spends
    the return until the orphan sweep fails it, which frees the return."""
    if len(note) > GUIDANCE_MAX_LENGTH:
        raise InvalidRequestError(f"a review note is at most {GUIDANCE_MAX_LENGTH} characters")
    child: uuid.UUID | None = None
    try:
        async with db.session() as s, s.begin():
            run = await runs.get_run(s, run_id, lock=True)
            if RunState(run.state) is not RunState.COMPLETED:
                raise InvalidRunStateError(
                    f"run {run_id} is {run.state}; only a completed run can be reviewed"
                )
            if action is ReviewAction.ACCEPT:
                await runs.add_review_event(s, run_id, action.value, note, actor, None)
                await _store_review_state(s, run_id)
                return None
            if not note.strip():
                raise InvalidRequestError("a return needs a note for the writer")
            if (run.review_state or {}).get("decision") == ReviewDecision.ACCEPTED.value:
                # An accept is the reviewer's final word on the report, which may already have
                # gone out (CRL-21, R-M16-1). Read under the row lock, so an accept that commits
                # while this return waits for the lock is seen here.
                raise ConflictError(f"run {run_id} was accepted; start a new run to change it")
            events = await runs.load_review_events(s, run_id)
            earlier = _live_return(events, await _reruns(s, events))
            if earlier is not None:
                if earlier.child_run_id is None:
                    raise ConflictError(
                        f"run {run_id} is being returned; its rerun is not ready yet"
                    )
                raise ConflictError(
                    f"run {run_id} was already returned; its rerun is {earlier.child_run_id}. "
                    "Return that run to iterate again"
                )
            guidance = f"{run.extra_guidance}\nReviewer note: {note.strip()}".strip()
            if len(guidance) > RUN_GUIDANCE_MAX_LENGTH:
                raise InvalidRequestError(GUIDANCE_CAP_MESSAGE)
            reference = (
                await storage_call(storage.get, run.docx_reference_key)
                if run.docx_reference_key
                else None
            )
            child = await _create_run(
                db,
                storage,
                cfg,
                prompts,
                RunRequest(
                    project_id=run.project_id,
                    source_ids=await runs.run_source_ids(s, run_id),
                    value_statement=run.value_statement,
                    profile=run.profile,
                    max_iterations=run.max_iterations,
                    extra_guidance=guidance,
                    parent_run_id=run_id,
                ),
                pack_name=run.pack_name,
                pack_hash_=run.pack_hash,
                pack_snapshot=run.pack_snapshot,
                profile=run.profile,
                reference=reference,
                session=s,
            )
            await runs.add_review_event(s, run_id, action.value, note, actor, child)
            await _store_review_state(s, run_id)
    except BaseException:
        # Nothing committed, so the database has nothing to undo. The rerun's copy of the
        # reference document goes in a thread that storage_call waits for even when cancelled,
        # so no CancelledError can stop it half way (R-M15-3, R-M19-4).
        if child is not None:
            with contextlib.suppress(StorageError):
                await storage_call(storage.delete_prefix, f"runs/{child}/")
        raise
    await _defer_run(db, queue, child)
    return child


def _review_state(events: list[ReviewEvent], reruns: Reruns) -> ReviewState | None:
    """The decision the review events amount to, given each rerun's state and error (`reruns`,
    by run id). A live return (its rerun being created, running or completed) wins over any
    accept; otherwise the latest event decides, so an accept after a failed rerun is "accepted",
    and a return whose rerun failed, with nothing after it, is "returned" with the rerun's fate.
    None when nobody reviewed the run."""
    if not events:
        return None
    chosen = _live_return(events, reruns) or events[-1]
    if chosen.action == ReviewAction.ACCEPT.value:
        return ReviewState(decision=ReviewDecision.ACCEPTED, at=chosen.at, actor=chosen.actor)
    rerun = reruns.get(chosen.child_run_id) if chosen.child_run_id else None
    state, error = rerun if rerun is not None and rerun[0] in TERMINAL_STATES else (None, None)
    return ReviewState(
        decision=ReviewDecision.RETURNED,
        at=chosen.at,
        actor=chosen.actor,
        child_run_id=str(chosen.child_run_id) if chosen.child_run_id else None,
        child_state=state,
        child_error=error,
        note=chosen.note,
    )


def _progress(
    run: Run, stages: list, source_ids: list[uuid.UUID], *, worker_gone: bool = False
) -> RunProgress:
    return RunProgress(
        run_id=str(run.id),
        project_id=str(run.project_id),
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        state=RunState(run.state),
        status=run.status,
        value_statement=run.value_statement,
        profile=run.profile,
        source_ids=[str(i) for i in source_ids],
        iteration=run.iteration,
        max_iterations=run.max_iterations,
        stages=stages,
        usage=Usage.model_validate(run.token_usage) if run.token_usage else None,
        cancel_requested=run.cancel_requested,
        worker_gone=worker_gone,
        attempts=run.attempts,
        error=run.error,
        export_error=run.export_error,
        review=ReviewState.model_validate(run.review_state) if run.review_state else None,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def run_progress(
    db: Database, run_id: uuid.UUID, *, stalled_after_s: float = STALLED_AFTER_S
) -> RunProgress:
    """The run as the progress page shows it. A run not yet ended costs one extra read, of
    whether the worker that took it is gone (`RunProgress.worker_gone`, CRL-49, CRL-69); callers
    with a configuration pass `worker.stalled_after_s`, as for `cancel_run`."""
    async with db.session() as s:
        run = await runs.get_run_brief(s, run_id)
        live = RunState(run.state) not in TERMINAL_STATES
        gone = live and await runs.has_abandoned_job(s, run_id, stalled_after_s=stalled_after_s)
        # The decision is stored on the run by review_run (CRL-17, R-M10-1); review_event is
        # never read here.
        stages = await runs.load_stages(s, run_id)
        return _progress(run, stages, await runs.run_source_ids(s, run_id), worker_gone=gone)


def _summary(run: Run) -> RunSummary:
    review = run.review_state or {}
    return RunSummary(
        run_id=str(run.id),
        project_id=str(run.project_id),
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        state=RunState(run.state),
        status=run.status,
        value_statement=run.value_statement,
        profile=run.profile,
        iteration=run.iteration,
        max_iterations=run.max_iterations,
        created_at=run.created_at,
        finished_at=run.finished_at,
        review_decision=review.get("decision"),
        review_child_state=review.get("child_state"),
    )


async def list_runs(
    db: Database,
    project_id: uuid.UUID,
    *,
    limit: int = 100,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[RunSummary]:
    """A project's runs, newest first; `before` (from `parse_run_cursor`) starts after that run."""
    async with db.session() as s:
        await runs.get_project(s, project_id)
        found = await runs.list_runs(s, project_id, limit=limit, before=before)
        return [_summary(r) for r in found]


def run_cursor(run: RunSummary) -> str:
    """The cursor that pages after `run` (CRL-24, R-M14-1): `<created_at>|<run_id>`, the time in
    ISO-8601 UTC to the microsecond, as Postgres stores it."""
    stamp = run.created_at.astimezone(UTC).isoformat(timespec="microseconds")
    return f"{stamp.replace('+00:00', 'Z')}|{run.run_id}"


def parse_run_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """`run_cursor`'s inverse. Anything else is an InvalidRequestError (HTTP 422)."""
    stamp, _, run_id = cursor.rpartition("|")
    try:
        created_at = datetime.fromisoformat(stamp)
        if created_at.tzinfo is None:
            raise ValueError("no time zone")
        return created_at, uuid.UUID(run_id)
    except ValueError:
        raise InvalidRequestError(
            "invalid cursor 'before': pass the next_before of the previous page"
        ) from None


async def stored_export(
    db: Database, storage: Storage, run_id: uuid.UUID, name: str
) -> bytes | None:
    """One of the worker's stored renders (`trace.json`, `report.docx`, ...), or None when the run
    has not stored one by that name. Reads the file off the event loop."""
    async with db.session() as s:
        await runs.get_run(s, run_id)
        row = next((r for r in await runs.list_exports(s, run_id) if r.name == name), None)
    if row is None:
        return None
    return await storage_call(storage.get, row.storage_key)


async def get_run_record(db: Database, run_id: uuid.UUID, *, with_io: bool = True) -> RunRecord:
    """`with_io=False` leaves the model calls' stored request and response unread (CRL-103)."""
    async with db.session() as s:
        return await records.load_record(s, run_id, with_io=with_io)


async def get_findings(db: Database, run_id: uuid.UUID) -> list[Finding]:
    """Every audit finding of the run, all iterations, from the finding rows alone (CRL-103);
    only a run with none is looked up, so an unknown run is still a NotFoundError."""
    async with db.session() as s:
        found = await runs.load_findings(s, run_id)
        if not found:
            await runs.require_run(s, run_id)
        return found


async def get_claim_provenance(db: Database, run_id: uuid.UUID, claim_id: str) -> ClaimProvenance:
    """A claim of the delivered report with its evidence units, from the report and the sources'
    units alone (CRL-103). InvalidRunStateError while the run has no report; TraceError for a
    claim the report does not have."""
    async with db.session() as s:
        state, report = await records.load_report(s, run_id)
        if report is None:
            raise InvalidRunStateError(f"run {run_id} has no report (state {state.value})")
        sources = await records.load_sources(s, run_id)
    return report_claim_provenance(str(run_id), report, sources, claim_id)


async def reference_document(db: Database, storage: Storage, run_id: uuid.UUID) -> bytes | None:
    """The DOCX reference the run was queued with, or None when its profile names none."""
    async with db.session() as s:
        run = await runs.get_run(s, run_id)
    if not run.docx_reference_key:
        return None
    return await storage_call(storage.get, run.docx_reference_key)


# ---------------------------------------------------------------- discovery (spec §7.1)


async def start_discovery(
    db: Database,
    queue: JobQueue,
    project_id: uuid.UUID,
    source_ids: list[uuid.UUID],
    audience_hint: str = "",
) -> uuid.UUID:
    """Queue a discovery over the chosen sources. It never starts a run by itself."""
    if not source_ids:
        raise InvalidRequestError("a discovery needs at least one source")
    if len(set(source_ids)) != len(source_ids):
        raise InvalidRequestError("a source may be listed only once")
    async with db.session() as s, s.begin():
        row = await discoveries.create(
            s, project_id=project_id, source_ids=source_ids, audience_hint=audience_hint.strip()
        )
    await _defer_discovery(db, queue, row.id)
    return row.id


def _duration(seconds: float) -> str:
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    if seconds == int(seconds):
        return f"{int(seconds)} seconds"
    return f"{seconds:f}".rstrip("0") + " seconds"  # never an exponent


def discovery_deadline_error(deadline_s: float) -> str:
    """What a discovery past its work limit records as its error; the New run screen shows it."""
    return (
        f"Discovery did not finish within {_duration(deadline_s)} and was stopped. "
        "Start a new discovery."
    )


def discovery_start_error(start_deadline_s: float) -> str:
    """What a discovery no worker claimed within its start limit records as its error."""
    return (
        f"Discovery did not start within {_duration(start_deadline_s)} and was stopped: the "
        "worker was stopped or busy with runs. Start a new discovery."
    )


async def expire_discoveries(
    s: AsyncSession,
    *,
    start_deadline_s: float,
    deadline_s: float,
    discovery_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Fail every discovery past the limit that applies to it (only `discovery_id`, when given),
    with that limit's error; returns the ids it failed (R-M17-26)."""
    return await discoveries.expire(
        s,
        start_deadline_s=start_deadline_s,
        deadline_s=deadline_s,
        start_error=discovery_start_error(start_deadline_s),
        error=discovery_deadline_error(deadline_s),
        discovery_id=discovery_id,
    )


async def get_discovery(
    db: Database,
    discovery_id: uuid.UUID,
    *,
    deadline_s: float = DISCOVERY_DEADLINE_S,
    start_deadline_s: float = DISCOVERY_START_DEADLINE_S,
) -> DiscoveryView:
    """The discovery as stored, after failing it if it is past the limit that applies and not
    ended (R-M17-1, R-M17-26), on the database's clock: `created_at` + `start_deadline_s` while
    no worker has claimed it, `started_at` + `deadline_s` once one has. The limits hold whenever
    anyone reads, with or without a worker. Callers with a configuration pass
    `worker.discovery_deadline_s` and `worker.discovery_start_deadline_s`."""
    async with db.session() as s:
        async with s.begin():
            await expire_discoveries(
                s,
                start_deadline_s=start_deadline_s,
                deadline_s=deadline_s,
                discovery_id=discovery_id,
            )
        return await discoveries.view(
            s, discovery_id, deadline_s=deadline_s, start_deadline_s=start_deadline_s
        )
