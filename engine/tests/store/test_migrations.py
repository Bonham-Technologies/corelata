import uuid
from datetime import UTC, datetime

from procrastinate.schema import SchemaManager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from corelata.schema import ReviewState
from corelata.store.db import to_sqlalchemy_url
from corelata.store.migrate import MIGRATIONS_DIR, downgrade, migration_state, upgrade
from corelata.store.models import Base
from corelata.testing.postgres import PROCRASTINATE_TABLES, create_test_database, drop_test_database

OUR_TABLES = {
    "project",
    "source",
    "source_unit",
    "run",
    "run_source",
    "stage_result",
    "draft",
    "claim",
    "claim_evidence",
    "audit_finding",
    "llm_call",
    "export",
    "review_event",
    "discovery",
    "discovery_source",
    "discovery_candidate",
}
HEAD = "0008"


def _tables(url):
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_vendored_procrastinate_schema_matches_the_installed_package():
    vendored = MIGRATIONS_DIR / "versions" / "0001_procrastinate_3_10_0.sql"
    assert vendored.read_text(encoding="utf-8") == SchemaManager.get_schema(), (
        "the installed procrastinate's schema differs from the one revision 0001 installs: "
        "add a new Alembic revision that applies procrastinate's migration SQL"
    )


def test_upgrade_creates_our_tables_and_the_job_queue(pg_url):
    tables = _tables(pg_url)
    assert tables >= OUR_TABLES
    assert set(PROCRASTINATE_TABLES) <= tables
    assert set(Base.metadata.tables) == OUR_TABLES


def test_migration_state_is_current(pg_url):
    state = migration_state(pg_url)
    assert state.current == state.head == HEAD
    assert state.up_to_date


def test_the_orphan_sweep_indexes_exist(pg_url):
    engine = create_engine(to_sqlalchemy_url(pg_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            names = set(
                conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'procrastinate_jobs'")
                ).scalars()
            )
    finally:
        engine.dispose()
    assert {"ix_procrastinate_jobs_run_id", "ix_procrastinate_jobs_discovery_id"} <= names


def _run_indexes(conn) -> dict[str, str]:
    return dict(
        conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'run'")
        ).all()
    )


