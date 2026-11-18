"""Discovery rows (spec §7.1): a job that proposes value statements over chosen sources."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.llm.agent import CallLog
from corelata.schema import (
    CandidateStatement,
    DiscoveryResult,
    DiscoveryState,
    DiscoveryView,
    LLMCallRecord,
)
from corelata.store import runs
from corelata.store.models import Discovery, DiscoveryCandidate, DiscoverySource


async def create(
    s: AsyncSession, *, project_id: uuid.UUID, source_ids: list[uuid.UUID], audience_hint: str
) -> Discovery:
    known = {r.id for r in await runs.list_sources(s, project_id)}
    for sid in source_ids:
        if sid not in known:
            raise runs.NotFoundError(f"source {sid} not in project {project_id}")
    # created_at on the database's clock, like the start limit it is compared with (CRL-53)
    now = await s.scalar(select(func.now()))
    row = Discovery(
        project_id=project_id, audience_hint=audience_hint, llm_calls=[], created_at=now
    )
    s.add(row)
    await s.flush()
    s.add_all(
        DiscoverySource(discovery_id=row.id, ordinal=i, source_id=sid)
        for i, sid in enumerate(source_ids, start=1)
    )
    await s.flush()
    return row


async def get(s: AsyncSession, discovery_id: uuid.UUID, *, lock: bool = False) -> Discovery:
    query = select(Discovery).where(Discovery.id == discovery_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await s.scalar(query)
    if row is None:
        raise runs.NotFoundError(f"discovery {discovery_id} not found")
    return row


# A discovery has two limits, both on the database's clock (CRL-38, R-M17-1, R-M17-26): one no
# worker has claimed is failed `start_deadline_s` after it was created, and one a worker claimed
# is failed `deadline_s` after its claim. One conditional statement each: idempotent, and the row
# lock it takes serialises it with the worker's claim and finish, so whichever commits first
# decides. An ended discovery is never touched.
_FAIL = "UPDATE discovery SET state = 'failed', finished_at = now(), "
_NOT_STARTED = (
    _FAIL + "error = :start_error WHERE state = 'created' "
    "AND created_at <= now() - make_interval(secs => :start_deadline_s)"
)
_NOT_FINISHED = (
    _FAIL + "error = :error WHERE state = 'running' "
    "AND started_at <= now() - make_interval(secs => :deadline_s)"
)
_EXPIRE_ALL = [text(q + " RETURNING id") for q in (_NOT_STARTED, _NOT_FINISHED)]
_EXPIRE_ONE = [text(q + " AND id = :id RETURNING id") for q in (_NOT_STARTED, _NOT_FINISHED)]
_CLOCK = text(
    "SELECT now(), extract(epoch FROM now() - created_at), "
    "extract(epoch FROM now() - coalesce(started_at, now())) FROM discovery WHERE id = :id"
)


async def expire(
    s: AsyncSession,
    *,
    start_deadline_s: float,
    deadline_s: float,
    start_error: str,
    error: str,
    discovery_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Fail every discovery past the limit that applies to it (only `discovery_id`, when given):
    `start_error` for one never claimed, `error` for one running. Returns the ids it failed."""
    params: dict[str, object] = {
        "start_deadline_s": start_deadline_s,
        "deadline_s": deadline_s,
        "start_error": start_error,
        "error": error,
    }
    statements = _EXPIRE_ALL
    if discovery_id is not None:
        statements, params = _EXPIRE_ONE, {**params, "id": discovery_id}
    return [i for statement in statements for i in await s.scalars(statement, params)]


@dataclass(frozen=True)
class Clock:
    """The database's `now()` (the transaction's start) and the discovery's ages by it;
    `since_started_s` is 0 for a discovery no worker has claimed."""

    now: datetime
    since_created_s: float
    since_started_s: float


async def clock(s: AsyncSession, discovery_id: uuid.UUID) -> Clock:
    now, created, started = (await s.execute(_CLOCK, {"id": discovery_id})).one()
    return Clock(now, float(created), float(started))


async def source_ids(s: AsyncSession, discovery_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await s.scalars(
            select(DiscoverySource.source_id)
            .where(DiscoverySource.discovery_id == discovery_id)
            .order_by(DiscoverySource.ordinal)
        )
    )


async def set_candidates(s: AsyncSession, discovery_id: uuid.UUID, result: DiscoveryResult) -> None:
    await s.execute(
        delete(DiscoveryCandidate).where(DiscoveryCandidate.discovery_id == discovery_id)
    )
    s.add_all(
        DiscoveryCandidate(
            discovery_id=discovery_id,
            ordinal=i,
            text=c.text,
            audience=c.audience,
            evidence=list(c.evidence),
            confidence_note=c.confidence_note,
        )
        for i, c in enumerate(result.candidates, start=1)
    )
    await s.flush()


async def view(
    s: AsyncSession, discovery_id: uuid.UUID, *, deadline_s: float, start_deadline_s: float
) -> DiscoveryView:
    row = await get(s, discovery_id)
    # the limit that applies (R-M17-27): the work limit from the claim on, ended or not
    if row.started_at is not None:
        deadline_at = row.started_at + timedelta(seconds=deadline_s)
    else:
        deadline_at = row.created_at + timedelta(seconds=start_deadline_s)
    candidates = await s.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.discovery_id == discovery_id)
        .order_by(DiscoveryCandidate.ordinal)
    )
    calls = [LLMCallRecord.model_validate(c) for c in row.llm_calls]
    return DiscoveryView(
        discovery_id=str(row.id),
        project_id=str(row.project_id),
        state=DiscoveryState(row.state),
        audience_hint=row.audience_hint,
        source_ids=[str(sid) for sid in await source_ids(s, discovery_id)],
        candidates=[
            CandidateStatement(
                text=c.text,
                audience=c.audience,
                evidence=list(c.evidence),
                confidence_note=c.confidence_note,
            )
            for c in candidates
        ],
        usage=CallLog(records=calls).usage() if calls else None,
        error=row.error,
        created_at=row.created_at,
        deadline_at=deadline_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
