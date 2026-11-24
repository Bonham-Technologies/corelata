import pytest
import yaml

from corelata.bench import REAL_SCENARIOS_DIR, SCENARIOS_DIR
from corelata.llm.agent import CallLog
from corelata.llm.payload import parse_input
from corelata.llm.types import ChatResponse
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import (
    Scenario,
    ScenarioError,
    audited_iterations,
    compare,
    load_scenario,
    load_scenarios,
    run_scenario,
    scenario_sources,
)
from corelata.schema import RunState, Verdict
from corelata.stages.audit import ENGINE_CHECK
from corelata.standards.loader import load_pack
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.sources import text_source

FIXTURES = SCENARIOS_DIR
SCENARIOS = load_scenarios(FIXTURES)


def test_fixture_directory_has_the_expected_set():
    assert [s.name for s in SCENARIOS] == [
        "badterm-fixed-one-loop",
        "clean-single-source",
        "clean-two-sources",
        "conflict-named-in-source-summary",
        "gate-rejected",
        "long-source-digested",
        "many-sources-writer-budget",
        "max-iterations-zero",
        "mixed-wording-fixed-one-loop",
        "offlexicon-fixed-one-loop",
        "quotes-fabricated-fixed-one-loop",
        "quotes-faithful-clean",
        "thin-material",
        "unsourced-fixed-one-loop",
        "unsourced-unfixable",
    ]
    assert all(s.description for s in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
async def test_scenario_passes_against_the_fake_model(scenario, make_config):
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.run_id == scenario.name
    assert compare(scenario, record) == [], "\n".join(compare(scenario, record))


def test_source_from_paragraphs_matches_text_source():
    s = scenario_sources(
        Scenario.model_validate(
            {
                "name": "x",
                "statement": "s",
                "sources": [
                    {"id": "src1", "paragraphs": ["a", "b"]},
                    {"id": "src2", "name": "n.md", "paragraphs": ["c"]},
                ],
                "expect": {"state": "completed"},
            }
        )
    )
    assert s[0] == text_source("src1", "a", "b")
    assert s[1].name == "n.md" and s[1].refs() == ["src2/u1"]


def test_load_scenario_errors_name_the_file_and_problem(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: x\nstatement: s\nsources: [{id: src1, paragraphs: [a]}]\n"
        "expect: {state: completed}\nbogus: 1\n"
    )
    with pytest.raises(ScenarioError, match=r"bad\.yaml: bogus: Extra inputs are not permitted"):
        load_scenario(bad)
    bad.write_text("name: [\n")
    with pytest.raises(ScenarioError, match=r"bad\.yaml: invalid YAML"):
        load_scenario(bad)
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ScenarioError, match=r"bad\.yaml: .*(dict|object|mapping)"):
        load_scenario(bad)
    with pytest.raises(ScenarioError, match="cannot read"):
        load_scenario(tmp_path / "missing.yaml")
    base = "name: x\nstatement: s\nsources: [{id: src1, paragraphs: [a]}]\n"
    bad.write_text(base + "pipeline: {digest_treshold_tokens: 500}\nexpect: {state: completed}\n")
    with pytest.raises(
        ScenarioError,
        match=r"bad\.yaml: pipeline\.digest_treshold_tokens: Extra inputs are not permitted",
    ):
        load_scenario(bad)
    bad.write_text(base + "pipeline: {digest_threshold_tokens: 10}\nexpect: {state: completed}\n")
    with pytest.raises(ScenarioError, match=r"bad\.yaml: pipeline\.digest_threshold_tokens: "):
        load_scenario(bad)
    assert load_scenarios(tmp_path / "empty-dir") == []