def test_the_run_indexes(pg_url):
    """At head `run` has no single-column project index: `ix_run_project_created` serves every
    lookup by project (CRL-58, R-M17-20)."""
    engine = create_engine(to_sqlalchemy_url(pg_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            names = set(_run_indexes(conn))
    finally:
        engine.dispose()
    assert names == {"run_pkey", "ix_run_state", "ix_run_project_created"}


def test_downgrade_then_upgrade_again(pg_admin):
    url = create_test_database(pg_admin)
    try:
        empty = migration_state(url)
        assert empty.current is None and not empty.up_to_date
        upgrade(url)
        downgrade(url)
        assert not (_tables(url) & (OUR_TABLES | set(PROCRASTINATE_TABLES)))
        upgrade(url)
        assert migration_state(url).up_to_date
    finally:
        drop_test_database(pg_admin, url)


def test_models_match_the_migrations(pg_url):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    engine = create_engine(to_sqlalchemy_url(pg_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_name": lambda name, type_, _: (
                        type_ != "table" or name in Base.metadata.tables
                    ),
                },
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


async def test_deleting_a_project_cascades(db):
    import uuid

    from sqlalchemy import select

    from corelata.store.models import (
        AuditFindingRow,
        DraftRow,
        LLMCall,
        Project,
        Run,
        RunSource,
        SourceRow,
        SourceUnitRow,
        StageResultRow,
    )
    from corelata.store.models import utcnow as now

    async with db.session() as s, s.begin():
        project = Project(name="p")
        s.add(project)
        await s.flush()
        src = SourceRow(
            project_id=project.id,
            kind="file",
            name="a.txt",
            format="txt",
            sha256="x",
            storage_key="k",
            provenance={},
        )
        s.add(src)
        await s.flush()
        s.add(
            SourceUnitRow(
                source_id=src.id,
                ordinal=1,
                unit_id="u1",
                text="t",
                locator="para 1",
                kind="paragraph",
                meta={},
            )
        )
        run = Run(
            project_id=project.id,
            value_statement="v",
            max_iterations=2,
            config_hash="h",
            config_snapshot={},
            pack_name="icd203-base",
            pack_hash="ph",
            pack_snapshot={},
            prompt_versions={},
            corelata_version="0.1.0",
        )
        s.add(run)
        await s.flush()
        s.add(RunSource(run_id=run.id, ordinal=1, source_id=src.id))
        s.add(
            StageResultRow(
                run_id=run.id,
                ordinal=0,
                stage="ingesting",
                iteration=0,
                ok=True,
                started_at=now(),
                finished_at=now(),
            )
        )
        s.add(DraftRow(run_id=run.id, ordinal=0, role="writer", iteration=0, report={}))
        s.add(
            AuditFindingRow(
                run_id=run.id,
                ordinal=0,
                iteration=0,
                rule_id="r",
                verdict="pass",
                severity="minor",
                route_to="writer",
                evidence="e",
            )
        )
        s.add(
            LLMCall(
                run_id=run.id,
                ordinal=0,
                stage="gating",
                role="gate",
                backend="b",
                model="m",
                prompt_id="gate",
                prompt_version=1,
                attempt=1,
                ok=True,
                latency_ms=1,
            )
        )
    async with db.session() as s, s.begin():
        await s.delete(await s.get(Project, project.id))
    async with db.session() as s:
        for model in (
            SourceRow,
            SourceUnitRow,
            Run,
            RunSource,
            StageResultRow,
            DraftRow,
            AuditFindingRow,
            LLMCall,
        ):
            assert (await s.scalars(select(model))).all() == []
    assert uuid.UUID(str(project.id))  # ids are UUIDs


def test_connect_error_is_a_database_unavailable_config_error():
    from corelata.config import ConfigError
    from corelata.store.migrate import DatabaseUnavailable, connect_error

    error = connect_error("postgresql://u:p@h/d", Exception("x"))
    assert isinstance(error, DatabaseUnavailable) and isinstance(error, ConfigError)
    assert "p@" not in str(error)


# A run row as revision 0003 has it (no review_state); every NOT NULL column is given.
_RUN_AT_0003 = (
    "INSERT INTO run (id, project_id, state, value_statement, extra_guidance, max_iterations, "
    "iteration, config_hash, config_snapshot, pack_name, pack_hash, pack_snapshot, "
    "prompt_versions, corelata_version, digests, cancel_requested, attempts, created_at) "
    "VALUES (:id, :project, 'completed', 'v', '', 2, 1, 'h', '{}', 'icd203-base', 'ph', '{}', "
    "'{}', '0.1.0', '[]', false, 1, :at)"
)
_EVENT = (
    "INSERT INTO review_event (run_id, action, note, actor, child_run_id, at) "
    "VALUES (:run, :action, '', :actor, :child, :at)"
)


def test_0004_backfills_review_state_from_the_review_events(pg_admin):
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0003")
        project = uuid.uuid4()
        ids = {k: uuid.uuid4() for k in ("accepted", "returned", "placeholder", "none", "child")}
        t = [datetime(2026, 10, 15, 10, minute, tzinfo=UTC) for minute in range(4)]
        events = [
            ("accepted", "accept", "alice", None, t[0]),
            ("accepted", "accept", "bob", None, t[1]),  # the latest accept wins
            ("returned", "accept", "alice", None, t[0]),
            ("returned", "return", "carol", ids["child"], t[2]),
            ("returned", "accept", "dave", None, t[3]),  # a later accept does not undo a return
            ("placeholder", "return", "erin", None, t[1]),  # its rerun was never linked
        ]
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": t[0]},
            )
            for run_id in ids.values():
                conn.execute(text(_RUN_AT_0003), {"id": run_id, "project": project, "at": t[0]})
            for run, action, actor, child, at in events:
                conn.execute(
                    text(_EVENT),
                    {"run": ids[run], "action": action, "actor": actor, "child": child, "at": at},
                )
        upgrade(url, "0004")
        with engine.connect() as conn:
            stored = dict(conn.execute(text("SELECT id, review_state FROM run")).all())
        assert ReviewState.model_validate(stored[ids["accepted"]]) == ReviewState(
            decision="accepted", at=t[1], actor="bob"
        )
        assert ReviewState.model_validate(stored[ids["returned"]]) == ReviewState(
            decision="returned", at=t[2], actor="carol", child_run_id=str(ids["child"])
        )
        assert ReviewState.model_validate(stored[ids["placeholder"]]) == ReviewState(
            decision="returned", at=t[1], actor="erin"
        )
        assert stored[ids["none"]] is None and stored[ids["child"]] is None
        downgrade(url, "0003")
        assert "review_state" not in {c["name"] for c in inspect(engine).get_columns("run")}
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)


