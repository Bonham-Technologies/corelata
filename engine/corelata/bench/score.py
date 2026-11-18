"""From a scenario and the record a real model produced to a `RunResult` (pure functions)."""

from corelata.bench.schema import (
    BenchSummary,
    GateResult,
    Rate,
    RuleTally,
    RunResult,
    ScenarioResult,
)
from corelata.scenarios import (
    Scenario,
    ScenarioExpect,
    audited_iterations,
    compare,
    delivered_unaudited,
    failed_rules,
    meets,
)
from corelata.schema import RunRecord, RunState


def _gate_agree(scenario: Scenario, record: RunRecord) -> bool | None:
    e = scenario.expect
    if not e.expects_gate():
        return None
    if record.gate is None:
        return False
    return meets(e.gate_supported, e.gate_supported_in, record.gate.supported) and meets(
        e.substance, e.substance_in, record.gate.substance
    )


def _tally(tallies: dict[str, RuleTally], rule_id: str) -> RuleTally:
    return tallies.setdefault(rule_id, RuleTally())


def _per_iteration_agree(
    expected_by_iteration: dict[int, list[str]], record: RunRecord, tallies: dict[str, RuleTally]
) -> bool:
    audited = audited_iterations(record)
    agree = True
    for iteration, expected in sorted(expected_by_iteration.items()):
        if iteration not in audited:
            agree = False
            for rule_id in expected:
                tally = _tally(tallies, rule_id)
                tally.expected += 1
                tally.missed += 1
            continue
        actual = failed_rules(record, iteration)
        if actual != set(expected):
            agree = False
        for rule_id in expected:
            tally = _tally(tallies, rule_id)
            tally.expected += 1
            if rule_id in actual:
                tally.hit += 1
            else:
                tally.missed += 1
        for rule_id in sorted(actual - set(expected)):
            _tally(tallies, rule_id).unexpected += 1
    return agree


def _rule_sets_agree(
    e: ScenarioExpect, record: RunRecord, tallies: dict[str, RuleTally]
) -> bool | None:
    """R-M12-5. Each `rules_must_fail` rule is expected once per run, a hit when it failed in
    any audited iteration. A failure in the last audited iteration is unexpected when the rule
    must pass, or when `rules_may_fail` closes the set and does not list it. A run that ended
    before any audit (gate rejected, failed) is not scored here; its state is."""
    audited = audited_iterations(record)
    if not audited and record.state is not RunState.COMPLETED:
        return None
    degraded = delivered_unaudited(record, audited)  # R-M12-10: no verdict on the report
    last = failed_rules(record, max(audited)) if audited and not degraded else set()
    ever = set().union(*(failed_rules(record, it) for it in audited))
    agree = bool(audited) and not degraded
    for rule_id in e.rules_must_fail:
        tally = _tally(tallies, rule_id)
        tally.expected += 1
        if rule_id in ever:
            tally.hit += 1
        else:
            tally.missed += 1
            agree = False
    tolerated = (set(e.rules_must_fail) | set(e.rules_may_fail or [])) - set(e.rules_must_pass)
    for rule_id in sorted(last - tolerated):  # empty when the delivered audit degraded
        if rule_id in e.rules_must_pass or e.rules_may_fail is not None:
            _tally(tallies, rule_id).unexpected += 1
            agree = False
    return agree


def _rules_agree(
    scenario: Scenario, record: RunRecord, tallies: dict[str, RuleTally]
) -> bool | None:
    e = scenario.expect
    if e.failing_rules:
        return _per_iteration_agree(e.failing_rules, record, tallies)
    if e.rule_sets():
        return _rule_sets_agree(e, record, tallies)
    return None


def _state_agree(scenario: Scenario, record: RunRecord) -> bool:
    e = scenario.expect
    delivered = record.report is not None
    return (
        meets(e.state, e.state_in, record.state)
        and (e.status is None or record.status == e.status)
        and (e.status_in is None or not delivered or record.status in e.status_in)
        and (e.iterations is None or record.iterations == e.iterations)
        and (e.iterations_max is None or record.iterations <= e.iterations_max)
    )


def score_run(
    scenario: Scenario,
    record: RunRecord,
    *,
    repeat: int,
    duration_s: float,
    tallies: dict[str, RuleTally],
) -> RunResult:
    """Score one record; `tallies` is updated in place with this run's rule outcomes."""
    return RunResult(
        repeat=repeat,
        ok=True,
        state=record.state,
        status=record.status,
        iterations=record.iterations,
        gate=None
        if record.gate is None
        else GateResult(
            supported=record.gate.supported,
            substance=record.gate.substance,
            reasons=list(record.gate.reasons),
        ),
        duration_s=duration_s,
        calls=record.usage.calls,
        tokens_in=record.usage.tokens_in,
        tokens_out=record.usage.tokens_out,
        mismatches=compare(scenario, record),
        gate_agree=_gate_agree(scenario, record),
        rules_agree=_rules_agree(scenario, record, tallies),
        state_agree=_state_agree(scenario, record),
    )


def error_result(*, repeat: int, error: str, duration_s: float) -> RunResult:
    """A run that raised before producing a record (a missing profile, a broken pack)."""
    return RunResult(repeat=repeat, ok=False, error=error, duration_s=duration_s)


def summarize(results: list[ScenarioResult], *, duration_s: float) -> BenchSummary:
    full, gate, rules, state = Rate(), Rate(), Rate(), Rate()
    runs = errors = tokens_in = tokens_out = 0
    for scenario in results:
        for run in scenario.runs:
            runs += 1
            tokens_in += run.tokens_in
            tokens_out += run.tokens_out
            full.add(run.agree)  # an errored run is a disagreement here, and counted below
            if not run.ok:
                errors += 1
                continue
            gate.add(run.gate_agree)
            rules.add(run.rules_agree)
            state.add(run.state_agree)
    return BenchSummary(
        scenarios=len(results),
        runs=runs,
        errors=errors,
        full_agreement=full,
        gate_agreement=gate,
        rule_agreement=rules,
        state_agreement=state,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_s=duration_s,
    )
