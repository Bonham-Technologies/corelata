"""Removing a source or a whole project (CRL-125): an operator's command-line tool for a file
added by mistake or a project that should not exist. The web app and the API have no delete.

A removal takes the project row's lock (FOR UPDATE, so no run, source or discovery can be added
to the project meanwhile), works out what goes, refuses when something it would take is still
running, deletes the rows, then removes the stored files, and announces every removed run on the
run channel, all in one transaction. The rows go first, so every row lock is taken before a file
is lost: a removal that loses a lock or a deadlock (a return locks its run, then inserts its
rerun into the project) is rolled back with every file still there. If removing the files fails,
the rows are rolled back too; if the commit fails after them, the same command run again finishes
the job (a missing file is no error). What goes:

- a source: its row and units, with every row that shares its stored file (a Coglossa export's
  guide), and the file's directory `projects/<project>/sources/<id>/`; the discoveries that read
  it (their candidate statements were drawn from it); and only with `with_runs`, the runs that
  used it, with everything a run owns (stages, drafts, claims, findings, model calls, exports,
  review events) and its files under `runs/<id>/`. Without `with_runs` a source a run used is
  refused. A run that names a removed run as its parent but did not use the source stays, its
  parent link cleared.
- a project: everything in it, `projects/<id>/` and every run's `runs/<id>/`.
"""

import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, delete, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.schema import TERMINAL_STATES, DiscoveryState, RunState
from corelata.service import ConflictError
from corelata.storage import Storage, storage_call
from corelata.store import runs
from corelata.store.db import Database
from corelata.store.models import Discovery, DiscoverySource, Project, Run, RunSource, SourceRow

log = logging.getLogger("corelata.removal")

_DISCOVERY_ENDED = {DiscoveryState.COMPLETED.value, DiscoveryState.FAILED.value}
_LISTED = 5  # ids a refusal names before "and N more"
# what the database says when a removal loses a lock to another change to the project
_LOST_A_LOCK = {"40P01": "deadlock", "40001": "serialization failure", "55P03": "lock timeout"}


@dataclass(frozen=True)
class Item:
    id: uuid.UUID
    label: str  # a source's name; a run's or a discovery's state


@dataclass(frozen=True)
class Removal:
    """What a removal takes away, in list order."""

    project_id: uuid.UUID
    project: str
    whole_project: bool
    sources: tuple[Item, ...]
    runs: tuple[Item, ...]
    discoveries: tuple[Item, ...]
    prefixes: tuple[str, ...]  # stored files: each a key prefix

    def ids(self) -> tuple[frozenset[uuid.UUID], ...]:
        return tuple(frozenset(i.id for i in items) for items in self.groups())

    def groups(self) -> tuple[tuple[Item, ...], ...]:
        return self.sources, self.runs, self.discoveries


@dataclass(frozen=True)
class SourceListing:
    id: uuid.UUID
    name: str
    created_at: datetime
    runs: int  # runs that used it


def _ids(items: Iterable[Item]) -> str:
    listed = [str(i.id) for i in items]
    more = len(listed) - _LISTED
    return ", ".join(listed[:_LISTED]) + (f" and {more} more" if more > 0 else "")


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") else f"{n} {word}s"


def summary(removal: Removal) -> str:
    """One line: what the removal took (or takes)."""
    counts = ", ".join(
        _plural(len(items), word)
        for items, word in zip(removal.groups(), ("source", "run", "discovery"), strict=True)
    )
    if removal.whole_project:
        return f"project '{removal.project}' ({removal.project_id}): {counts}"
    first = removal.sources[0]
    return f"source {first.id} ({first.label}) of project '{removal.project}': {counts}"


# ---------------------------------------------------------------- what goes


async def _items(s: AsyncSession, query: Select[Any]) -> tuple[Item, ...]:
    return tuple(Item(row[0], row[1]) for row in await s.execute(query))


def _run_items(where: ColumnElement[bool]) -> Select[Any]:
    return select(Run.id, Run.state).where(where).order_by(Run.created_at, Run.id)


def _discovery_items(where: ColumnElement[bool]) -> Select[Any]:
    return (
        select(Discovery.id, Discovery.state)
        .where(where)
        .order_by(Discovery.created_at, Discovery.id)
    )