# A review event with its note, which revision 0005 keeps in the stored decision.
_NOTED_EVENT = (
    "INSERT INTO review_event (run_id, action, note, actor, child_run_id, at) "
    "VALUES (:run, :action, :note, :actor, :child, :at)"
)


def test_0005_drops_unlinked_returns_and_records_each_reruns_fate(pg_admin):
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0004")
        project = uuid.uuid4()
        ids = {
            k: uuid.uuid4()
            for k in ("failed", "placeholder", "orphan", "live", "after", "done", "gate")
        }
        kids = {k: uuid.uuid4() for k in ("failed", "live", "after", "done", "gate")}
        t = [datetime(2026, 10, 18, 9, minute, tzinfo=UTC) for minute in range(3)]
        ends = {
            "failed": ("failed", "boom"),
            "live": ("drafting", None),
            "after": ("cancelled", None),
            "done": ("completed", None),
            "gate": ("gate_rejected", None),
        }
        events = [
            ("failed", "return", "first", "ana", kids["failed"], t[1]),
            ("placeholder", "accept", "", "ana", None, t[0]),
            ("placeholder", "return", "lost", "bob", None, t[1]),  # never linked: deleted
            ("orphan", "return", "lost", "bob", None, t[1]),  # never linked: deleted
            ("live", "return", "go", "carol", kids["live"], t[1]),
            ("after", "return", "x", "dave", kids["after"], t[1]),
            ("after", "accept", "", "erin", None, t[2]),  # an accept after a cancelled rerun
            ("done", "return", "fine", "fay", kids["done"], t[0]),
            ("done", "accept", "", "gus", None, t[2]),  # a completed rerun: the return still wins
            ("gate", "return", "stop", "hal", kids["gate"], t[1]),  # freed, nothing after it
        ]
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": t[0]},
            )
            for run_id in [*ids.values(), *kids.values()]:
                conn.execute(text(_RUN_AT_0003), {"id": run_id, "project": project, "at": t[0]})
            for name, (state, error) in ends.items():
                conn.execute(
                    text("UPDATE run SET state = :state, error = :error WHERE id = :id"),
                    {"id": kids[name], "state": state, "error": error},
                )
            for run, action, note, actor, child, at in events:
                row = {"run": ids[run], "action": action, "note": note, "actor": actor}
                conn.execute(text(_NOTED_EVENT), {**row, "child": child, "at": at})
            conn.execute(
                text("UPDATE run SET review_state = CAST(:stale AS jsonb) WHERE id = :id"),
                {
                    "stale": '{"decision": "returned", "at": "2026-10-18T09:01:00Z"}',
                    "id": ids["orphan"],
                },
            )
        upgrade(url, "0005")
        with engine.connect() as conn:
            stored = dict(conn.execute(text("SELECT id, review_state FROM run")).all())
            left = conn.execute(text("SELECT count(*) FROM review_event")).scalar_one()
        assert left == len(events) - 2
        assert ReviewState.model_validate(stored[ids["failed"]]) == ReviewState(
            decision="returned",
            at=t[1],
            actor="ana",
            child_run_id=str(kids["failed"]),
            child_state="failed",
            child_error="boom",
            note="first",
        )
        assert ReviewState.model_validate(stored[ids["placeholder"]]) == ReviewState(
            decision="accepted", at=t[0], actor="ana"
        )
        assert stored[ids["orphan"]] is None  # its only event was the unlinked return
        assert ReviewState.model_validate(stored[ids["live"]]) == ReviewState(
            decision="returned", at=t[1], actor="carol", child_run_id=str(kids["live"]), note="go"
        )
        assert ReviewState.model_validate(stored[ids["after"]]) == ReviewState(
            decision="accepted", at=t[2], actor="erin"
        )
        assert ReviewState.model_validate(stored[ids["done"]]) == ReviewState(
            decision="returned",
            at=t[0],
            actor="fay",
            child_run_id=str(kids["done"]),
            child_state="completed",
            note="fine",
        )
        assert ReviewState.model_validate(stored[ids["gate"]]) == ReviewState(
            decision="returned",
            at=t[1],
            actor="hal",
            child_run_id=str(kids["gate"]),
            child_state="gate_rejected",
            note="stop",
        )
        assert all(stored[k] is None for k in kids.values())  # nobody reviewed the reruns
        downgrade(url, "0004")  # the data stays
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM review_event")).scalar_one() == left
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)


