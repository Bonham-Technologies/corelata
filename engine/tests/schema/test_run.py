from datetime import UTC, datetime

from corelata.schema import TERMINAL_STATES, RunRecord, RunState, Usage


def test_run_record_minimal():
    rec = RunRecord(
        corelata_version="0.1.0",
        run_id="abc",
        created_at=datetime.now(UTC),
        value_statement="v",
        pack_name="icd203-base",
        pack_hash="h",
        pack_snapshot={},
        config_hash="c",
        prompt_versions={},
        max_iterations=2,
        usage=Usage(calls=0, tokens_in=0, tokens_out=0, by_role={}),
    )
    assert rec.state is RunState.CREATED and rec.report is None and rec.iterations == 0
    assert RunState.COMPLETED in TERMINAL_STATES and RunState.AUDITING not in TERMINAL_STATES
