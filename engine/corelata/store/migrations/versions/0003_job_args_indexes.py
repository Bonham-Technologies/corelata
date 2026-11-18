"""expression indexes for the orphan sweep (CRL-10)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 12:00:00.000000

The sweep matches procrastinate_jobs.args->>'run_id' and ->>'discovery_id' against run and
discovery ids every minute; without an index that is a scan of the job table per candidate row.
procrastinate's own schema (revision 0001) is never edited; these indexes live here and go with
this revision's downgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_procrastinate_jobs_run_id ON procrastinate_jobs ((args->>'run_id'))"
    )
    op.execute(
        "CREATE INDEX ix_procrastinate_jobs_discovery_id "
        "ON procrastinate_jobs ((args->>'discovery_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_procrastinate_jobs_discovery_id")
    op.execute("DROP INDEX IF EXISTS ix_procrastinate_jobs_run_id")
