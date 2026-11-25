"""source.stated and run_source.stated: what the analyst states about a source (CRL-138)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25 10:00:00.000000

An analyst may state a source's descriptor, reliability note, date of information, origin and
access; a run writes them into the report's source entry over the model's. `source.stated` holds
the current statement and `run_source.stated` the one a run was queued with, so a later edit does
not change an earlier run. Two nullable JSONB columns, added without a default: every existing
source and run has NULL, read as nothing stated. Adding a nullable column without a default
rewrites nothing. Add-only: nothing is backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source", sa.Column("stated", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "run_source", sa.Column("stated", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("run_source", "stated")
    op.drop_column("source", "stated")
