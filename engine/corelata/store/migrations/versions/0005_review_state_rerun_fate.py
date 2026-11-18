"""run.review_state: the rerun's fate (CRL-34)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 10:00:00.000000

From M15 a return is spent only while its rerun is live or completed (R-M15-1), and the stored
decision carries the rerun's terminal state, its error and the return's note (R-M15-2). A return
now commits with its rerun in one transaction (R-M15-3), so a `return` event whose rerun was never
linked can only be left over from an earlier version's interrupted return: it is deleted. Then
every reviewed run's decision is recomputed with `service._review_state`'s rule, written out here
so this revision never imports the service. Nothing in the table's shape changes; the downgrade
keeps the data (the older code ignores the new keys).
"""

import json
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERMINAL = {"completed", "gate_rejected", "failed", "cancelled"}
FREED_BY = TERMINAL - {"completed"}


def _iso(at: Any) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decision(events: list[Any], reruns: dict[Any, Any]) -> dict[str, Any]:
    """`events`: one run's (action, note, actor, child_run_id, at) rows, oldest first; `reruns`:
    (state, error) by run id."""
    live = next(
        (
            e
            for e in reversed(events)
            if e.action == "return"
            and (e.child_run_id not in reruns or reruns[e.child_run_id][0] not in FREED_BY)
        ),
        None,
    )
    chosen = live or events[-1]
    state: dict[str, Any] = {
        "decision": "accepted" if chosen.action == "accept" else "returned",
        "at": _iso(chosen.at),
        "actor": chosen.actor,
        "child_run_id": None,
        "child_state": None,
        "child_error": None,
        "note": None,
    }
    if chosen.action == "return":
        rerun = reruns.get(chosen.child_run_id)
        ended = rerun is not None and rerun[0] in TERMINAL
        state.update(
            child_run_id=str(chosen.child_run_id),
            child_state=rerun[0] if ended else None,
            child_error=rerun[1] if ended else None,
            note=chosen.note,
        )
    return state


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM review_event WHERE action = 'return' AND child_run_id IS NULL")
    )
    rows = bind.execute(
        sa.text(
            "SELECT run_id, action, note, actor, child_run_id, at FROM review_event "
            "ORDER BY run_id, at, id"
        )
    ).all()
    reruns = {
        r.id: (r.state, r.error)
        for r in bind.execute(
            sa.text(
                "SELECT id, state, error FROM run WHERE id IN "
                "(SELECT child_run_id FROM review_event WHERE child_run_id IS NOT NULL)"
            )
        ).all()
    }
    by_run: dict[Any, list[Any]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)
    bind.execute(
        sa.text(
            "UPDATE run SET review_state = NULL WHERE review_state IS NOT NULL "
            "AND id NOT IN (SELECT run_id FROM review_event)"
        )
    )
    store = sa.text("UPDATE run SET review_state = CAST(:state AS jsonb) WHERE id = :id")
    for run_id, events in by_run.items():
        bind.execute(store, {"id": run_id, "state": json.dumps(_decision(events, reruns))})


def downgrade() -> None:
    pass  # the data stays: revision 0004's code reads the keys it knows and ignores the rest
