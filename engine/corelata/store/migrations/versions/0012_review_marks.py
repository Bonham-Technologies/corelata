"""review_mark and run.reviewer_findings: per-claim review marks (CRL-139)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-26 10:00:00.000000

A reviewer marks a claim of a delivered report checked or disputed, with a comment. Each mark is
a row of the new table `review_mark`, only ever added: a claim's latest row is its mark, and the
run's trace lists them all. A return hands each disputed claim to the rerun's writer as a
finding, kept on the rerun in the new nullable JSONB column `run.reviewer_findings`; every
existing run has NULL, read as none. Add-only: a new table, its index and a nullable column
without a default, so nothing is rewritten or backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_mark",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("mark", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_mark_run_id"), "review_mark", ["run_id"], unique=False)
    op.add_column(
        "run",
        sa.Column("reviewer_findings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run", "reviewer_findings")
    op.drop_index(op.f("ix_review_mark_run_id"), table_name="review_mark")
    op.drop_table("review_mark")
