from datetime import UTC, datetime

from corelata.bench.schema import (
    BenchReport,
    BenchSummary,
    GateResult,
    Rate,
    RuleTally,
    RunResult,
    ScenarioResult,
)
from corelata.bench.text import GATE_REASON_CHARS, OUTCOME_WIDTH, format_bench

REASON = (
    "The terminal log shows July arrivals below June, so growth since the shuttle began is "
    "not established."
)


def _report() -> BenchReport:
    t = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    good = RunResult(
        repeat=1,
        ok=True,
        state="completed",
        status="clean",
        iterations=0,
        gate=GateResult(supported=True, substance="sufficient", reasons=["Three passages."]),
        duration_s=12.3,
        calls=4,
        tokens_in=1200,
        tokens_out=400,
        gate_agree=True,
        rules_agree=None,
        state_agree=True,
    )
    bad = RunResult(
        repeat=1,
        ok=True,
        state="completed",
        status="findings_open",
        iterations=2,
        gate=GateResult(supported=True, substance="thin", reasons=[REASON, "second reason"]),
        duration_s=40.0,
        calls=9,
        tokens_in=5000,
        tokens_out=900,
        mismatches=[
            "status: expected 'clean', got 'findings_open'",
            "failing_rules[1]: expected [], got ['icd203.tc.8']",
        ],
        gate_agree=False,
        rules_agree=False,
        state_agree=False,
    )
    err = RunResult(repeat=1, ok=False, error="RuntimeError: boom", duration_s=0.1)
    results = [
        ScenarioResult(name="clean-single-source", description="", runs=[good]),
        ScenarioResult(name="unsourced-fixed-one-loop", description="", runs=[bad]),
        ScenarioResult(name="broken", description="", runs=[err]),
    ]
    summary = BenchSummary(
        scenarios=3,
        runs=3,
        errors=1,
        full_agreement=Rate(agree=1, total=3),
        gate_agreement=Rate(agree=1, total=2),
        rule_agreement=Rate(agree=0, total=1),
        state_agreement=Rate(agree=1, total=2),
        tokens_in=6200,
        tokens_out=1300,
        duration_s=52.4,
    )
    return BenchReport(
        corelata_version="0.1.0",
        started_at=t,
        finished_at=t,
        config_hash="abc",
        repeat=1,
        models={
            "gate": "openai/gpt-4.1-mini",
            "writer": "openai/gpt-4.1-mini",
            "conveyor": "google/gemini-2.5-flash",
            "auditor": "google/gemini-2.5-flash",
        },
        scenarios_dir="/x",
        scenarios=results,
        rules={
            "icd203.tc.8": RuleTally(expected=1, hit=0, missed=0, unexpected=1),
            "icd203.tc.2": RuleTally(expected=2, hit=2),
        },
        summary=summary,
    )


def _rows(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    header = next(ln for ln in lines if ln.startswith("scenario "))
    names = ("clean-single-source", "unsourced-fixed", "broken")
    return header, [next(ln for ln in lines if ln.startswith(n)) for n in names]


def test_format_bench_lists_scenarios_summary_rules_and_mismatches():
    text = format_bench(_report())
    lines = text.splitlines()
    assert lines[0].startswith("corelata bench 0.1.0")
    assert lines[1:4] == [  # one line per model id, with the roles it serves
        "models:",
        "  openai/gpt-4.1-mini      gate, writer",
        "  google/gemini-2.5-flash  conveyor, auditor",
    ]
    header, table = _rows(text)
    assert "  agree  outcome" in header and "agree outcome" not in header
    assert table[0].split()[2] == "yes" and table[1].split()[2] == "no"
    assert table[2].split()[2] == "err" and "RuntimeError: boom" in table[2]
    assert "completed clean" in table[0] and "12.3s" in table[0]
    assert "findings_open" in table[1]
    assert "full agreement 1/3 (33%)" in text
    assert "gate agreement 1/2 (50%)" in text
    assert "rule-failure agreement 0/1 (0%)" in text
    assert "state agreement 1/2 (50%)" in text
    assert "errors 1" in text and "tokens in 6200, out 1300" in text
    assert "icd203.tc.8" in text and "unexpected 1" in text
    assert "icd203.tc.2" not in text.split("rules with misses or unexpected failures")[1]
    assert "  unsourced-fixed-one-loop run 1:" in text
    assert "    status: expected 'clean', got 'findings_open'" in text


def test_the_gate_column_shows_the_verdict_and_a_disagreeing_gates_first_reason():
    header, (good, bad, err) = _rows(format_bench(_report()))
    column = header.index("gate")
    assert good[column:].startswith("supported · sufficient")
    assert "Three passages" not in good  # the gate agreed: no reason
    assert bad[column:].startswith("supported · thin")
    assert bad.endswith("  " + REASON[: GATE_REASON_CHARS - 1] + "…")
    assert "second reason" not in bad
    assert err[column:].startswith("-")
    rejected = _report()
    run = rejected.scenarios[0].runs[0]
    run.gate = GateResult(supported=False, substance="insufficient", reasons=["short"])
    run.gate_agree = False
    _, (row, _, _) = _rows(format_bench(rejected))
    assert row[column:].startswith("rejected · insufficient") and row.endswith("  short")


def test_an_errored_runs_long_error_keeps_every_column_aligned():
    report = _report()
    error = "PermanentBackendError: " + "x" * 277
    assert len(error) == 300
    report.scenarios[2].runs[0].error = error
    text = format_bench(report)
    header, rows = _rows(text)
    starts = [header.index(h) for h in ("agree", "outcome", "gate")]  # left-aligned columns
    ends = [header.index(h) + len(h) for h in ("time", "calls", "tokens")]  # right-aligned
    for row in rows:
        for start in starts:
            assert row[start - 1] == " " and row[start] != " ", row
        for end in ends:
            assert row[end - 1] != " " and row[end : end + 1] in ("", " "), row
    err = rows[2]
    outcome = header.index("outcome")
    assert err[outcome : outcome + OUTCOME_WIDTH] == error[: OUTCOME_WIDTH - 1] + "…"
    assert len(err) == len(header)  # nothing spills past the tokens column
    assert text.endswith("\nerrors\n  broken run 1: " + error + "\n")  # whole, after the table
    assert report.scenarios[2].runs[0].error == error  # bench.json keeps the whole error
    assert error in report.model_dump_json()


def test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections():
    report = _report()
    report.scenarios = report.scenarios[:1]
    report.rules = {"icd203.tc.2": RuleTally(expected=2, hit=2)}
    report.summary = BenchSummary(
        scenarios=1,
        runs=1,
        errors=0,
        full_agreement=Rate(agree=1, total=1),
        gate_agreement=Rate(agree=1, total=1),
        rule_agreement=Rate(),
        state_agreement=Rate(agree=1, total=1),
        tokens_in=1,
        tokens_out=1,
        duration_s=1,
    )
    text = format_bench(report)
    assert "rule-failure agreement n/a" in text
    assert "rules with misses" not in text and "mismatches" not in text
    assert "\nerrors\n" not in text


def test_a_multi_line_error_is_printed_on_one_line_in_the_errors_section():
    report = _report()
    report.scenarios[2].runs[0].error = "ValueError: bad\n  at line 3\n\tdetail"
    text = format_bench(report)
    assert text.endswith("\nerrors\n  broken run 1: ValueError: bad at line 3 detail\n")
    assert report.scenarios[2].runs[0].error.count("\n") == 2  # bench.json keeps it as it was
