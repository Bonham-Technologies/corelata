"""run.kind and run.report_source_id: check runs (CRL-94)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24 10:00:00.000000

A check run audits a finished report someone else wrote instead of writing one. `kind` says which
a run is: NOT NULL with the server default 'report', so every existing run reads as a report run;
Postgres 11 and later add a column with a constant default without rewriting the table.
`report_source_id` names the uploaded source a check run audits (NULL for a report run); a
nullable column without a default rewrites nothing either. Add-only: nothing is backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run", sa.Column("kind", sa.Text(), server_default="report", nullable=False))
    op.add_column("run", sa.Column("report_source_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "run_report_source_id_fkey",
        "run",
        "source",
        ["report_source_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("run_report_source_id_fkey", "run", type_="foreignkey")
    op.drop_column("run", "report_source_id")
    op.drop_column("run", "kind")
