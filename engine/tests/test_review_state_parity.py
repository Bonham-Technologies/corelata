"""Migration 0005 writes out `service._review_state`'s rule so it never imports the service
(R-M15-1, R-M15-2); a property test keeps the two copies identical for random review histories."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from corelata import service
from corelata.schema import RunState
from corelata.store.migrate import MIGRATIONS_DIR
from corelata.store.models import ReviewEvent

_PATH = MIGRATIONS_DIR / "versions" / "0005_review_state_rerun_fate.py"
_SPEC = importlib.util.spec_from_file_location("migration_0005", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_RERUNS = [uuid.UUID(int=i + 1) for i in range(4)]
_BASE = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)

# A history: events oldest first, each (action, child index or None, note, actor, seconds,
# microseconds); every rerun is in some state, or missing (a deleted run).
_event = st.tuples(
    st.sampled_from(["accept", "return"]),
    st.none() | st.integers(0, len(_RERUNS) - 1),
    st.text(max_size=8),
    st.none() | st.sampled_from(["ana", "bob"]),
    st.integers(0, 3),
    st.sampled_from([0, 0, 123456]),
)
_fate = st.none() | st.tuples(st.sampled_from(list(RunState)), st.none() | st.text(max_size=8))


@settings(max_examples=200, deadline=None)
@given(st.lists(_event, max_size=6), st.lists(_fate, min_size=len(_RERUNS), max_size=len(_RERUNS)))
def test_the_migrations_decision_equals_the_services(history, fates):
    run_id = uuid.uuid4()
    events = [
        ReviewEvent(
            run_id=run_id,
            action=action,
            note=note,
            actor=actor,
            child_run_id=None if child is None else _RERUNS[child],
            at=_BASE + timedelta(seconds=seconds, microseconds=micro),
        )
        for action, child, note, actor, seconds, micro in sorted(history, key=lambda e: e[4:])
    ]
    # The migration first deletes returns that were never linked to a rerun.
    events = [e for e in events if not (e.action == "return" and e.child_run_id is None)]
    reruns = {rid: fate for rid, fate in zip(_RERUNS, fates, strict=True) if fate is not None}
    state = service._review_state(events, reruns)
    if not events:
        assert state is None
        return
    assert state is not None
    plain = {rid: (str(s.value), error) for rid, (s, error) in reruns.items()}
    assert migration._decision(events, plain) == state.model_dump(mode="json")
