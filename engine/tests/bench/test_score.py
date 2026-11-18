from corelata.bench import SCENARIOS_DIR
from corelata.bench.schema import GateResult, Rate, RuleTally, RunResult, ScenarioResult
from corelata.bench.score import error_result, score_run, summarize
from corelata.llm.agent import CallLog
from corelata.llm.payload import parse_input
from corelata.llm.types import ChatResponse
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import Scenario, audited_iterations, load_scenario, run_scenario
from corelata.testing.fake_backend import FakeBackend


async def _record(name, make_config):
    scenario = load_scenario(SCENARIOS_DIR / f"{name}.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    return scenario, record


def test_rate_counts_only_decided_cases():
    rate = Rate()
    rate.add(None)
    assert rate.total == 0 and rate.ratio is None
    rate.add(True)
    rate.add(False)
    rate.add(True)
    assert (rate.agree, rate.total, rate.ratio) == (2, 3, 0.6667)
    assert rate.model_dump()["ratio"] == 0.6667


async def test_a_matching_run_agrees_everywhere(make_config):
    scenario, record = await _record("badterm-fixed-one-loop", make_config)
    tallies: dict[str, RuleTally] = {}
    result = score_run(scenario, record, repeat=1, duration_s=1.5, tallies=tallies)
    assert result.ok and result.agree and result.mismatches == []
    assert result.state == "completed" and result.status == "clean" and result.iterations == 1
    assert (result.gate_agree, result.rules_agree, result.state_agree) == (None, True, True)
    assert result.calls == record.usage.calls and result.tokens_in == record.usage.tokens_in
    assert result.duration_s == 1.5
    assert tallies["icd203.tc.2"] == RuleTally(expected=1, hit=1, missed=0, unexpected=0)
    assert tallies["icd203.as.5"] == RuleTally(expected=1, hit=1, missed=0, unexpected=0)


async def test_gate_agreement_is_scored_when_expected(make_config):
    scenario, record = await _record("gate-rejected", make_config)
    result = score_run(scenario, record, repeat=1, duration_s=0, tallies={})
    assert result.gate_agree is True and result.rules_agree is None
    wrong = scenario.model_copy(
        update={"expect": scenario.expect.model_copy(update={"gate_supported": True})}
    )
    result = score_run(wrong, record, repeat=1, duration_s=0, tallies={})
    assert result.gate_agree is False and not result.agree
    assert any(m.startswith("gate.supported") for m in result.mismatches)


async def test_rule_tallies_record_misses_and_unexpected_failures(make_config):
    scenario, record = await _record("badterm-fixed-one-loop", make_config)
    wrong = scenario.model_copy(
        update={
            "expect": scenario.expect.model_copy(
                update={
                    "failing_rules": {0: ["icd203.tc.2", "icd203.tc.8"], 1: [], 3: ["icd203.tc.1"]}
                }
            )
        }
    )
    tallies: dict[str, RuleTally] = {}
    result = score_run(wrong, record, repeat=2, duration_s=0, tallies=tallies)
    assert result.repeat == 2 and result.rules_agree is False
    assert tallies["icd203.tc.2"] == RuleTally(expected=1, hit=1)
    assert tallies["icd203.tc.8"] == RuleTally(expected=1, missed=1)  # expected, did not fail
    assert tallies["icd203.as.5"] == RuleTally(unexpected=1)  # failed, not expected
    assert tallies["icd203.tc.1"] == RuleTally(expected=1, missed=1)  # iteration 3 never audited


async def test_state_agreement_covers_status_and_iterations(make_config):
    scenario, record = await _record("clean-single-source", make_config)
    wrong = scenario.model_copy(
        update={"expect": scenario.expect.model_copy(update={"iterations": 2})}
    )
    assert score_run(wrong, record, repeat=1, duration_s=0, tallies={}).state_agree is False
    assert score_run(scenario, record, repeat=1, duration_s=0, tallies={}).state_agree is True


def test_error_result_and_summary():
    err = error_result(repeat=1, error="PackError: profile 'x' not found", duration_s=0.2)
    assert not err.ok and not err.agree and err.state is None and err.mismatches == []
    good = RunResult(
        repeat=1,
        ok=True,
        state="completed",
        gate_agree=True,
        rules_agree=True,
        state_agree=True,
        calls=4,
        tokens_in=40,
        tokens_out=20,
        duration_s=1,
    )
    bad = RunResult(
        repeat=2,
        ok=True,
        state="completed",
        mismatches=["status: x"],
        gate_agree=True,
        rules_agree=False,
        state_agree=False,
        duration_s=1,
    )
    summary = summarize(
        [
            ScenarioResult(name="a", description="", runs=[good, bad]),
            ScenarioResult(name="b", description="", runs=[err]),
        ],
        duration_s=2.5,
    )
    assert summary.scenarios == 2 and summary.runs == 3 and summary.errors == 1
    assert (summary.full_agreement.agree, summary.full_agreement.total) == (1, 3)
    assert (summary.gate_agreement.agree, summary.gate_agreement.total) == (2, 2)
    assert (summary.rule_agreement.agree, summary.rule_agreement.total) == (1, 2)
    assert (summary.state_agreement.agree, summary.state_agreement.total) == (1, 2)
    assert summary.tokens_in == 40 and summary.tokens_out == 20 and summary.duration_s == 2.5


async def test_missing_gate_disagrees_when_the_scenario_expects_one(make_config):
    scenario, record = await _record("gate-rejected", make_config)
    no_gate = record.model_copy(update={"gate": None})
    assert score_run(scenario, no_gate, repeat=1, duration_s=0, tallies={}).gate_agree is False


def _expecting(base: Scenario, **expect) -> Scenario:
    data = base.model_dump(mode="json", exclude={"expect"})
    return Scenario.model_validate({**data, "expect": expect})


def _score(scenario, record, tallies=None):
    tallies = {} if tallies is None else tallies
    return score_run(scenario, record, repeat=1, duration_s=0, tallies=tallies)


async def test_gate_and_state_ranges_are_scored(make_config):
    rejected, record = await _record("gate-rejected", make_config)
    ok = _expecting(
        rejected,
        state="gate_rejected",
        gate_supported_in=[False],
        substance_in=["insufficient", "thin"],
    )
    assert _score(ok, record).gate_agree is True
    thin_only = _expecting(rejected, state="gate_rejected", substance_in=["thin"])
    assert _score(thin_only, record).gate_agree is False
    # no report: status_in is not read
    loose = _expecting(
        rejected, state_in=["completed", "gate_rejected"], status_in=["clean"], iterations_max=0
    )
    assert _score(loose, record).state_agree is True
    assert _score(_expecting(rejected, state_in=["completed"]), record).state_agree is False
    unfixable, rec = await _record("unsourced-unfixable", make_config)

    def state_agree(**expect):
        return _score(_expecting(unfixable, state="completed", **expect), rec).state_agree

    assert state_agree(iterations_max=1) is False
    assert state_agree(status_in=["clean"]) is False
    assert state_agree(iterations_max=2) is True


async def test_rule_sets_tally_must_fail_as_expected_and_untolerated_failures_as_unexpected(
    make_config,
):
    unfixable, record = await _record("unsourced-unfixable", make_config)
    scenario = _expecting(
        unfixable,
        state="completed",
        rules_must_fail=["icd203.tc.8", "icd203.tc.2"],
        rules_may_fail=["icd203.as.5"],
    )
    tallies: dict[str, RuleTally] = {}
    assert _score(scenario, record, tallies).rules_agree is False
    assert tallies == {
        "icd203.tc.8": RuleTally(expected=1, hit=1),
        "icd203.tc.2": RuleTally(expected=1, missed=1),
        "icd206.src.2": RuleTally(unexpected=1),  # failed at the end, not tolerated
    }
    open_set = _expecting(unfixable, state="completed", rules_must_pass=["icd206.src.2"])
    tallies = {}
    assert _score(open_set, record, tallies).rules_agree is False  # a must-pass rule failed
    assert tallies == {"icd206.src.2": RuleTally(unexpected=1)}  # others are left free


async def test_a_rule_fixed_in_a_revision_meets_must_fail_and_must_pass(make_config):
    fixed, record = await _record("unsourced-fixed-one-loop", make_config)
    scenario = _expecting(
        fixed,
        state="completed",
        rules_must_fail=["icd203.tc.8"],
        rules_must_pass=["icd203.tc.8", "icd206.src.2"],
        rules_may_fail=[],
    )
    tallies: dict[str, RuleTally] = {}
    result = _score(scenario, record, tallies)
    assert result.rules_agree is True and result.agree
    assert tallies == {"icd203.tc.8": RuleTally(expected=1, hit=1)}


async def test_a_degraded_audit_scores_as_missed_not_hit(make_config):
    backend = FakeBackend(name="fake")
    backend.script("auditor", *["this is not JSON"] * 4)
    scenario = load_scenario(SCENARIOS_DIR / "max-iterations-zero.yaml")
    record = await run_scenario(
        scenario, make_config(), backends={"fake": backend}, prompts=PromptLibrary(), log=CallLog()
    )
    tallies: dict[str, RuleTally] = {}
    assert _score(scenario, record, tallies).rules_agree is False
    # before M12 the engine's own icd203.tc.8 finding counted as a hit for an audit that never ran
    assert tallies == {
        "icd203.as.5": RuleTally(expected=1, missed=1),
        "icd203.tc.8": RuleTally(expected=1, missed=1),
        "icd206.src.2": RuleTally(expected=1, missed=1),
    }


class _AuditorFailsFromIteration1(FakeBackend):
    audits = 0

    async def chat(self, request):
        if parse_input([m.model_dump() for m in request.messages])["task"] == "auditor":
            self.audits += 1
            if self.audits > 1:
                return ChatResponse(content="this is not JSON")
        return await super().chat(request)


async def test_a_degraded_final_audit_leaves_must_pass_and_may_fail_unscored(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "unsourced-fixed-one-loop.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": _AuditorFailsFromIteration1(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.iterations == 1 and audited_iterations(record) == {0}
    must_pass = _expecting(
        scenario, state="completed", rules_must_pass=["icd203.tc.8"], rules_may_fail=[]
    )
    tallies: dict[str, RuleTally] = {}
    result = _score(must_pass, record, tallies)
    assert result.rules_agree is False and not result.agree
    assert result.mismatches == ["rules: no audit of the delivered draft (iteration 1 degraded)"]
    assert tallies == {}  # iteration 0's failure is not tallied as unexpected
    must_fail = _expecting(scenario, state="completed", rules_must_fail=["icd203.tc.8"])
    tallies = {}
    result = _score(must_fail, record, tallies)
    assert result.rules_agree is False  # a disagreement all the same
    assert tallies == {"icd203.tc.8": RuleTally(expected=1, hit=1)}  # met over audited iterations


async def test_rule_sets_are_not_scored_when_the_run_stopped_before_an_audit(make_config):
    rejected, record = await _record("gate-rejected", make_config)
    scenario = _expecting(rejected, state="gate_rejected", rules_must_pass=["icd203.tc.8"])
    result = _score(scenario, record)
    assert result.rules_agree is None and result.agree


async def test_score_run_keeps_the_gate_verdict(make_config):
    scenario, record = await _record("gate-rejected", make_config)
    result = score_run(scenario, record, repeat=1, duration_s=0, tallies={})
    assert result.gate == GateResult(
        supported=False, substance="insufficient", reasons=record.gate.reasons
    )
    assert RunResult.model_validate_json(result.model_dump_json()).gate == result.gate
    no_gate = record.model_copy(update={"gate": None})
    assert score_run(scenario, no_gate, repeat=1, duration_s=0, tallies={}).gate is None
    assert RunResult.model_validate({"repeat": 1, "ok": True}).gate is None  # older bench.json
