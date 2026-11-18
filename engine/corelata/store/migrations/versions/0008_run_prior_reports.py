"""run.prior_reports: the earlier accepted reports a run was given (CRL-97)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17 10:00:00.000000

A run reads the key judgments of its project's newest accepted reports (`pipeline.prior_judgments`)
and its trace records which, with those the token budget left out (`RunRecord.prior_reports`).
One nullable JSONB column, added without a default: a run made before this revision has NULL,
read as none. Adding a nullable column without a default rewrites nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("prior_reports", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run", "prior_reports")