def _source_prefix(key: str, project_id: uuid.UUID) -> str:
    """The upload's own directory, projects/<project>/sources/<id>/, which holds its one file;
    the key alone should a stored key ever have another shape."""
    directory = key.rsplit("/", 1)[0] + "/"
    pattern = f"projects/{project_id}/sources/"
    if directory.startswith(pattern) and directory.count("/") == pattern.count("/") + 1:
        return directory
    return key


async def _source_removal(s: AsyncSession, source_id: uuid.UUID) -> Removal:
    found = (
        await s.execute(
            select(SourceRow.storage_key, SourceRow.project_id).where(SourceRow.id == source_id)
        )
    ).one_or_none()
    if found is None:
        raise runs.NotFoundError(f"source {source_id} not found")
    key, project_id = found
    project = await runs.get_project(s, project_id)
    sources = await _items(
        s,
        select(SourceRow.id, SourceRow.name)
        .where(SourceRow.project_id == project_id, SourceRow.storage_key == key)
        .order_by(SourceRow.created_at, SourceRow.id),
    )
    # the asked-for row first, so a refusal and the summary name it
    sources = tuple(sorted(sources, key=lambda i: i.id != source_id))
    ids = [i.id for i in sources]
    used = select(RunSource.run_id).where(RunSource.source_id.in_(ids))
    read = select(DiscoverySource.discovery_id).where(DiscoverySource.source_id.in_(ids))
    # a check run (CRL-94) uses the report it audits as well as its sources
    found_runs = await _items(s, _run_items(or_(Run.id.in_(used), Run.report_source_id.in_(ids))))
    return Removal(
        project_id=project_id,
        project=project.name,
        whole_project=False,
        sources=sources,
        runs=found_runs,
        discoveries=await _items(s, _discovery_items(Discovery.id.in_(read))),
        prefixes=(_source_prefix(key, project_id), *(f"runs/{r.id}/" for r in found_runs)),
    )


async def _project_removal(s: AsyncSession, project: Project) -> Removal:
    found_runs = await _items(s, _run_items(Run.project_id == project.id))
    return Removal(
        project_id=project.id,
        project=project.name,
        whole_project=True,
        sources=await _items(
            s,
            select(SourceRow.id, SourceRow.name)
            .where(SourceRow.project_id == project.id)
            .order_by(SourceRow.created_at, SourceRow.id),
        ),
        runs=found_runs,
        discoveries=await _items(s, _discovery_items(Discovery.project_id == project.id)),
        prefixes=(f"projects/{project.id}/", *(f"runs/{r.id}/" for r in found_runs)),
    )


async def plan_source(db: Database, source_id: uuid.UUID) -> Removal:
    """What deleting the source would take, now; it changes nothing."""
    async with db.session() as s:
        return await _source_removal(s, source_id)


async def plan_project(db: Database, name: str) -> Removal:
    """What deleting the project would take, now; it changes nothing."""
    async with db.session() as s:
        return await _project_removal(s, await runs.find_project(s, name))


def check(removal: Removal, *, with_runs: bool = False) -> None:
    """ConflictError when the removal must not go ahead: a source that runs used, without
    `with_runs`; a run or a discovery it would take that has not ended (cancel the run first:
    a removal never stops work in flight)."""
    if not removal.whole_project and removal.runs and not with_runs:
        source = removal.sources[0]
        raise ConflictError(
            f"source {source.id} ({source.label}) was used by "
            f"{_plural(len(removal.runs), 'run')}: {_ids(removal.runs)}; add --with-runs to "
            "delete those runs and their reports too"
        )
    active = [r for r in removal.runs if RunState(r.label) not in TERMINAL_STATES]
    if active:
        raise ConflictError(
            f"{_plural(len(active), 'run')} not ended yet: {_ids(active)}; cancel "
            "(corelata cancel RUN_ID) and wait until it has ended, then try again"
        )
    pending = [d for d in removal.discoveries if d.label not in _DISCOVERY_ENDED]
    if pending:
        raise ConflictError(
            f"{_plural(len(pending), 'discovery')} not ended yet: {_ids(pending)}; it ends "
            "by itself by its deadline, then try again"
        )


# ---------------------------------------------------------------- removing