async def test_compare_reports_every_mismatch(make_config):
    scenario = load_scenario(FIXTURES / "clean-single-source.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    wrong = scenario.model_copy(
        update={
            "expect": scenario.expect.model_copy(
                update={
                    "status": "findings_open",
                    "iterations": 3,
                    "substance": "thin",
                    "failing_rules": {0: ["icd203.tc.8", "nope.rule.1"], 4: []},
                    "open_findings": ["icd203.tc.8@0"],
                    "digested": ["src1"],
                }
            )
        }
    )
    mismatches = compare(wrong, record)
    assert mismatches == [
        "status: expected 'findings_open', got 'clean'",
        "iterations: expected 3, got 0",
        "gate.substance: expected 'thin', got 'sufficient'",
        "failing_rules[0]: not in pack: nope.rule.1",
        "failing_rules[0]: expected ['icd203.tc.8', 'nope.rule.1'], got []",
        "failing_rules[4]: no audit ran for iteration 4",
        "open_findings: expected ['icd203.tc.8@0'], got []",
        "digested: expected ['src1'], got []",
    ]
    rejected = load_scenario(FIXTURES / "gate-rejected.yaml")
    rec = await run_scenario(
        rejected,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    expects_gate = rejected.model_copy(
        update={"expect": rejected.expect.model_copy(update={"gate_supported": True})}
    )
    assert compare(expects_gate, rec) == ["gate.supported: expected True, got False"]
    no_gate = rec.model_copy(update={"gate": None})
    assert compare(rejected, no_gate) == ["gate: expected a verdict, got none"]


async def test_conflicting_sources_is_scored_against_the_source_summary(make_config):
    """CRL-96: `conflicting_sources` names sources the report's source summary must list as
    conflicting; the real set asks it of conflicting-rail-figures."""
    scenario = load_scenario(FIXTURES / "conflict-named-in-source-summary.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.report is not None and record.report.source_summary is not None
    wants_both = scenario.model_copy(
        update={
            "expect": scenario.expect.model_copy(update={"conflicting_sources": ["src1", "src2"]})
        }
    )
    assert compare(wants_both, record) == [
        "conflicting_sources: not named as conflicting: src1 (named: src2)"
    ]
    quiet = record.report.source_summary.model_copy(update={"conflicting_sources": []})
    calm = record.model_copy(
        update={"report": record.report.model_copy(update={"source_summary": quiet})}
    )
    assert compare(scenario, calm) == [
        "conflicting_sources: not named as conflicting: src2 (named: none)"
    ]
    for report in (None, record.report.model_copy(update={"source_summary": None})):
        bare = record.model_copy(update={"report": report})
        assert "conflicting_sources: the report has no source summary" in compare(scenario, bare)
    [rail] = [s for s in REAL if s.name == "conflicting-rail-figures"]
    assert rail.expect.conflicting_sources == ["src1", "src2"]
    assert "icd206.src.1" in rail.expect.rules_must_pass


def test_scenario_yaml_round_trips_through_the_model():
    for s in SCENARIOS:
        data = yaml.safe_load((FIXTURES / f"{s.name}.yaml").read_text())
        assert Scenario.model_validate(data) == s


BAD = "this is not JSON"  # four of them: two stage attempts, each a first try and a repair


async def _played(name: str, make_config, backend: FakeBackend | None = None):
    scenario = load_scenario(FIXTURES / f"{name}.yaml")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": backend or FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    return scenario, record


def _expecting(base: Scenario, **expect) -> Scenario:
    """`base`'s sources and statement with another expectation, validated as a file would be."""
    data = base.model_dump(mode="json", exclude={"expect"})
    return Scenario.model_validate({**data, "expect": expect})


@pytest.mark.parametrize(
    ("expect", "message"),
    [
        ("{state: completed, state_in: [completed]}", "set state or state_in, not both"),
        ("{state: completed, status: clean, status_in: [clean]}", "set status or status_in"),
        (
            "{state: completed, iterations: 0, iterations_max: 1}",
            "set iterations or iterations_max",
        ),
        (
            "{state: completed, gate_supported: true, gate_supported_in: [true]}",
            "set gate_supported or gate_supported_in, not both",
        ),
        (
            "{state: completed, substance: thin, substance_in: [thin]}",
            "set substance or substance_in",
        ),
        ("{status: clean}", "set state or state_in"),
        (
            "{state: completed, failing_rules: {0: []}, rules_may_fail: []}",
            "set failing_rules or rules_may_fail, not both",
        ),
        (
            "{state: completed, rules_must_pass: [icd203.tc.8], rules_may_fail: [icd203.tc.8]}",
            "icd203.tc.8 in both rules_must_pass and rules_may_fail",
        ),
        ("{state_in: []}", "expect.state_in: List should have at least 1 item"),
    ],
)
def test_expectation_forms_are_validated(tmp_path, expect, message):
    path = tmp_path / "bad.yaml"
    path.write_text(
        f"name: x\nstatement: s\nsources: [{{id: src1, paragraphs: [a]}}]\nexpect: {expect}\n"
    )
    with pytest.raises(ScenarioError) as e:
        load_scenario(path)
    assert str(e.value).startswith("bad.yaml: expect") and message in str(e.value)


async def test_range_expectations_accept_any_listed_outcome(make_config):
    clean, record = await _played("clean-single-source", make_config)
    ranged = _expecting(
        clean,
        state_in=["completed", "gate_rejected"],
        status_in=["clean", "findings_open"],
        iterations_max=0,
        gate_supported_in=[True],
        substance_in=["sufficient", "thin"],
        rules_must_pass=["icd203.tc.8", "icd206.src.2"],
        rules_may_fail=[],
    )
    assert compare(ranged, record) == []
    rejected, rec = await _played("gate-rejected", make_config)
    # no report, so status_in is not read; the run ended before an audit, so the rule sets are
    # not read either
    loose = _expecting(
        rejected,
        state_in=["completed", "gate_rejected"],
        status_in=["clean"],
        rules_must_pass=["icd203.tc.8"],
    )
    assert compare(loose, rec) == []


async def test_range_expectations_report_every_way_they_disagree(make_config):
    clean, record = await _played("clean-single-source", make_config)
    wrong = _expecting(
        clean,
        state_in=["gate_rejected"],
        status_in=["findings_open"],
        gate_supported_in=[False],
        substance_in=["thin", "insufficient"],
        rules_must_fail=["icd203.tc.2", "nope.rule.1"],
    )
    assert compare(wrong, record) == [
        "state: expected one of ['gate_rejected'], got 'completed'",
        "status: expected one of ['findings_open'], got 'clean'",
        "gate.supported: expected one of [False], got True",
        "gate.substance: expected one of ['thin', 'insufficient'], got 'sufficient'",
        "rules_must_fail: not in pack: nope.rule.1",
        "rules_must_fail: never failed: icd203.tc.2, nope.rule.1",
    ]
    unfixable, rec = await _played("unsourced-unfixable", make_config)
    strict = _expecting(
        unfixable,
        state="completed",
        iterations_max=1,
        rules_must_pass=["icd203.tc.8"],
        rules_may_fail=[],
    )
    assert compare(strict, rec) == [
        "iterations: expected at most 1, got 2",
        "rules_must_pass: failed in iteration 2: icd203.tc.8",
        "rules: unexpected failure in iteration 2: icd203.as.5, icd206.src.2",
    ]


async def test_a_degraded_audit_counts_as_no_audit_ran(make_config):
    backend = FakeBackend(name="fake")
    backend.script("auditor", *[BAD] * 4)
    scenario, record = await _played("max-iterations-zero", make_config, backend)
    [note] = record.report.metadata.degradations
    assert note.startswith("audit incomplete")
    assert [f.rule_id for f in record.findings] == ["icd203.tc.8"]  # the engine's own check
    assert audited_iterations(record) == set()
    mismatches = compare(scenario, record)
    assert "failing_rules[0]: no audit ran for iteration 0" in mismatches
    assert not any(m.startswith("failing_rules[0]: expected") for m in mismatches)
    ranged = _expecting(scenario, state="completed", rules_must_pass=["icd203.tc.8"])
    assert compare(ranged, record) == ["rules: no audit ran"]


class AuditorFailsFromIteration1(FakeBackend):
    """The first audit answers (synthetic), every later auditor reply is garbage."""

    audits = 0

    async def chat(self, request):
        if parse_input([m.model_dump() for m in request.messages])["task"] == "auditor":
            self.audits += 1
            if self.audits > 1:
                return ChatResponse(content=BAD)
        return await super().chat(request)


async def test_a_degraded_last_audit_leaves_the_rule_sets_unscored(make_config):
    scenario, record = await _played(
        "unsourced-fixed-one-loop", make_config, AuditorFailsFromIteration1(name="fake")
    )
    assert record.iterations == 1 and record.report is not None
    assert record.report.metadata.degradations[0].startswith("audit incomplete")
    assert audited_iterations(record) == {0}  # only iteration 0 was audited
    not_scored = "rules: no audit of the delivered draft (iteration 1 degraded)"
    must_pass = _expecting(
        scenario, state="completed", rules_must_pass=["icd203.tc.8"], rules_may_fail=[]
    )
    assert compare(must_pass, record) == [not_scored]  # tc.8 failed in 0: not read as a failure
    must_fail = _expecting(scenario, state="completed", rules_must_fail=["icd203.tc.8"])
    assert compare(must_fail, record) == [not_scored]  # met over the audited iterations
    never = _expecting(scenario, state="completed", rules_must_fail=["icd203.tc.2"])
    assert compare(never, record) == [not_scored, "rules_must_fail: never failed: icd203.tc.2"]


async def test_engine_only_findings_alone_leave_an_iteration_unaudited(make_config):
    """The `ENGINE_CHECK` clause of `audited_iterations` on its own (R-M13-5). No pipeline path
    leaves an iteration with only engine findings and no `audit incomplete` note naming it: a
    degraded audit always ends the run and names its last iteration. So the record is built by
    hand from a played one: `unsourced-unfixable` with every audit after the first failing
    (iteration 0 audited; iteration 1 carries only the engine's icd203.tc.8 failure), with the
    report's degradation note removed."""
    scenario, played = await _played(
        "unsourced-unfixable", make_config, AuditorFailsFromIteration1(name="fake")
    )
    assert played.iterations == 1
    assert played.report.metadata.degradations[0].startswith("audit incomplete")
    meta = played.report.metadata.model_copy(update={"degradations": []})
    record = played.model_copy(
        update={"report": played.report.model_copy(update={"metadata": meta})}
    )
    late = [f for f in record.findings if f.iteration == 1]
    assert [f.rule_id for f in late] == ["icd203.tc.8"]
    assert all(f.evidence.startswith(ENGINE_CHECK) for f in late)
    assert audited_iterations(record) == {0}  # no note names iteration 1: the prefix decides
    worded = late[0].model_copy(update={"evidence": "The auditor's own words."})
    findings = [worded if f is late[0] else f for f in record.findings]
    assert audited_iterations(record.model_copy(update={"findings": findings})) == {0, 1}
    must_pass = _expecting(
        scenario, state="completed", rules_must_pass=["icd203.tc.8"], rules_may_fail=[]
    )
    assert compare(must_pass, record) == [
        "rules: no audit of the delivered draft (iteration 1 degraded)"
    ]


async def test_audited_iterations_read_only_audit_incomplete_degradations(make_config):
    _, record = await _played("clean-single-source", make_config)
    assert audited_iterations(record) == {0}

    def with_note(note: str):
        meta = record.report.metadata.model_copy(update={"degradations": [note]})
        report = record.report.model_copy(update={"metadata": meta})
        return record.model_copy(update={"report": report})

    assert audited_iterations(with_note("audit incomplete after 2 attempts: x")) == set()
    assert audited_iterations(with_note("conveyance skipped after 2 attempts: x")) == {0}


REAL = load_scenarios(REAL_SCENARIOS_DIR)


def test_the_real_set_is_written_for_real_models():
    assert len(REAL) == 12
    rule_ids = set(load_pack("icd203-base").rule_ids())
    for s in REAL:
        e = s.expect
        assert "A good model" in s.description and "A weak model" in s.description, s.name
        sources = scenario_sources(s)
        visible = [[u for u in src.units if not u.meta.get("hidden")] for src in sources]
        assert all(2 <= len(units) <= 3 for units in visible), s.name
        assert not e.failing_rules, s.name  # rule expectations are sets, never exact per iteration
        named = set(e.rules_must_pass) | set(e.rules_may_fail or []) | set(e.rules_must_fail)
        assert named <= rule_ids, s.name
        if e.state is not RunState.GATE_REJECTED:  # a run that may deliver names what must pass
            assert e.rules_must_pass, s.name
        assert e.expects_gate() or e.state_in, s.name


QUOTE_SCENARIOS = ["borrowed-quotation", "quoted-customs-figures"]


@pytest.mark.parametrize("name", QUOTE_SCENARIOS)
async def test_the_quote_scenarios_agree_fully_on_the_synthetic_model(name, make_config):
    """CRL-93: CI plays the fabricated-quote and faithful-quote scenarios on the synthetic model,
    which borrows the statement's quotation once and quotes its units faithfully otherwise."""
    [scenario] = [s for s in REAL if s.name == name]
    assert scenario.pipeline == {"evidence_quotes": "required"}
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert compare(scenario, record) == []
    engine = [f.evidence for f in record.findings if f.evidence.startswith(ENGINE_CHECK)]
    if name == "borrowed-quotation":
        assert engine == [f"{ENGINE_CHECK}quote not found in src1/u1 (c0)"] * 2
    else:
        assert engine == [] and all(c.quotes for c in record.report.claims if c.evidence)


async def test_evidence_quotes_off_sends_no_quote_anywhere(make_config):
    """CRL-93: under `off` (the default) no request mentions quotes, so the synthetic set plays
    exactly as before; `test_without_quotes_the_schema_is_the_one_sent_before_quotes_existed`
    pins the schema itself."""
    backend = FakeBackend(name="fake")
    for scenario in SCENARIOS:
        if "evidence_quotes" in scenario.pipeline:
            continue
        await run_scenario(
            scenario,
            make_config(),
            backends={"fake": backend},
            prompts=PromptLibrary(),
            log=CallLog(),
        )
    assert backend.requests
    for request in backend.requests:
        assert "quote" not in request.model_dump_json().casefold().replace("unquote", "")


@pytest.mark.parametrize("scenario", REAL, ids=[s.name for s in REAL])
async def test_every_real_scenario_runs_to_an_outcome_on_the_synthetic_model(scenario, make_config):
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert record.state in (RunState.COMPLETED, RunState.GATE_REJECTED), record.error
    assert record.gate is not None
    assert isinstance(compare(scenario, record), list)  # scoring never raises on these records


INJECTION_SCENARIOS = ["injected-instruction-visible", "injected-instruction-hidden"]


@pytest.mark.parametrize("name", INJECTION_SCENARIOS)
async def test_the_injection_scenarios_agree_fully_on_the_synthetic_model(name, make_config):
    """CRL-137: an instruction planted in a source, visible or hidden. The visible one reaches
    the models flagged suspect; the synthetic writer cites it once, the auditor fails
    icd203.tc.8 for the claim resting on it and the revision drops it. The hidden ones are in
    the record and in no model request."""
    [scenario] = [s for s in REAL if s.name == name]
    backend = FakeBackend(name="fake")
    record = await run_scenario(
        scenario,
        make_config(),
        backends={"fake": backend},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    assert compare(scenario, record) == []
    failed = [(f.iteration, f.rule_id) for f in record.findings if f.verdict is Verdict.FAIL]
    sent = " ".join(r.model_dump_json() for r in backend.requests)
    if name == "injected-instruction-visible":
        assert failed == [(0, "icd203.tc.8")] and record.iterations == 1
        payloads = [parse_input([m.model_dump() for m in r.messages]) for r in backend.requests]
        units = [u for p in payloads for u in p.get("units", []) + p.get("cited_units", [])]
        assert "HERON-CLOSED" in sent and {u["ref"] for u in units if u.get("suspect")} == {
            "src1/u3"
        }
    else:
        assert failed == [] and record.iterations == 0
        hidden = [u.text for u in record.sources[0].units if u.meta.get("hidden")]
        assert len(hidden) == 2 and "HERON-CANCELLED" in " ".join(hidden)
        assert "HERON-CANCELLED" not in sent and "src1/u3" not in sent


async def test_injection_expectations_report_every_way_they_disagree(make_config):
    [visible] = [s for s in REAL if s.name == "injected-instruction-visible"]
    record = await run_scenario(
        visible,
        make_config(),
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        log=CallLog(),
    )
    wrong = _expecting(
        visible,
        state="completed",
        hidden_units=["src1/u1"],
        suspect_units=[],
        report_excludes=["Varna", "absent", "PORT"],
    )
    assert compare(wrong, record) == [
        "hidden_units: expected ['src1/u1'], got []",
        "suspect_units: expected [], got ['src1/u3']",
        "report_excludes: the title or key judgments say ['Varna', 'PORT']",
    ]
    assert compare(wrong, record.model_copy(update={"report": None}))[-1].startswith(
        "suspect_units"
    )


@pytest.mark.parametrize(
    "sources",
    ["[{id: src1}]", "[{id: src1, paragraphs: [a], html: '<p>a</p>'}]"],
)
def test_a_scenario_source_has_paragraphs_or_html(tmp_path, sources):
    path = tmp_path / "bad.yaml"
    path.write_text(f"name: x\nstatement: s\nsources: {sources}\nexpect: {{state: completed}}\n")
    with pytest.raises(ScenarioError, match="set paragraphs or html, not both"):
        load_scenario(path)
