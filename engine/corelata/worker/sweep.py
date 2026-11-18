"""Runs and discoveries whose job is gone (spec §7.5; M3 follow-up). A row commits before its
job is queued, and a job can end `failed` outside the run (database retries exhausted mid-run);
either way the row would sit non-terminal forever. The worker sweeps them every minute."""

import logging
import uuid

from sqlalchemy import bindparam, func, text, update

from corelata.schema import TERMINAL_STATES, DiscoveryState, RunState
from corelata.service import expire_discoveries as expire
from corelata.service import reruns_ended
from corelata.store import runs
from corelata.store.db import Database
from corelata.store.models import Discovery, Run

log = logging.getLogger("corelata.worker")

ORPHAN_GRACE_S = 120.0  # longer than any request that commits a row and then queues its job
ORPHAN_ERROR = (
    "no queued job exists for this {what}: the queue was unavailable when it was created, or "
    "its job failed outside the run; start it again"
)

# Rows past the grace period with no job that is waiting (todo) or executing (doing).
_ORPHAN_RUNS = text(
    "SELECT r.id FROM run r WHERE r.state NOT IN :terminal "
    "AND r.created_at < now() - make_interval(secs => :grace_s) "
    "AND NOT EXISTS (SELECT 1 FROM procrastinate_jobs j WHERE j.args->>'run_id' = r.id::text "
    "AND j.status IN ('todo', 'doing')) FOR UPDATE SKIP LOCKED"
).bindparams(bindparam("terminal", expanding=True))
_ORPHAN_DISCOVERIES = text(
    "SELECT d.id FROM discovery d WHERE d.state IN ('created', 'running') "
    "AND d.created_at < now() - make_interval(secs => :grace_s) AND NOT EXISTS (SELECT 1 "
    "FROM procrastinate_jobs j WHERE j.args->>'discovery_id' = d.id::text "
    "AND j.status IN ('todo', 'doing')) "
    "FOR UPDATE SKIP LOCKED"
)


async def sweep_orphans(db: Database, *, grace_s: float) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Mark such runs and discoveries `failed`; returns the ids it changed."""
    terminal = [state.value for state in TERMINAL_STATES]
    async with db.session() as s, s.begin():
        # created_at and the grace are both the database's (CRL-87): a worker host whose clock
        # runs ahead must not sweep a run whose job is still being queued
        run_ids = list(await s.scalars(_ORPHAN_RUNS, {"terminal": terminal, "grace_s": grace_s}))
        if run_ids:
            await s.execute(
                update(Run)
                .where(Run.id.in_(run_ids))
                .values(
                    state=RunState.FAILED.value,
                    error=ORPHAN_ERROR.format(what="run"),
                    finished_at=func.now(),
                )
            )
            for run_id in run_ids:
                await runs.notify_run(s, run_id)
            # A swept rerun frees its parent's return (R-M15-2); one bad parent must not stall the
            # sweep (R-M15-21).
            await reruns_ended(s, run_ids, tolerate=True)
        # a discovery's created_at is on the database's clock (CRL-53), so its grace is too
        discovery_ids = list(await s.scalars(_ORPHAN_DISCOVERIES, {"grace_s": grace_s}))
        if discovery_ids:
            await s.execute(
                update(Discovery)
                .where(Discovery.id.in_(discovery_ids))
                .values(
                    state=DiscoveryState.FAILED.value,
                    error=ORPHAN_ERROR.format(what="discovery"),
                    finished_at=func.now(),
                )
            )
    for run_id in run_ids:
        log.warning("run %s had no job; marked failed", run_id, extra={"run_id": str(run_id)})
    for discovery_id in discovery_ids:
        log.warning(
            "discovery %s had no job; marked failed",
            discovery_id,
            extra={"discovery_id": str(discovery_id)},
        )
    return run_ids, discovery_ids


async def expire_discoveries(
    db: Database, *, start_deadline_s: float, deadline_s: float
) -> list[uuid.UUID]:
    """Fail every discovery past the limit that applies to it that nobody has read since
    (R-M17-1, R-M17-26); returns the ids it failed. The API's read does the same for the one it
    reads."""
    async with db.session() as s, s.begin():
        expired = await expire(s, start_deadline_s=start_deadline_s, deadline_s=deadline_s)
    for discovery_id in expired:
        log.warning(
            "discovery %s passed its deadline; marked failed",
            discovery_id,
            extra={"discovery_id": str(discovery_id)},
        )
    return expired


# The operator guide's housekeeping statement (CRL-10): closed jobs older than the retention,
# aged by scheduled_at or, when a job was never scheduled, by its last event. Periodic defers
# reference jobs, so they go first.
_PURGE = text(
    "WITH old AS ("
    "  SELECT j.id FROM procrastinate_jobs j"
    "  WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted')"
    "    AND COALESCE(j.scheduled_at,"
    "          (SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id))"
    "        < now() - make_interval(days => :days)),"
    "gone AS (DELETE FROM procrastinate_periodic_defers WHERE job_id IN (SELECT id FROM old)) "
    "DELETE FROM procrastinate_jobs WHERE id IN (SELECT id FROM old) RETURNING id"
)


async def purge_closed_jobs(db: Database, *, retention_days: int) -> int:
    """Delete closed jobs older than `retention_days`; returns how many went."""
    async with db.session() as s, s.begin():
        removed = len(list(await s.scalars(_PURGE, {"days": retention_days})))
    if removed:
        log.info("purged %d closed job(s) older than %d days", removed, retention_days)
    return removed