async def _lock_project(s: AsyncSession, project_id: uuid.UUID) -> None:
    """FOR UPDATE: inserting a run, a source or a discovery into the project (KEY SHARE) and an
    upload's lock (`runs.lock_project`) wait until the removal has committed."""
    await s.execute(select(Project.id).where(Project.id == project_id).with_for_update())


async def _remove(
    s: AsyncSession,
    storage: Storage,
    removal: Removal,
    *,
    with_runs: bool,
    expected: Removal | None,
) -> None:
    check(removal, with_runs=with_runs)
    if expected is not None and expected.ids() != removal.ids():
        raise ConflictError(
            "what would be deleted changed since it was listed; nothing was deleted, try again"
        )
    # rows first: every lock and cascade is taken while nothing is lost yet (module docstring)
    if removal.whole_project:
        await runs.delete_project(s, removal.project_id)  # every row cascades from the project
    else:
        for table, items in zip((Discovery, Run), (removal.discoveries, removal.runs), strict=True):
            if items:
                await s.execute(delete(table).where(table.id.in_([i.id for i in items])))
        await s.execute(delete(SourceRow).where(SourceRow.id.in_([i.id for i in removal.sources])))
    for prefix in removal.prefixes:
        await storage_call(storage.delete_prefix, prefix)
    for run in removal.runs:  # an open progress page gets `event: deleted` (CRL-22)
        await runs.notify_run(s, run.id)


@contextlib.asynccontextmanager
async def _lost_a_lock() -> AsyncIterator[None]:
    """A removal that loses a lock to another change to the project (a review returning one of
    its runs, say) is a ConflictError. The rows go before the files, so it lost nothing."""
    try:
        yield
    except DBAPIError as e:
        what = _LOST_A_LOCK.get(getattr(e.orig, "sqlstate", None) or "")
        if what is None:
            raise
        raise ConflictError(
            f"another change to the project got in the way ({what}); nothing was deleted, try again"
        ) from e


def _audit(removal: Removal) -> None:
    log.info(
        "deleted %s; sources [%s]; runs [%s]; discoveries [%s]; stored files [%s]",
        summary(removal),
        ", ".join(str(i.id) for i in removal.sources),
        ", ".join(str(i.id) for i in removal.runs),
        ", ".join(str(i.id) for i in removal.discoveries),
        ", ".join(removal.prefixes),
    )


async def delete_source(
    db: Database,
    storage: Storage,
    source_id: uuid.UUID,
    *,
    with_runs: bool = False,
    expected: Removal | None = None,
) -> Removal:
    """Delete the source as the module says. `expected`: the plan the operator confirmed; if
    what would go differs from it now, nothing is deleted (ConflictError)."""
    async with _lost_a_lock(), db.session() as s, s.begin():
        project_id = await s.scalar(select(SourceRow.project_id).where(SourceRow.id == source_id))
        if project_id is None:
            raise runs.NotFoundError(f"source {source_id} not found")
        await _lock_project(s, project_id)
        removal = await _source_removal(s, source_id)
        await _remove(s, storage, removal, with_runs=with_runs, expected=expected)
    _audit(removal)
    return removal


async def delete_project(
    db: Database, storage: Storage, name: str, *, expected: Removal | None = None
) -> Removal:
    """Delete the project and everything in it, as the module says."""
    async with _lost_a_lock(), db.session() as s, s.begin():
        project = await runs.find_project(s, name)
        await _lock_project(s, project.id)
        removal = await _project_removal(s, project)
        await _remove(s, storage, removal, with_runs=True, expected=expected)
    _audit(removal)
    return removal


async def list_sources(db: Database, name: str) -> list[SourceListing]:
    """The project's sources in list order, each with how many runs used it."""
    async with db.session() as s:
        project = await runs.find_project(s, name)
        rows = await s.execute(
            select(
                SourceRow.id,
                SourceRow.name,
                SourceRow.created_at,
                func.count(func.distinct(RunSource.run_id))
                # a check run's report is never one of its sources (R-CRL94-5): no overlap
                + select(func.count())
                .where(Run.report_source_id == SourceRow.id)
                .scalar_subquery(),
            )
            .outerjoin(RunSource, RunSource.source_id == SourceRow.id)
            .where(SourceRow.project_id == project.id)
            .group_by(SourceRow.id)
            .order_by(SourceRow.created_at, SourceRow.id)
        )
        return [SourceListing(*row) for row in rows]
