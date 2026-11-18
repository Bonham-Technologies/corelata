"""run list index: (project_id, created_at DESC, id DESC) (CRL-39)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 10:00:00.000000

`GET /api/runs` pages a project's runs newest first by `(created_at, id)` (R-M14-1). With only
`ix_run_project_id`, Postgres reads every run of the project and sorts them for each page; this
index matches the query's order exactly, so a page is an index scan that stops after `limit`
rows. Measured on 50,000 runs in five projects (R-M17-20): the first page went from 6.9 ms and
2,011 buffers (bitmap heap scan and top-N sort over 10,000 rows) to 0.08 ms and 25 buffers, a
keyset page 5,000 runs in from 7.5 ms to 0.09 ms. A plain CREATE INDEX: `migrate` runs before
`api` and `worker` start. The time to build the index was not measured.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_run_project_created",
        "run",
        ["project_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_run_project_created", table_name="run")
