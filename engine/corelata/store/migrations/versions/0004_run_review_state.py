"""run.review_state: the review decision, stored once (CRL-17)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 13:00:00.000000

`RunProgress.review` was derived from review_event on every progress read. The decision now lives
on the run row, written by `service.review_run` with each event; review_event stays the audit
trail. The backfill applies `service._review_state`'s rule, written out here so this revision
never imports the service: a return wins (even a placeholder whose rerun was never linked), else
the latest accept. `at` is written as pydantic writes it (`...Z`).
"""

import json
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _iso(at: Any) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decision(events: list[Any]) -> dict[str, Any]:
    """`events`: one run's (action, actor, child_run_id, at) rows, oldest first."""
    returned = next((e for e in events if e.action == "return"), None)
    if returned is not None:
        child = str(returned.child_run_id) if returned.child_run_id else None
        return {
            "decision": "returned",
            "at": _iso(returned.at),
            "actor": returned.actor,
            "child_run_id": child,
        }
    latest = events[-1]  # no return, so every event is an accept
    return {
        "decision": "accepted",
        "at": _iso(latest.at),
        "actor": latest.actor,
        "child_run_id": None,
    }


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("review_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT run_id, action, actor, child_run_id, at FROM review_event "
            "ORDER BY run_id, at, id"
        )
    ).all()
    by_run: dict[Any, list[Any]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)
    store = sa.text("UPDATE run SET review_state = CAST(:state AS jsonb) WHERE id = :id")
    for run_id, events in by_run.items():
        bind.execute(store, {"id": run_id, "state": json.dumps(_decision(events))})


def downgrade() -> None:
    op.drop_column("run", "review_state")
