"""procrastinate 3.12.0's job queue schema: procrastinate's 3.11 and 3.12 migrations

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24 12:00:00.000000

procrastinate 3.12 defers jobs through procrastinate_defer_jobs_v2, which only its 3.12
migrations create; revision 0001 installed procrastinate 3.10.0's schema. This revision applies
every procrastinate migration since, vendored verbatim from the package's sql/migrations/ so it
never changes: 3.11.00_01 and 3.12.00_01 to _03 ("pre": they run before 3.12 code starts) and
3.12.00_50 and _51 ("post": they drop what only 3.10 code calls, procrastinate_defer_jobs_v1,
its type procrastinate_job_to_defer_v1, procrastinate_defer_periodic_job_v2 and the (id, lock)
index). The database then matches what procrastinate 3.12.0's own schema.sql builds.

Pre and post run in this one revision because no procrastinate code runs during it: `corelata
migrate` runs before `api` and `worker` start, after the old version is stopped (operator guide,
section 10: `docker compose down` in the old directory, then `migrate` runs first in the new
one; section 5, "Applying changes": the compose file starts `api` and `worker` only once
`migrate` completed), and nothing that still calls the 3.10 functions survives it.

procrastinate builds the new lock index and drops the old one CONCURRENTLY, which cannot run
inside a transaction. Here both run as a plain CREATE INDEX and DROP INDEX, inside the migration's
transaction like every other revision: with Corelata stopped no writer waits on the table's lock,
and the revision stays atomic. A failure rolls the whole of it back, where a concurrent build
would leave an invalid index and a half-applied revision behind. The vendored files stay as
procrastinate ships them; `_in_transaction` drops the one CONCURRENTLY from each.

The downgrade puts back procrastinate 3.10.0's objects exactly as revision 0001 installed them
(0010_procrastinate_3_10_0_restore.sql) and drops every job's lock_mode, which 3.10 lacks.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HERE = Path(__file__).parent

# procrastinate's migrations since 3.10.0, in the order procrastinate applies them
_PROCRASTINATE_MIGRATIONS = (
    "03.11.00_01_pre_fetch_job_skip_null_lock",
    "03.12.00_01_pre_add_lock_mode",
    "03.12.00_02_pre_retry_job_fail_on_queueing_lock_conflict",
    "03.12.00_03_pre_add_todo_doing_lock_index",
    "03.12.00_50_post_add_lock_mode",
    "03.12.00_51_post_drop_id_lock_index",
)
_DOWNGRADE = _HERE / "0010_procrastinate_3_10_0_restore.sql"


def _vendored(name: str) -> str:
    return (_HERE / f"0010_procrastinate_{name}.sql").read_text(encoding="utf-8")


def _in_transaction(sql: str) -> str:
    """The migration's SQL with CREATE/DROP INDEX CONCURRENTLY made plain, so it can run in the
    migration's transaction (see the module docstring)."""
    return sql.replace("INDEX CONCURRENTLY", "INDEX")


def _raw(sql: str) -> None:
    # The raw psycopg connection, as in revision 0001: procrastinate's SQL contains '%' that
    # SQLAlchemy would read as placeholders. It runs inside the migration's transaction.
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    for name in _PROCRASTINATE_MIGRATIONS:
        _raw(_in_transaction(_vendored(name)))


def downgrade() -> None:
    _raw(_DOWNGRADE.read_text(encoding="utf-8"))
