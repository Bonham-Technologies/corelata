"""drop ix_run_project_id: ix_run_project_created covers it (CRL-58)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 10:00:00.000000

`ix_run_project_created` (`project_id, created_at DESC, id DESC`, revision 0006) leads with
`project_id`, so it serves every lookup the single-column `ix_run_project_id` (revision 0002)
served: the run list's pages, the project summary's statements and the delete the project
cascade issues (R-M17-20). The old index only cost write time and space on `run`. A plain DROP
INDEX: it takes a brief ACCESS EXCLUSIVE lock on `run`, and `migrate` runs before `api` and
`worker` start; Alembic runs every revision in one transaction, where CONCURRENTLY cannot run.
The downgrade recreates the index as 0002 made it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_run_project_id", table_name="run")


def downgrade() -> None:
    op.create_index("ix_run_project_id", "run", ["project_id"], unique=False)