_RUN_INDEX = text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_run_project_created'")
_FIRST_PAGE = text(
    "EXPLAIN (FORMAT JSON) SELECT * FROM run WHERE project_id = :project "
    "ORDER BY created_at DESC, id DESC LIMIT 101"
)


def _plan_nodes(plan: dict) -> list[str]:
    nodes = [f"{plan['Node Type']}:{plan.get('Index Name', '')}"]
    for child in plan.get("Plans", []):
        nodes += _plan_nodes(child)
    return nodes


def test_0006_adds_the_run_list_index_to_a_0005_database_and_the_downgrade_drops_it(pg_admin):
    """A 0.1.5 database (head 0005) with runs in it: the upgrade adds the index the run list
    reads by, the page query uses it, and the downgrade removes it again (CRL-39, R-M17-5)."""
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0005")
        project = uuid.uuid4()
        at = datetime(2026, 10, 19, 9, tzinfo=UTC)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": at},
            )
            for _ in range(3):
                conn.execute(text(_RUN_AT_0003), {"id": uuid.uuid4(), "project": project, "at": at})
            assert conn.execute(_RUN_INDEX).scalar() is None
        upgrade(url, "0006")
        with engine.begin() as conn:
            assert conn.execute(_RUN_INDEX).scalar_one() == (
                "CREATE INDEX ix_run_project_created ON public.run USING btree "
                "(project_id, created_at DESC, id DESC)"
            )
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
            conn.execute(text("SET LOCAL enable_seqscan = off"))  # three rows: force the choice
            conn.execute(text("SET LOCAL enable_bitmapscan = off"))
            [[explained]] = conn.execute(_FIRST_PAGE, {"project": project}).all()
            nodes = _plan_nodes(explained[0]["Plan"])
            assert "Index Scan:ix_run_project_created" in nodes
            assert not any(n.startswith("Sort:") for n in nodes)  # no sort: the index's order
        downgrade(url, "0005")
        with engine.connect() as conn:
            assert conn.execute(_RUN_INDEX).scalar() is None
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)


_PROJECT_INDEX = "CREATE INDEX ix_run_project_id ON public.run USING btree (project_id)"


def test_0007_drops_the_project_index_from_a_0006_database_and_the_downgrade_restores_it(
    pg_admin,
):
    """A 0006 database with runs in it: the upgrade drops `ix_run_project_id`, which
    `ix_run_project_created` covers, keeps the runs and the run list's index, and the downgrade
    recreates the dropped index as 0002 made it (CRL-58)."""
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0006")
        project = uuid.uuid4()
        at = datetime(2026, 11, 9, 9, tzinfo=UTC)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": at},
            )
            for _ in range(3):
                conn.execute(text(_RUN_AT_0003), {"id": uuid.uuid4(), "project": project, "at": at})
            assert _run_indexes(conn)["ix_run_project_id"] == _PROJECT_INDEX
        upgrade(url, "0007")
        with engine.connect() as conn:
            indexes = _run_indexes(conn)
            assert "ix_run_project_id" not in indexes
            assert "ix_run_project_created" in indexes
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
        downgrade(url, "0006")
        with engine.connect() as conn:
            assert _run_indexes(conn)["ix_run_project_id"] == _PROJECT_INDEX
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)


def _run_columns(conn) -> dict[str, str]:
    rows = conn.execute(
        text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'run'"
        )
    )
    return {name: nullable for name, nullable in rows}


def test_0008_adds_a_nullable_prior_reports_column_and_the_downgrade_drops_it(pg_admin):
    """A 0007 database with runs in it: the upgrade adds `run.prior_reports` (CRL-97), NULL on
    every existing run, and keeps the runs; the downgrade drops the column."""
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0007")
        project = uuid.uuid4()
        at = datetime(2026, 11, 17, 9, tzinfo=UTC)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": at},
            )
            conn.execute(text(_RUN_AT_0003), {"id": uuid.uuid4(), "project": project, "at": at})
            assert "prior_reports" not in _run_columns(conn)
        upgrade(url, "0008")
        with engine.connect() as conn:
            assert _run_columns(conn)["prior_reports"] == "YES"
            assert conn.execute(text("SELECT prior_reports FROM run")).scalar_one() is None
        downgrade(url, "0007")
        with engine.connect() as conn:
            assert "prior_reports" not in _run_columns(conn)
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)
