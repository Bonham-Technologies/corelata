"""procrastinate job queue

Revision ID: 0001
Revises:
Create Date: 2026-10-13 12:00:00.000000

"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# procrastinate 3.10.0's schema.sql, vendored verbatim so this revision never changes. A
# procrastinate upgrade needs a new revision that applies its migration SQL
# (tests/store/test_migrations.py fails when the installed schema differs from this file).
_PROCRASTINATE_SCHEMA = Path(__file__).with_name("0001_procrastinate_3_10_0.sql")

_DROP_PROCRASTINATE = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs,
    procrastinate_workers CASCADE;
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT oid::regprocedure AS fn FROM pg_proc WHERE proname LIKE 'procrastinate%' LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.fn || ' CASCADE';
    END LOOP;
END $$;
DROP TYPE IF EXISTS procrastinate_job_status, procrastinate_job_event_type,
    procrastinate_job_to_defer_v1 CASCADE;
"""


def _raw(sql: str) -> None:
    # The raw psycopg connection: this SQL contains '%' that SQLAlchemy would read as
    # placeholders. It runs inside the migration's transaction.
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    """Install procrastinate's job queue (spec §4.1, §8.3)."""
    _raw(_PROCRASTINATE_SCHEMA.read_text(encoding="utf-8"))


def downgrade() -> None:
    """Remove the job queue."""
    _raw(_DROP_PROCRASTINATE)
