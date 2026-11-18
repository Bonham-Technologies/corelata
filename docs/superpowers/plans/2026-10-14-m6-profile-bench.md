# M6 Profile Extractor and Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `corelata profile extract` drafts a team profile from a directory of example reports, and `corelata bench` runs the shipped scenario set against the configured (real) models and reports gate agreement and rule-failure agreement.

**Architecture:** Both commands live in the engine package and need no database. The bench reuses `corelata.scenarios` (load, run, compare) unchanged; a new `corelata.bench` package adds a result schema, scoring, a sequential runner that survives per-run failures, a text formatter, and carries the scenario YAML files as package data so the command works inside the shipped image. The extractor is a fifth agent role (`profiler`, already in `RolesConfig`): it reads the example reports through the existing ingestors, shows the model the base pack it will extend, gets a constrained `ProfileDraft`, converts it to a `Profile` with `draft: true`, proves the profile resolves against the pack chain, and writes commented YAML the team reviews.

**Tech Stack:** Python 3.12, pydantic 2, argparse, Jinja2 prompts, pytest + hypothesis, the synthetic responder and `FakeOpenAIServer` for tests, uv.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §4.4 (`profiler` role), §6.5 (profile), §6.8 (CLI), §10.2, §11 (`roles.profiler`), §13 (scenario fixtures, `corelata bench`), §14 M6 row.

## Global Constraints

- 95% branch coverage for the engine package (`--cov-fail-under=95` in `engine/pyproject.toml`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100).
- Strict pydantic (`extra="forbid"`) for everything a customer edits; model-output schemas are plain `BaseModel` as in `corelata/schema/`.
- The `profiler` role "cannot be used in a run" (§4.4): nothing in `corelata.pipeline` or `corelata.stages` imports the profiler; `run_prompt_ids()` stays `["gate", "discover", "digest", "writer", "conveyor", "auditor"]`.
- A profile written by the extractor always has `draft: true` (§4.4, §6.5); `load_pack` keeps refusing drafts for runs.
- CLI exit codes (cli.py header): 0 ok, 1 failed, 2 usage or config error, 3 completed with findings open / disagreements, 130 interrupted.
- No changes under `api/` or `web/`; the only `deploy/` change is one package-data path in `deploy/tests/check-app-image.sh` (Task 1).
- Commit messages end with the two attribution lines the session uses; write them to a file and `git commit -F FILE`.

## Review Focus

1. **A model failure inside one bench run** (backend down, oversize context, malformed output) must end that run as a `failed` record and a disagreement, and an exception from loading the scenario's pack or profile must become an error entry; in both cases the remaining scenarios still run and the exit code says what happened (1 for errors, 3 for disagreements). Pinned in Task 3 (`test_an_exception_in_one_run_does_not_stop_the_bench`) and Task 4 (`test_bench_profile_missing_is_an_error_exit_1`).
2. **`profile extract --out` pointing at an existing file** must refuse without `--force` and leave the file untouched; a reviewed profile is the team's work. Pinned in Task 7 (`test_extract_refuses_to_overwrite_without_force`).
3. **A model that proposes an unknown rule id, or disables and overrides the same rule**, gets one repair turn; if the second answer is also invalid the command exits 1 and writes nothing. Pinned in Task 6 (`test_check_draft_names_every_problem`) and Task 7 (`test_extract_invalid_draft_twice_exits_1_and_writes_nothing`).
4. **An example-reports directory holding an unsupported or unreadable file** fails before any model call with a message naming the file (exit 2). Pinned in Task 7 (`test_extract_unsupported_example_is_a_usage_error_before_any_call`).
5. **The written draft must load**: it round-trips through `Profile`, resolves against the `extends` chain, is refused by `load_pack` for a run, and `corelata pack validate` reports it as a warning when placed in `profiles/`. Pinned in Task 7 (`test_extract_three_example_reports_produce_a_valid_draft_profile`), the spec §14 exit test.

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/bench/__init__.py` | `SCENARIOS_DIR`: where the shipped scenario set lives. Nothing else (avoids import cycles). |
| `engine/corelata/bench/scenarios/*.yaml` | The ten scenario fixtures, moved from `engine/tests/fixtures/scenarios/`. |
| `engine/corelata/bench/schema.py` | `Rate`, `RuleTally`, `RunResult`, `ScenarioResult`, `BenchSummary`, `BenchReport`. |
| `engine/corelata/bench/score.py` | `score_run`, `error_result`, `summarize`: pure functions from records to results. |
| `engine/corelata/bench/run.py` | `run_bench` (sequential, per-run failure isolation, trace files) and `exit_code`. |
| `engine/corelata/bench/text.py` | `format_bench`: the terminal table. |
| `engine/corelata/schema/profiler.py` | `ProfileDraft` and its parts: what the profiler model returns. |
| `engine/corelata/prompts/templates/profiler/v1.j2` | The profiler prompt. |
| `engine/corelata/profiler.py` | `read_examples`, `check_draft`, `to_profile`, `extract_profile`, `profile_yaml`. |
| `engine/corelata/standards/loader.py` | adds `resolve_profile(profile, packs_dir)` (public wrapper over the chain). |
| `engine/corelata/testing/synthetic.py` | adds the `profiler` handler. |
| `engine/corelata/prompts/check.py` | adds the profiler prompt to `_CHECKS`. |
| `engine/corelata/cli.py` | adds `bench` and `profile extract`. |
| `engine/corelata/schema/export.py` | exports `bench-report`. |
| `engine/tests/test_scenarios.py`, `engine/tests/bench/`, `engine/tests/test_profiler.py`, `engine/tests/test_cli_bench.py`, `engine/tests/test_cli_profile.py`, `engine/tests/testing/test_synthetic.py` | tests. |
| `README.md`, `docs/operator-guide.md`, `docs/m6-followups.md`, spec amendments | docs. |

---

### Task 1: Ship the scenario set inside the package

The bench must run inside the deployed image, which has no repository checkout, so the scenario files become package data. `corelata.scenarios` (the module) keeps its name; the data lives under the new `corelata.bench` package.

**Files:**
- Create: `engine/corelata/bench/__init__.py`
- Move: `engine/tests/fixtures/scenarios/*.yaml` → `engine/corelata/bench/scenarios/*.yaml` (ten files, `git mv`)
- Modify: `engine/tests/test_scenarios.py:20` (the `FIXTURES` constant)
- Modify: `engine/pyproject.toml` (`[tool.hatch.build.targets.wheel] artifacts`)
- Modify: `deploy/tests/check-app-image.sh:21` (package-data list)
- Modify: `README.md` (the "Scenario fixtures" paragraph in Development)
- Test: `engine/tests/bench/__init__.py` (empty), `engine/tests/bench/test_package_data.py`

**Interfaces:**
- Produces: `corelata.bench.SCENARIOS_DIR: Path` — the directory of shipped scenarios; Tasks 3, 4 and the tests use it.

- [ ] **Step 1: Create the package and move the files**

```bash
cd engine
mkdir -p corelata/bench/scenarios tests/bench
git mv tests/fixtures/scenarios/badterm-fixed-one-loop.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/clean-single-source.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/clean-two-sources.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/gate-rejected.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/long-source-digested.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/many-sources-writer-budget.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/max-iterations-zero.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/thin-material.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/unsourced-fixed-one-loop.yaml corelata/bench/scenarios/
git mv tests/fixtures/scenarios/unsourced-unfixable.yaml corelata/bench/scenarios/
rmdir tests/fixtures/scenarios
```

Run the `git mv` lines one per shell command if the environment refuses chained git commands.

`engine/corelata/bench/__init__.py`:

```python
"""`corelata bench` (spec §13, §14 M6): the shipped scenario set and the runner that plays it
against real models. Only the data path lives here; the runner is `corelata.bench.run`, the
result schema `corelata.bench.schema`, so importing the package never imports the pipeline."""

from pathlib import Path

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
```

`engine/tests/bench/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`engine/tests/bench/test_package_data.py`:

```python
from corelata.bench import SCENARIOS_DIR
from corelata.scenarios import load_scenarios


def test_shipped_scenarios_load_and_are_the_known_set():
    names = [s.name for s in load_scenarios(SCENARIOS_DIR)]
    assert names == [
        "badterm-fixed-one-loop",
        "clean-single-source",
        "clean-two-sources",
        "gate-rejected",
        "long-source-digested",
        "many-sources-writer-budget",
        "max-iterations-zero",
        "thin-material",
        "unsourced-fixed-one-loop",
        "unsourced-unfixable",
    ]
    assert all(p.suffix == ".yaml" for p in SCENARIOS_DIR.iterdir() if p.is_file())
```

- [ ] **Step 3: Point the existing scenario tests at the package**

In `engine/tests/test_scenarios.py` replace

```python
FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
```

with

```python
from corelata.bench import SCENARIOS_DIR

FIXTURES = SCENARIOS_DIR
```

(keep the import block sorted for ruff: `from corelata.bench import SCENARIOS_DIR` goes before `from corelata.llm.agent import CallLog`; drop `from pathlib import Path` if nothing else uses it).

- [ ] **Step 4: Package data and the image check**

In `engine/pyproject.toml`, add to `artifacts`:

```toml
  "corelata/bench/scenarios/*.yaml",
```

In `deploy/tests/check-app-image.sh` line 21, add `bench/scenarios/clean-single-source.yaml` to the list of package files the image must carry (same line, space separated, keep the `\` continuation intact).

In `README.md` Development, change the paragraph to:

```markdown
Scenario fixtures (`engine/corelata/bench/scenarios/*.yaml`) pin the pipeline's behaviour
against the synthetic model: sources, statement, expected gate verdict, failing rules per
iteration. They ship inside the package so `corelata bench` can play them against real models
(see M6). Add one when you change what a run does.
```

- [ ] **Step 5: Run the tests**

Run: `cd engine && uv run pytest tests/bench tests/test_scenarios.py -q --no-cov`
Expected: all pass.

Run: `cd engine && uv build --wheel -o /tmp/corelata-wheel && unzip -l /tmp/corelata-wheel/*.whl | grep bench/scenarios | wc -l`
Expected: `10`. (Delete `/tmp/corelata-wheel` afterwards.)

- [ ] **Step 6: Commit**

```bash
git add -A engine/corelata/bench engine/tests/bench engine/tests/test_scenarios.py engine/tests/fixtures engine/pyproject.toml deploy/tests/check-app-image.sh README.md
git commit -F /path/to/message   # "build: ship the scenario set as package data (corelata.bench)"
```

---

### Task 2: Bench result schema and scoring

**Files:**
- Create: `engine/corelata/bench/schema.py`
- Create: `engine/corelata/bench/score.py`
- Modify: `engine/corelata/schema/export.py` (add `"bench-report": BenchReport`)
- Test: `engine/tests/bench/test_score.py`, `engine/tests/schema/test_export.py` (count, if it asserts one)

**Interfaces:**
- Consumes: `corelata.scenarios.Scenario`, `ScenarioExpect`, `compare(scenario, record) -> list[str]`; `corelata.schema.RunRecord` (`state`, `status`, `iterations`, `gate`, `findings`, `usage`), `Verdict.FAIL`.
- Produces (used by Tasks 3 and 4):
  - `Rate(agree: int, total: int)` with `.add(agreed: bool | None)` and computed `ratio: float | None`
  - `RuleTally(expected, hit, missed, unexpected)`
  - `RunResult(repeat, ok, error, state, status, iterations, duration_s, calls, tokens_in, tokens_out, mismatches, gate_agree, rules_agree, state_agree)` with property `agree`
  - `ScenarioResult(name, description, runs)`
  - `BenchSummary`, `BenchReport`
  - `score_run(scenario, record, *, repeat, duration_s, tallies) -> RunResult`
  - `error_result(*, repeat, error, duration_s) -> RunResult`
  - `summarize(results: list[ScenarioResult], *, duration_s: float) -> BenchSummary`

- [ ] **Step 1: Write the failing tests**

`engine/tests/bench/test_score.py`:

```python
from corelata.bench import SCENARIOS_DIR
from corelata.bench.schema import Rate, RuleTally, RunResult, ScenarioResult
from corelata.bench.score import error_result, score_run, summarize
from corelata.llm.agent import CallLog
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import load_scenario, run_scenario
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
                update={"failing_rules": {0: ["icd203.tc.2", "icd203.tc.8"], 1: [], 3: ["icd203.tc.1"]}}
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
    good = RunResult(repeat=1, ok=True, state="completed", gate_agree=True, rules_agree=True,
                     state_agree=True, calls=4, tokens_in=40, tokens_out=20, duration_s=1)
    bad = RunResult(repeat=2, ok=True, state="completed", mismatches=["status: x"],
                    gate_agree=True, rules_agree=False, state_agree=False, duration_s=1)
    summary = summarize(
        [ScenarioResult(name="a", description="", runs=[good, bad]),
         ScenarioResult(name="b", description="", runs=[err])],
        duration_s=2.5,
    )
    assert summary.scenarios == 2 and summary.runs == 3 and summary.errors == 1
    assert (summary.full_agreement.agree, summary.full_agreement.total) == (1, 3)
    assert (summary.gate_agreement.agree, summary.gate_agreement.total) == (2, 2)
    assert (summary.rule_agreement.agree, summary.rule_agreement.total) == (1, 2)
    assert (summary.state_agreement.agree, summary.state_agreement.total) == (1, 2)
    assert summary.tokens_in == 40 and summary.tokens_out == 20 and summary.duration_s == 2.5
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/bench/test_score.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: corelata.bench.schema`.

- [ ] **Step 3: The schema**

`engine/corelata/bench/schema.py`:

```python
"""What `corelata bench` reports (spec §13): one result per scenario run, rule tallies across
runs, and agreement rates. Exported as `bench-report.schema.json`."""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from corelata.schema import ReportStatus, RunState


class Rate(BaseModel):
    """Agreements over decided cases; a case the scenario does not specify is not counted."""

    agree: int = 0
    total: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ratio(self) -> float | None:
        return None if self.total == 0 else round(self.agree / self.total, 4)

    def add(self, agreed: bool | None) -> None:
        if agreed is None:
            return
        self.total += 1
        self.agree += int(agreed)


class RuleTally(BaseModel):
    """How one rule behaved across every audited iteration the scenarios specify."""

    expected: int = 0  # times the rule was expected to fail
    hit: int = 0  # expected and did fail
    missed: int = 0  # expected, did not fail (or the iteration was never audited)
    unexpected: int = 0  # failed in an iteration that did not expect it


class RunResult(BaseModel):
    repeat: int
    ok: bool  # the run produced a record (even a failed one); False means an exception
    error: str | None = None
    state: RunState | None = None
    status: ReportStatus | None = None
    iterations: int | None = None
    duration_s: float = 0.0
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    mismatches: list[str] = Field(default_factory=list)  # from scenarios.compare
    gate_agree: bool | None = None  # None: the scenario does not specify the gate
    rules_agree: bool | None = None  # None: the scenario lists no failing rules
    state_agree: bool | None = None  # None only for an errored run

    @property
    def agree(self) -> bool:
        return self.ok and not self.mismatches


class ScenarioResult(BaseModel):
    name: str
    description: str
    runs: list[RunResult]


class BenchSummary(BaseModel):
    scenarios: int
    runs: int
    errors: int
    full_agreement: Rate  # compare() found nothing to object to
    gate_agreement: Rate
    rule_agreement: Rate
    state_agreement: Rate
    tokens_in: int
    tokens_out: int
    duration_s: float


class BenchReport(BaseModel):
    corelata_version: str
    started_at: datetime
    finished_at: datetime
    config_hash: str
    models: dict[str, str]  # role -> model id sent to the server
    scenarios_dir: str
    repeat: int
    scenarios: list[ScenarioResult]
    rules: dict[str, RuleTally]  # rule id -> tally, sorted by id
    summary: BenchSummary
```

- [ ] **Step 4: Scoring**

`engine/corelata/bench/score.py`:

```python
"""From a scenario and the record a real model produced to a `RunResult` (pure functions)."""

from corelata.bench.schema import BenchSummary, Rate, RuleTally, RunResult, ScenarioResult
from corelata.scenarios import Scenario, compare
from corelata.schema import RunRecord, Verdict


def _gate_agree(scenario: Scenario, record: RunRecord) -> bool | None:
    e = scenario.expect
    if e.gate_supported is None and e.substance is None:
        return None
    if record.gate is None:
        return False
    return (e.gate_supported is None or e.gate_supported == record.gate.supported) and (
        e.substance is None or e.substance == record.gate.substance
    )


def _rules_agree(
    scenario: Scenario, record: RunRecord, tallies: dict[str, RuleTally]
) -> bool | None:
    expected_by_iteration = scenario.expect.failing_rules
    if not expected_by_iteration:
        return None
    audited = {f.iteration for f in record.findings}
    agree = True
    for iteration, expected in sorted(expected_by_iteration.items()):
        if iteration not in audited:
            agree = False
            for rule_id in expected:
                tally = tallies.setdefault(rule_id, RuleTally())
                tally.expected += 1
                tally.missed += 1
            continue
        actual = {
            f.rule_id
            for f in record.findings
            if f.iteration == iteration and f.verdict is Verdict.FAIL
        }
        if actual != set(expected):
            agree = False
        for rule_id in expected:
            tally = tallies.setdefault(rule_id, RuleTally())
            tally.expected += 1
            if rule_id in actual:
                tally.hit += 1
            else:
                tally.missed += 1
        for rule_id in sorted(actual - set(expected)):
            tallies.setdefault(rule_id, RuleTally()).unexpected += 1
    return agree


def _state_agree(scenario: Scenario, record: RunRecord) -> bool:
    e = scenario.expect
    return (
        record.state == e.state
        and (e.status is None or record.status == e.status)
        and (e.iterations is None or record.iterations == e.iterations)
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
```

An errored run counts in `errors` and as a disagreement in `full_agreement` (the test expects `(1, 3)`), but not in the gate, rule or state rates, which only score runs that produced a record.

- [ ] **Step 5: Export the schema**

In `engine/corelata/schema/export.py` add `from corelata.bench.schema import BenchReport` and the entry `"bench-report": BenchReport` at the end of `EXPORTED`. Run `cd engine && uv run python -m corelata.schema.export ../schema` and commit the new `schema/bench-report.schema.json`. If `engine/tests/schema/test_export.py` asserts a count or list of names, update it.

- [ ] **Step 6: Run the tests**

Run: `cd engine && uv run pytest tests/bench tests/schema -q --no-cov`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add engine/corelata/bench/schema.py engine/corelata/bench/score.py engine/corelata/schema/export.py engine/tests/bench/test_score.py engine/tests/schema schema/bench-report.schema.json
git commit -F /path/to/message   # "feat: bench result schema and scoring"
```

---

### Task 3: The bench runner and text report

**Files:**
- Create: `engine/corelata/bench/run.py`
- Create: `engine/corelata/bench/text.py`
- Test: `engine/tests/bench/test_run.py`, `engine/tests/bench/test_text.py`

**Interfaces:**
- Consumes: Task 2's schema and scoring; `corelata.scenarios.run_scenario`; `corelata.pipeline.utcnow`; `corelata.config.config_hash`; `corelata.exports.dump_json`; `corelata.__version__`.
- Produces (used by Task 4):
  - `async def run_bench(cfg, scenarios, *, backends, prompts, repeat=1, out_dir=None, scenarios_dir, now=utcnow, clock=time.monotonic, progress=None) -> BenchReport`
  - `def exit_code(report: BenchReport) -> int` — 1 if any error, 3 if any disagreement, else 0
  - `def format_bench(report: BenchReport) -> str`

- [ ] **Step 1: Write the failing tests**

`engine/tests/bench/test_run.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from corelata import scenarios as scenarios_module
from corelata.bench import SCENARIOS_DIR
from corelata.bench.run import exit_code, run_bench
from corelata.bench.schema import BenchReport
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import load_scenario, load_scenarios
from corelata.testing.fake_backend import FakeBackend

FROZEN = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _ticker(step: float = 0.5):
    t = [0.0]

    def clock() -> float:
        t[0] += step
        return t[0]

    return clock


async def test_full_agreement_on_the_shipped_set(make_config, tmp_path):
    scenarios = load_scenarios(SCENARIOS_DIR)
    lines: list[str] = []
    report = await run_bench(
        make_config(),
        scenarios,
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        out_dir=tmp_path / "bench",
        scenarios_dir=SCENARIOS_DIR,
        now=lambda: FROZEN,
        clock=_ticker(),
        progress=lines.append,
    )
    assert report.summary.scenarios == 10 and report.summary.runs == 10
    assert report.summary.errors == 0 and report.summary.full_agreement.ratio == 1.0
    assert report.summary.gate_agreement.total >= 1 and report.summary.rule_agreement.total >= 1
    assert report.models == {"gate": "model-a", "writer": "model-a", "conveyor": "model-b", "auditor": "model-b"}
    assert report.scenarios_dir == str(SCENARIOS_DIR) and report.repeat == 1
    assert report.started_at == FROZEN and report.corelata_version
    assert exit_code(report) == 0
    assert len(lines) == 10 and lines[0].startswith("badterm-fixed-one-loop 1/1: completed clean")
    trace = tmp_path / "bench" / "clean-single-source" / "run-1" / "trace.json"
    assert json.loads(trace.read_text())["run_id"] == "clean-single-source"
    assert report.rules["icd203.tc.2"].hit >= 1
    BenchReport.model_validate_json(report.model_dump_json())  # round trip


async def test_repeat_runs_each_scenario_n_times(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    report = await run_bench(
        make_config(), [scenario], backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(), repeat=3, scenarios_dir=SCENARIOS_DIR, clock=_ticker(),
    )
    assert [r.repeat for r in report.scenarios[0].runs] == [1, 2, 3]
    assert report.summary.runs == 3 and report.repeat == 3


async def test_a_disagreement_is_exit_3(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    wrong = scenario.model_copy(
        update={"expect": scenario.expect.model_copy(update={"status": "findings_open"})}
    )
    report = await run_bench(
        make_config(), [wrong], backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(), scenarios_dir=SCENARIOS_DIR, clock=_ticker(),
    )
    run = report.scenarios[0].runs[0]
    assert run.ok and run.mismatches == ["status: expected 'findings_open', got 'clean'"]
    assert exit_code(report) == 3


async def test_an_exception_in_one_run_does_not_stop_the_bench(make_config, monkeypatch, tmp_path):
    good = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    broken = good.model_copy(update={"name": "broken", "profile": "nope"})
    real = scenarios_module.run_scenario

    async def flaky(scenario, cfg, **kw):
        if scenario.name == "broken":
            raise RuntimeError("profile 'nope' not found in pack 'icd203-base' or its ancestors")
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", flaky)
    lines: list[str] = []
    report = await run_bench(
        make_config(), [broken, good], backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(), out_dir=tmp_path, scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(), progress=lines.append,
    )
    first, second = report.scenarios
    assert first.name == "broken" and not first.runs[0].ok
    assert first.runs[0].error == "RuntimeError: profile 'nope' not found in pack 'icd203-base' or its ancestors"
    assert second.runs[0].agree
    assert report.summary.errors == 1 and exit_code(report) == 1
    assert lines[0] == "broken 1/1: error: RuntimeError: profile 'nope' not found in pack 'icd203-base' or its ancestors"
    assert not (tmp_path / "broken").exists() and (tmp_path / "clean-single-source").is_dir()


async def test_a_model_failure_is_a_failed_record_not_an_error(make_config):
    from corelata.llm.types import BackendError

    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    backend = FakeBackend(name="fake")
    for _ in range(6):  # every retry of the gate call fails
        backend.script("gate", BackendError("connection refused"))
    report = await run_bench(
        make_config(), [scenario], backends={"fake": backend}, prompts=PromptLibrary(),
        scenarios_dir=SCENARIOS_DIR, clock=_ticker(),
    )
    run = report.scenarios[0].runs[0]
    assert run.ok and run.state == "failed" and not run.agree
    assert report.summary.errors == 0 and exit_code(report) == 3
```

The pipeline turns `AGENT_FAILURES = (StructuredOutputError, BackendError)` into a `failed` record (`corelata/pipeline.py`, the `except AGENT_FAILURES` arms); any other exception type propagates and would become an error entry instead. Check `BackendError`'s constructor in `corelata/llm/types.py` and build it the way `tests/llm` does; keep the assertions (`run.ok` True, `exit_code` 3).

`engine/tests/bench/test_text.py`:

```python
from datetime import UTC, datetime

from corelata.bench.schema import (
    BenchReport, BenchSummary, Rate, RuleTally, RunResult, ScenarioResult,
)
from corelata.bench.text import format_bench


def _report() -> BenchReport:
    t = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    good = RunResult(repeat=1, ok=True, state="completed", status="clean", iterations=0,
                     duration_s=12.3, calls=4, tokens_in=1200, tokens_out=400,
                     gate_agree=True, rules_agree=None, state_agree=True)
    bad = RunResult(repeat=1, ok=True, state="completed", status="findings_open", iterations=2,
                    duration_s=40.0, calls=9, tokens_in=5000, tokens_out=900,
                    mismatches=["status: expected 'clean', got 'findings_open'",
                                "failing_rules[1]: expected [], got ['icd203.tc.8']"],
                    gate_agree=True, rules_agree=False, state_agree=False)
    err = RunResult(repeat=1, ok=False, error="RuntimeError: boom", duration_s=0.1)
    results = [
        ScenarioResult(name="clean-single-source", description="", runs=[good]),
        ScenarioResult(name="unsourced-fixed-one-loop", description="", runs=[bad]),
        ScenarioResult(name="broken", description="", runs=[err]),
    ]
    summary = BenchSummary(
        scenarios=3, runs=3, errors=1, full_agreement=Rate(agree=1, total=3),
        gate_agreement=Rate(agree=2, total=2), rule_agreement=Rate(agree=0, total=1),
        state_agreement=Rate(agree=1, total=2), tokens_in=6200, tokens_out=1300, duration_s=52.4,
    )
    return BenchReport(
        corelata_version="0.1.0", started_at=t, finished_at=t, config_hash="abc", repeat=1,
        models={"gate": "qwen3-32b", "writer": "qwen3-32b", "conveyor": "qwen3-32b", "auditor": "qwen3-32b"},
        scenarios_dir="/x", scenarios=results,
        rules={"icd203.tc.8": RuleTally(expected=1, hit=0, missed=0, unexpected=1),
               "icd203.tc.2": RuleTally(expected=2, hit=2)},
        summary=summary,
    )


def test_format_bench_lists_scenarios_summary_rules_and_mismatches():
    text = format_bench(_report())
    lines = text.splitlines()
    assert lines[0].startswith("corelata bench 0.1.0")
    assert "models: gate=qwen3-32b writer=qwen3-32b conveyor=qwen3-32b auditor=qwen3-32b" in text
    table = [ln for ln in lines if ln.startswith(("clean-single-source", "unsourced-fixed", "broken"))]
    assert len(table) == 3
    assert "yes" in table[0] and "completed clean" in table[0] and "12.3s" in table[0]
    assert "no" in table[1] and "findings_open" in table[1]
    assert "error" in table[2] and "RuntimeError: boom" in table[2]
    assert "full agreement 1/3 (33%)" in text
    assert "gate agreement 2/2 (100%)" in text
    assert "rule-failure agreement 0/1 (0%)" in text
    assert "state agreement 1/2 (50%)" in text
    assert "errors 1" in text and "tokens in 6200, out 1300" in text
    assert "icd203.tc.8" in text and "unexpected 1" in text
    assert "icd203.tc.2" not in text.split("rules with misses or unexpected failures")[1]
    assert "  unsourced-fixed-one-loop run 1:" in text
    assert "    status: expected 'clean', got 'findings_open'" in text


def test_format_bench_when_everything_agrees_has_no_rule_or_mismatch_sections():
    report = _report()
    report.scenarios = report.scenarios[:1]
    report.rules = {"icd203.tc.2": RuleTally(expected=2, hit=2)}
    report.summary = BenchSummary(
        scenarios=1, runs=1, errors=0, full_agreement=Rate(agree=1, total=1),
        gate_agreement=Rate(agree=1, total=1), rule_agreement=Rate(), state_agreement=Rate(agree=1, total=1),
        tokens_in=1, tokens_out=1, duration_s=1,
    )
    text = format_bench(report)
    assert "rule-failure agreement n/a" in text
    assert "rules with misses" not in text and "mismatches" not in text
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/bench/test_run.py tests/bench/test_text.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: The runner**

`engine/corelata/bench/run.py`:

```python
"""Play scenarios against the configured models, one run at a time (a real model server is the
bottleneck; `backends[*].max_concurrency` already bounds its load). A run that raises becomes an
error entry and the bench continues; a run whose model calls fail ends `failed` like any run and
is scored as a disagreement."""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from corelata import __version__
from corelata.bench.schema import BenchReport, RuleTally, RunResult, ScenarioResult
from corelata.bench.score import error_result, score_run, summarize
from corelata.config import CorelataConfig, config_hash
from corelata.exports import dump_json
from corelata.llm.agent import CallLog
from corelata.llm.types import Backend
from corelata.pipeline import utcnow
from corelata.prompts.library import PromptLibrary
from corelata.scenarios import Scenario, run_scenario

Progress = Callable[[str], None]


def _describe(result: RunResult) -> str:
    if not result.ok:
        return f"error: {result.error}"
    status = f" {result.status.value}" if result.status is not None else ""
    state = result.state.value if result.state is not None else "?"
    verdict = "agree" if result.agree else f"{len(result.mismatches)} mismatch(es)"
    return f"{state}{status} in {result.duration_s:.1f}s, {verdict}"


def _write_trace(out_dir: Path, name: str, repeat: int, record_json: str) -> None:
    run_dir = out_dir / name / f"run-{repeat}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trace.json").write_text(record_json, encoding="utf-8")


async def run_bench(
    cfg: CorelataConfig,
    scenarios: list[Scenario],
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    repeat: int = 1,
    out_dir: Path | None = None,
    scenarios_dir: Path,
    now: Callable[[], datetime] = utcnow,
    clock: Callable[[], float] = time.monotonic,
    progress: Progress | None = None,
) -> BenchReport:
    started = now()
    bench_t0 = clock()
    tallies: dict[str, RuleTally] = {}
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        runs: list[RunResult] = []
        for k in range(1, repeat + 1):
            t0 = clock()
            try:
                record = await run_scenario(
                    scenario,
                    cfg,
                    backends=backends,
                    prompts=prompts,
                    log=CallLog(store_io=False),
                    now=now,
                )
            except Exception as e:  # noqa: BLE001 - one broken scenario must not end the bench
                result = error_result(
                    repeat=k, error=f"{type(e).__name__}: {e}", duration_s=clock() - t0
                )
            else:
                result = score_run(
                    scenario, record, repeat=k, duration_s=clock() - t0, tallies=tallies
                )
                if out_dir is not None:
                    _write_trace(
                        out_dir, scenario.name, k, dump_json(record.model_dump(mode="json"))
                    )
            runs.append(result)
            if progress is not None:
                progress(f"{scenario.name} {k}/{repeat}: {_describe(result)}")
        results.append(
            ScenarioResult(name=scenario.name, description=scenario.description, runs=runs)
        )
    return BenchReport(
        corelata_version=__version__,
        started_at=started,
        finished_at=now(),
        config_hash=config_hash(cfg),
        models={
            role: cfg.models[key].name or key for role, key in cfg.roles.all_roles()
        },
        scenarios_dir=str(scenarios_dir),
        repeat=repeat,
        scenarios=results,
        rules={rule_id: tallies[rule_id] for rule_id in sorted(tallies)},
        summary=summarize(results, duration_s=clock() - bench_t0),
    )


def exit_code(report: BenchReport) -> int:
    """1 when any run errored, 3 when any run disagreed with its scenario, else 0."""
    if report.summary.errors:
        return 1
    if any(not run.agree for s in report.scenarios for run in s.runs):
        return 3
    return 0
```

Check `CallLog.__init__` accepts `store_io` (it does in `tests/conftest.py`: `CallLog(store_io=store_io)`). The progress line for an errored run must read exactly `"<name> <k>/<repeat>: error: <TypeName>: <message>"` and for a completed run start with `"<name> <k>/<repeat>: completed clean"` (the tests pin both); adjust `_describe` so the state word comes first, then the status, as shown.

- [ ] **Step 4: The text report**

`engine/corelata/bench/text.py`:

```python
"""The terminal rendering of a `BenchReport`."""

from corelata.bench.schema import BenchReport, Rate, RunResult


def _pct(rate: Rate) -> str:
    if rate.total == 0:
        return "n/a"
    return f"{rate.agree}/{rate.total} ({round(100 * rate.agree / rate.total)}%)"


def _outcome(run: RunResult) -> str:
    if not run.ok:
        return f"error  {run.error}"
    state = run.state.value if run.state is not None else "?"
    status = f" {run.status.value}" if run.status is not None else ""
    return f"{'yes' if run.agree else 'no ':<4} {state}{status}"


def format_bench(report: BenchReport) -> str:
    s = report.summary
    width = max([len(x.name) for x in report.scenarios] + [8])
    lines = [
        f"corelata bench {report.corelata_version}  config {report.config_hash}  "
        f"{report.started_at:%Y-%m-%d %H:%M} UTC",
        "models: " + " ".join(f"{role}={model}" for role, model in report.models.items()),
        f"scenarios: {report.scenarios_dir} (repeat {report.repeat})",
        "",
        f"{'scenario':<{width}}  run  agree  outcome                 time    calls  tokens",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            lines.append(
                f"{scenario.name:<{width}}  {run.repeat:>3}  {_outcome(run):<30} "
                f"{run.duration_s:>6.1f}s  {run.calls:>5}  {run.tokens_in + run.tokens_out:>6}"
            )
    lines += [
        "",
        f"full agreement {_pct(s.full_agreement)}",
        f"gate agreement {_pct(s.gate_agreement)}",
        f"rule-failure agreement {_pct(s.rule_agreement)}",
        f"state agreement {_pct(s.state_agreement)}",
        f"runs {s.runs}, errors {s.errors}, tokens in {s.tokens_in}, out {s.tokens_out}, "
        f"{s.duration_s:.1f}s",
    ]
    noisy = {rid: t for rid, t in report.rules.items() if t.missed or t.unexpected}
    if noisy:
        lines += ["", "rules with misses or unexpected failures"]
        for rid, t in noisy.items():
            lines.append(
                f"  {rid}: expected {t.expected}, hit {t.hit}, missed {t.missed}, "
                f"unexpected {t.unexpected}"
            )
    mismatched = [
        (sc.name, run)
        for sc in report.scenarios
        for run in sc.runs
        if run.ok and run.mismatches
    ]
    if mismatched:
        lines += ["", "mismatches"]
        for name, run in mismatched:
            lines.append(f"  {name} run {run.repeat}:")
            lines += [f"    {m}" for m in run.mismatches]
    return "\n".join(lines) + "\n"
```

Make the column layout satisfy the tests (the exact spacing is free; the substrings are not): the outcome cell must contain `yes`/`no`/`error`, the state and status words, and the error text; the time cell must print one decimal followed by `s`.

- [ ] **Step 5: Run the tests**

Run: `cd engine && uv run pytest tests/bench -q --no-cov`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add engine/corelata/bench/run.py engine/corelata/bench/text.py engine/tests/bench/test_run.py engine/tests/bench/test_text.py
git commit -F /path/to/message   # "feat: the bench runner and its text report"
```

---

### Task 4: `corelata bench`

**Files:**
- Modify: `engine/corelata/cli.py` (parser, dispatch, `_bench`)
- Test: `engine/tests/test_cli_bench.py`

**Interfaces:**
- Consumes: `corelata.bench.SCENARIOS_DIR`, `run_bench`, `exit_code`, `format_bench`, `BenchReport`; `corelata.scenarios.load_scenarios`, `ScenarioError`; `build_backends`; `validate_prompts`; `dump_json`.
- Produces: the command

```
corelata bench [--config FILE] [--scenarios DIR] [--only NAME ...] [--repeat N] [--out DIR] [--json]
```

Exit 0 full agreement, 3 any disagreement, 1 any errored run, 2 usage/config. Progress lines go to stderr; the text report (or, with `--json`, the report JSON) goes to stdout; with `--out DIR` the report is also written to `DIR/bench.json` and each run's `trace.json` to `DIR/<scenario>/run-<k>/`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_cli_bench.py`:

```python
import json
import shutil
from pathlib import Path

import pytest
import yaml

from corelata.bench import SCENARIOS_DIR
from corelata.bench.schema import BenchReport
from corelata.cli import main
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG


@pytest.fixture
def fake_server():
    with FakeOpenAIServer() as server:
        yield server


@pytest.fixture
def config_path(tmp_path, fake_server) -> Path:
    data = {**BASE_CONFIG, "backends": {"fake": {"base_url": fake_server.base_url}}}
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_bench_two_scenarios_text_and_files(config_path, tmp_path, capsys):
    out = tmp_path / "bench"
    rc = main(["bench", "--config", str(config_path), "--only", "clean-single-source",
               "--only", "gate-rejected", "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "full agreement 2/2 (100%)" in captured.out
    assert "gate agreement 1/1 (100%)" in captured.out
    assert captured.err.count("1/1:") == 2  # progress lines
    report = BenchReport.model_validate_json((out / "bench.json").read_text())
    assert [s.name for s in report.scenarios] == ["clean-single-source", "gate-rejected"]
    assert (out / "gate-rejected" / "run-1" / "trace.json").is_file()


def test_bench_json_output(config_path, capsys):
    rc = main(["bench", "--config", str(config_path), "--only", "clean-single-source", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["runs"] == 1 and data["summary"]["full_agreement"]["ratio"] == 1.0


def test_bench_disagreement_is_exit_3(config_path, tmp_path, capsys):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    data = yaml.safe_load((SCENARIOS_DIR / "clean-single-source.yaml").read_text())
    data["expect"]["status"] = "findings_open"
    (scenarios / "wrong.yaml").write_text(yaml.safe_dump(data))
    rc = main(["bench", "--config", str(config_path), "--scenarios", str(scenarios)])
    out = capsys.readouterr().out
    assert rc == 3
    assert "status: expected 'findings_open', got 'clean'" in out


def test_bench_profile_missing_is_an_error_exit_1(config_path, tmp_path, capsys):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    shutil.copy(SCENARIOS_DIR / "gate-rejected.yaml", scenarios / "gate-rejected.yaml")
    data = yaml.safe_load((SCENARIOS_DIR / "clean-single-source.yaml").read_text())
    data["profile"] = "nope"
    (scenarios / "clean-single-source.yaml").write_text(yaml.safe_dump(data))
    rc = main(["bench", "--config", str(config_path), "--scenarios", str(scenarios)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error" in captured.out and "nope" in captured.out
    assert "gate-rejected" in captured.out  # the other scenario still ran


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--only", "nope"], "unknown scenario 'nope'"),
        (["--repeat", "0"], "--repeat must be between 1 and 20"),
        (["--repeat", "21"], "--repeat must be between 1 and 20"),
    ],
)
def test_bench_usage_errors(config_path, argv, message, capsys):
    assert main(["bench", "--config", str(config_path), *argv]) == 2
    assert message in capsys.readouterr().err


def test_bench_empty_or_broken_scenario_dir(config_path, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["bench", "--config", str(config_path), "--scenarios", str(empty)]) == 2
    assert "no scenarios in" in capsys.readouterr().err
    (empty / "bad.yaml").write_text("name: [\n")
    assert main(["bench", "--config", str(config_path), "--scenarios", str(empty)]) == 2
    assert "bad.yaml: invalid YAML" in capsys.readouterr().err


def test_bench_out_pointing_at_a_file_is_a_usage_error(config_path, tmp_path, capsys):
    f = tmp_path / "file"
    f.write_text("x")
    assert main(["bench", "--config", str(config_path), "--only", "gate-rejected", "--out", str(f)]) == 2
    assert "--out" in capsys.readouterr().err


def test_bench_bad_config(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("nonsense: 1\n")
    assert main(["bench", "--config", str(cfg)]) == 2
```

Whether `profile: nope` surfaces as an exception (error entry, exit 1) or as a `failed` record (exit 3) depends on where `run_report` loads the pack: read `corelata/pipeline.py` (`run_report` and `_Run`). If `load_run_pack` runs inside the try that turns failures into a `failed` record, change the test's expectation to exit 3 and note it in the report; Review Focus 1 is satisfied either way as long as the other scenario still runs and the problem is visible in the output.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/test_cli_bench.py -q --no-cov`
Expected: FAIL (argparse: invalid choice 'bench').

- [ ] **Step 3: The command**

In `engine/corelata/cli.py`:

Imports to add (keep sorted):

```python
from corelata.bench import SCENARIOS_DIR
from corelata.bench.run import exit_code as bench_exit_code
from corelata.bench.run import run_bench
from corelata.bench.text import format_bench
from corelata.scenarios import ScenarioError, load_scenarios
```

Parser (after the `fake-openai` parser, before `add_commands(sub)`):

```python
    bench = sub.add_parser(
        "bench", help="play the scenario set against the configured models and report agreement"
    )
    bench.add_argument("--config", type=Path, default=default_config_path())
    bench.add_argument(
        "--scenarios", type=Path, default=SCENARIOS_DIR, help="directory of scenario YAML files"
    )
    bench.add_argument(
        "--only", action="append", default=[], metavar="NAME", help="run only this scenario"
    )
    bench.add_argument("--repeat", type=int, default=1, help="runs per scenario (1-20)")
    bench.add_argument("--out", type=Path, help="write bench.json and each run's trace here")
    bench.add_argument("--json", action="store_true", help="print the report as JSON")
```

Dispatch in `main`: `if args.command == "bench": return _bench(args)`.

Handler:

```python
def _bench(args: argparse.Namespace) -> int:
    if not 1 <= args.repeat <= 20:
        return _usage("--repeat must be between 1 and 20")
    if args.out is not None and args.out.exists() and not args.out.is_dir():
        return _usage(f"--out {args.out} is not a directory")
    try:
        cfg, issues = load_config(args.config)
        for issue in issues:
            print(f"{issue.level}: {issue.message}", file=sys.stderr)
        prompts = PromptLibrary(cfg.prompts_dir)
        validate_prompts(cfg, prompts)
        scenarios = load_scenarios(args.scenarios)
    except (ConfigError, ScenarioError, OSError) as e:
        return _usage(str(e))
    if not scenarios:
        return _usage(f"no scenarios in {args.scenarios}")
    if args.only:
        known = {s.name for s in scenarios}
        for name in args.only:
            if name not in known:
                return _usage(f"unknown scenario '{name}' (have: {', '.join(sorted(known))})")
        scenarios = [s for s in scenarios if s.name in set(args.only)]
    try:
        backends = build_backends(cfg)
    except ConfigError as e:
        return _usage(str(e))

    async def go():
        try:
            return await run_bench(
                cfg,
                scenarios,
                backends=backends,
                prompts=prompts,
                repeat=args.repeat,
                out_dir=args.out,
                scenarios_dir=args.scenarios,
                progress=lambda line: print(line, file=sys.stderr, flush=True),
            )
        finally:
            for backend in backends.values():
                await backend.aclose()

    report = asyncio.run(go())
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "bench.json").write_text(
            dump_json(report.model_dump(mode="json")), encoding="utf-8"
        )
    if args.json:
        print(dump_json(report.model_dump(mode="json")), end="")
    else:
        print(format_bench(report), end="")
    return bench_exit_code(report)
```

Look at how `_run` in `cli.py` closes backends (around lines 230–265) and mirror it exactly (the `Backend` protocol's `aclose`). If `_run` uses a helper, reuse it.

- [ ] **Step 4: Run the tests, then the whole engine suite**

Run: `cd engine && uv run pytest tests/test_cli_bench.py -q --no-cov`
Expected: pass.

Run: `make test-engine` (needs `make db-up`)
Expected: pass with coverage ≥ 95%.

- [ ] **Step 5: Lint and commit**

Run: `cd engine && uv run ruff check . && uv run ruff format --check .`

```bash
git add engine/corelata/cli.py engine/tests/test_cli_bench.py
git commit -F /path/to/message   # "feat: corelata bench"
```

---

### Task 5: The profiler's output schema, prompt and synthetic answer

**Files:**
- Create: `engine/corelata/schema/profiler.py`
- Modify: `engine/corelata/schema/__init__.py` (export `ProfileDraft`, `DraftRuleOverride`, `DraftLimits`)
- Create: `engine/corelata/prompts/templates/profiler/v1.j2`
- Modify: `engine/corelata/prompts/check.py` (`_CHECKS`)
- Modify: `engine/corelata/testing/synthetic.py` (handler `profiler`, markers)
- Test: `engine/tests/schema/test_profiler.py`, `engine/tests/testing/test_synthetic.py` (exists; add the tests below to it), `engine/tests/prompts/test_library.py` (parametrized over `_CHECKS`, picks the new prompt up automatically)

**Interfaces:**
- Produces (used by Task 6):

```python
class DraftLimits(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=1)

class DraftRuleOverride(BaseModel):
    id: str
    severity: Severity  # from corelata.standards.schema

class ProfileDraft(BaseModel):
    observations: list[str] = Field(min_length=1)
    tone: str = Field(min_length=1)
    key_judgments: DraftLimits | None = None
    analysis_max_words: int | None = Field(None, ge=50)
    heading_style: Literal["plain", "numbered"] = "plain"
    handling_markings: list[str] = Field(default_factory=list)
    source_descriptors: list[str] = Field(default_factory=list)
    disable: list[str] = Field(default_factory=list)
    override: list[DraftRuleOverride] = Field(default_factory=list)
```

- The synthetic `profiler` handler reads payload `{"task": "profiler", "pack": {...}, "reports": [{"name", "units": [str], "truncated": bool}]}` and answers deterministically:
  - `observations`: `["<n> example reports read", "<k> passages in total"]`
  - `tone`: `"Lead with the key judgments; one idea per paragraph; cite every source."`, plus `" Open with a bottom line up front."` when any unit contains `BLUF` (case-sensitive marker).
  - `heading_style`: `"numbered"` when any unit matches `^\d+\.\s` else `"plain"`.
  - `key_judgments`: `{"min": 1, "max": 3}` when any unit casefolds to contain `"key judgment"`, else `None`.
  - `handling_markings`: every unit whose whole text matches `^[A-Z]+(//[A-Z][A-Z /,-]*)+$` (for example `UNCLASSIFIED//FOUO`), deduplicated, in order of first appearance.
  - `source_descriptors`: `[]`.
  - `override`: `[{"id": "icd203.tc.9", "severity": "major"}]` when any unit contains the marker `CHART`, else `[]`.
  - `disable`: `["icd203.tc.4"]` when any unit contains the marker `NOALT`, else `[]`.
  - Marker `BADRULE`: `disable` becomes `["nope.rule.1"]` (an id no pack has) — lets tests exercise the repair turn through the fake server.

- [ ] **Step 1: Write the failing tests**

`engine/tests/schema/test_profiler.py`:

```python
import pytest
from pydantic import ValidationError

from corelata.schema import DraftLimits, DraftRuleOverride, ProfileDraft


def test_profile_draft_minimal_and_full():
    d = ProfileDraft(observations=["x"], tone="Be brief.")
    assert d.heading_style == "plain" and d.key_judgments is None and d.override == []
    full = ProfileDraft(
        observations=["a", "b"],
        tone="t",
        key_judgments=DraftLimits(min=1, max=3),
        analysis_max_words=800,
        heading_style="numbered",
        handling_markings=["UNCLASSIFIED//FOUO"],
        source_descriptors=["a liaison service"],
        disable=["icd203.tc.4"],
        override=[DraftRuleOverride(id="icd203.tc.9", severity="major")],
    )
    assert full.model_dump()["override"] == [{"id": "icd203.tc.9", "severity": "major"}]


@pytest.mark.parametrize(
    "data",
    [
        {"observations": [], "tone": "t"},
        {"observations": ["x"], "tone": ""},
        {"observations": ["x"], "tone": "t", "analysis_max_words": 10},
        {"observations": ["x"], "tone": "t", "heading_style": "fancy"},
        {"observations": ["x"], "tone": "t", "override": [{"id": "a.b", "severity": "fatal"}]},
    ],
)
def test_profile_draft_rejects(data):
    with pytest.raises(ValidationError):
        ProfileDraft.model_validate(data)


def test_profile_draft_schema_is_model_friendly():
    schema = ProfileDraft.model_json_schema()
    assert set(schema["required"]) == {"observations", "tone"}
    assert "description" in schema["properties"]["tone"]
```

Add to `engine/tests/testing/test_synthetic.py` (merge the imports with the file's own):

```python
from corelata.schema import ProfileDraft
from corelata.testing.synthetic import synthetic_response

PACK = {"name": "icd203-base", "version": "1", "rule_ids": ["icd203.tc.4", "icd203.tc.9"],
        "rules": [], "template": {}, "lexicon": {"handling_markings": ["UNCLASSIFIED"],
        "source_descriptors": [], "likelihood_terms": []}}


def _reports(*units: str, n: int = 3):
    return [{"name": f"r{i}.md", "units": list(units), "truncated": False} for i in range(n)]


def test_profiler_plain_reports():
    out = synthetic_response({"task": "profiler", "pack": PACK, "reports": _reports("Varna grew.")})
    draft = ProfileDraft.model_validate(out)
    assert draft.observations == ["3 example reports read", "3 passages in total"]
    assert draft.tone.startswith("Lead with the key judgments")
    assert draft.heading_style == "plain" and draft.key_judgments is None
    assert draft.handling_markings == [] and draft.disable == [] and draft.override == []


def test_profiler_markers_steer_the_draft():
    out = synthetic_response({
        "task": "profiler", "pack": PACK,
        "reports": _reports("UNCLASSIFIED//FOUO", "1. Key Judgments", "BLUF: ports matter.",
                            "A CHART shows traffic.", "NOALT", "UNCLASSIFIED//FOUO", n=1),
    })
    draft = ProfileDraft.model_validate(out)
    assert draft.handling_markings == ["UNCLASSIFIED//FOUO"]
    assert draft.heading_style == "numbered"
    assert draft.key_judgments is not None and draft.key_judgments.max == 3
    assert draft.tone.endswith("Open with a bottom line up front.")
    assert [o.model_dump() for o in draft.override] == [{"id": "icd203.tc.9", "severity": "major"}]
    assert draft.disable == ["icd203.tc.4"]


def test_profiler_badrule_marker_proposes_an_unknown_rule():
    out = synthetic_response({"task": "profiler", "pack": PACK, "reports": _reports("BADRULE", n=1)})
    assert out["disable"] == ["nope.rule.1"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/schema/test_profiler.py tests/testing -q --no-cov`
Expected: FAIL (`ImportError: ProfileDraft`; `ValueError: unknown task 'profiler'`).

- [ ] **Step 3: The schema**

`engine/corelata/schema/profiler.py`:

```python
"""What the profiler returns (spec §4.4): a constrained sketch of a team profile, drawn from
example reports. The extractor turns it into a `Profile` with `draft: true`."""

from typing import Literal

from pydantic import BaseModel, Field

from corelata.standards.schema import Severity


class DraftLimits(BaseModel):
    min: int = Field(ge=0)
    max: int = Field(ge=1)


class DraftRuleOverride(BaseModel):
    id: str = Field(description="A rule id from INPUT_JSON.pack.rule_ids")
    severity: Severity


class ProfileDraft(BaseModel):
    observations: list[str] = Field(
        min_length=1,
        description="What the example reports share: structure, length, voice, markings; "
        "one sentence each, for the reviewer",
    )
    tone: str = Field(
        min_length=1,
        description="House guidance the writer and conveyor read verbatim: voice, length, "
        "what to lead with, what to avoid",
    )
    key_judgments: DraftLimits | None = Field(
        None, description="How many key judgments the team's reports carry, if consistent"
    )
    analysis_max_words: int | None = Field(
        None, ge=50, description="A word limit for the analysis if the reports are consistently short"
    )
    heading_style: Literal["plain", "numbered"] = "plain"
    handling_markings: list[str] = Field(
        default_factory=list,
        description="Handling markings seen in the reports that the pack's lexicon lacks",
    )
    source_descriptors: list[str] = Field(
        default_factory=list,
        description="Source descriptor phrases the reports use that the lexicon lacks",
    )
    disable: list[str] = Field(
        default_factory=list,
        description="Rule ids the team's reports never meet by design; use sparingly",
    )
    override: list[DraftRuleOverride] = Field(
        default_factory=list, description="Rules whose severity the team treats differently"
    )
```

Check for an import cycle: `corelata.standards.schema` imports `corelata.schema.report` (for `Confidence`), and `corelata.schema.__init__` would now import `corelata.schema.profiler`, which imports `corelata.standards.schema`. `corelata.standards.schema` imports `from corelata.schema.report import Confidence` — a submodule import, which triggers `corelata.schema.__init__`. If this cycles, define `Severity` use in `profiler.py` via a local `Literal["blocking", "major", "minor"]` instead of importing `Severity`, and convert in Task 6's `to_profile` (`Severity(o.severity)`). Prefer the `Literal` to be safe; the tests above accept either since `"major"` validates in both.

Export from `engine/corelata/schema/__init__.py`: add `from corelata.schema.profiler import DraftLimits, DraftRuleOverride, ProfileDraft` in alphabetical position and the three names to `__all__` if one exists.

- [ ] **Step 4: The prompt**

`engine/corelata/prompts/templates/profiler/v1.j2`:

```
You are the profiler for an intelligence reporting team: you read a team's finished reports and describe how they differ from the base standard, so the writer and reviewers can match the team's house style.
INPUT_JSON.pack is the standards pack the profile will extend: its rule ids and titles, its template limits, and the handling markings, source descriptors and likelihood terms its lexicon already has. INPUT_JSON.reports are the team's example reports, one object per report with its passages in order ("truncated" is true when a long report was cut).
Return one JSON object:
- observations: what the reports share, one sentence each — structure and section order, typical length, voice, how judgments are phrased, markings and classification lines, how sources are described. Only what you can see in the passages.
- tone: guidance a writer would follow to sound like this team, written as instructions ("Lead with ...", "Keep ... under ..."). Do not restate the standard; describe the house style.
- key_judgments: {min, max} only if the reports consistently carry a number of key judgments; otherwise null.
- analysis_max_words: a limit only if the reports are consistently short; otherwise null.
- heading_style: "numbered" if the reports number their headings, else "plain".
- handling_markings: markings seen in the reports that are not in INPUT_JSON.pack.lexicon.handling_markings, exactly as written.
- source_descriptors: descriptor phrases the reports use for sources that the lexicon lacks.
- disable: rule ids from INPUT_JSON.pack.rule_ids the reports never satisfy by design (for example a team that never discusses alternatives). Use sparingly; an empty list is normal.
- override: rules from INPUT_JSON.pack.rule_ids the team treats more or less strictly, each with a severity of blocking, major or minor.
Use only rule ids that appear in INPUT_JSON.pack.rule_ids. Respond with a single JSON object only.
```

In `engine/corelata/prompts/check.py` add `("profiler", {})` to `_CHECKS` (after `("auditor", {})`). `run_prompt_ids()` is unchanged (Global Constraints).

- [ ] **Step 5: The synthetic handler**

In `engine/corelata/testing/synthetic.py`:

```python
import re

BLUF, CHART, NOALT, BADRULE = "BLUF", "CHART", "NOALT", "BADRULE"
_MARKING = re.compile(r"^[A-Z]+(//[A-Z][A-Z /,-]*)+$")
_NUMBERED = re.compile(r"^\d+\.\s")


def _profiler(p: Payload) -> Payload:
    reports = p.get("reports", [])
    units = [u for r in reports for u in r.get("units", [])]
    known = set(p.get("pack", {}).get("lexicon", {}).get("handling_markings", []))
    markings: list[str] = []
    for u in units:
        if _MARKING.match(u.strip()) and u.strip() not in known and u.strip() not in markings:
            markings.append(u.strip())
    tone = "Lead with the key judgments; one idea per paragraph; cite every source."
    if any(BLUF in u for u in units):
        tone += " Open with a bottom line up front."
    disable: list[str] = []
    if any(NOALT in u for u in units):
        disable.append("icd203.tc.4")
    if any(BADRULE in u for u in units):
        disable = ["nope.rule.1"]
    return {
        "observations": [f"{len(reports)} example reports read", f"{len(units)} passages in total"],
        "tone": tone,
        "key_judgments": {"min": 1, "max": 3}
        if any("key judgment" in u.casefold() for u in units)
        else None,
        "analysis_max_words": None,
        "heading_style": "numbered" if any(_NUMBERED.match(u) for u in units) else "plain",
        "handling_markings": markings,
        "source_descriptors": [],
        "disable": disable,
        "override": [{"id": "icd203.tc.9", "severity": "major"}]
        if any(CHART in u for u in units)
        else [],
    }
```

Register `"profiler": _profiler` in `_HANDLERS` and extend the module docstring with the new markers (BLUF, CHART, NOALT, BADRULE).

- [ ] **Step 6: Run the tests**

Run: `cd engine && uv run pytest tests/schema tests/testing tests/prompts -q --no-cov`
Expected: pass (including `test_builtin_templates_render[profiler-...]`).

- [ ] **Step 7: Commit**

```bash
git add engine/corelata/schema/profiler.py engine/corelata/schema/__init__.py engine/corelata/prompts/templates/profiler/v1.j2 engine/corelata/prompts/check.py engine/corelata/testing/synthetic.py engine/tests/schema/test_profiler.py engine/tests/testing
git commit -F /path/to/message   # "feat: the profiler's output schema, prompt and synthetic answer"
```

---

### Task 6: The extractor

**Files:**
- Create: `engine/corelata/profiler.py`
- Modify: `engine/corelata/standards/loader.py` (add `resolve_profile`)
- Test: `engine/tests/test_profiler.py`, `engine/tests/standards/test_loader.py` (one test for `resolve_profile`)

**Interfaces:**
- Consumes: `ProfileDraft`, `DraftLimits`, `DraftRuleOverride` (Task 5); `AgentRunner`, `CallLog`, `StructuredOutputError` (`corelata.llm.agent`); `make_source` (`corelata.ingest.units`); `check_supported` (`corelata.ingest.registry`); `estimate_tokens` (`corelata.stages.context`); `load_pack`, `PackError` (loader); `Profile`, `ProfileRules`, `RuleOverride`, `TemplateOverride`, `ItemLimits`, `ProfileFormat`, `LexiconAdditions`, `ResolvedPack`, `Severity` (`corelata.standards.schema`); `ConfigError`.
- Produces (used by Task 7):

```python
@dataclass
class ExampleReport:
    name: str
    units: list[str]
    truncated: bool

def read_examples(directory: Path, *, budget_tokens: int, bytes_per_token: float) -> list[ExampleReport]
def check_draft(draft: ProfileDraft, base: ResolvedPack) -> list[str]
def to_profile(draft: ProfileDraft, base: ResolvedPack, *, name: str, extends: str) -> Profile
class ProfileExtraction(BaseModel): profile: Profile; observations: list[str]; examples: list[str]; model: str
async def extract_profile(cfg, *, backends, prompts, log, examples, name, extends, packs_dir) -> ProfileExtraction
def profile_yaml(extraction: ProfileExtraction, *, written_at: datetime) -> str
```

and in the loader: `def resolve_profile(profile: Profile, *, packs_dir: Path | None = None) -> ResolvedPack`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_profiler.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from corelata.config import ConfigError
from corelata.ingest.base import IngestError
from corelata.llm.agent import CallLog, StructuredOutputError
from corelata.profiler import (
    ExampleReport,
    ProfileExtraction,
    check_draft,
    extract_profile,
    profile_yaml,
    read_examples,
    to_profile,
)
from corelata.prompts.library import PromptLibrary
from corelata.schema import DraftLimits, DraftRuleOverride, ProfileDraft
from corelata.standards.loader import load_pack, resolve_profile
from corelata.standards.schema import Profile
from corelata.testing.fake_backend import FakeBackend

REPORT = [
    "UNCLASSIFIED//FOUO",
    "1. Key Judgments",
    "BLUF: Varna's container capacity expansion matters to shippers.",
    "We assess it is likely that traffic keeps rising.",
    "2. Analysis",
    "The port of Varna expanded its container capacity in 2025.",
]


@pytest.fixture
def examples_dir(tmp_path) -> Path:
    d = tmp_path / "examples"
    d.mkdir()
    for i in range(1, 4):
        (d / f"report-{i}.md").write_text("\n\n".join(REPORT), encoding="utf-8")
    (d / ".DS_Store").write_bytes(b"\x00")  # hidden files are skipped
    return d


@pytest.fixture
def profiler_config(make_config):
    return make_config(
        roles={
            "gate": {"model": "model-a"},
            "writer": {"model": "model-a"},
            "conveyor": {"model": "model-b"},
            "auditor": {"model": "model-b"},
            "profiler": {"model": "model-b"},
        }
    )


def test_read_examples_in_name_order_within_budget(examples_dir):
    reports = read_examples(examples_dir, budget_tokens=100_000, bytes_per_token=2.5)
    assert [r.name for r in reports] == ["report-1.md", "report-2.md", "report-3.md"]
    assert reports[0].units[0] == "UNCLASSIFIED//FOUO" and not reports[0].truncated
    assert len(reports[0].units) == 6
    small = read_examples(examples_dir, budget_tokens=60, bytes_per_token=2.5)
    assert all(r.truncated for r in small)
    assert all(1 <= len(r.units) < 6 for r in small)  # at least one unit per report, always


def test_read_examples_errors(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(IngestError, match="no example reports in"):
        read_examples(empty, budget_tokens=100, bytes_per_token=2.5)
    (empty / "a.xyz").write_text("x")
    with pytest.raises(IngestError, match=r"a\.xyz"):
        read_examples(empty, budget_tokens=100, bytes_per_token=2.5)
    with pytest.raises(IngestError, match="not a directory"):
        read_examples(tmp_path / "missing", budget_tokens=100, bytes_per_token=2.5)


def test_check_draft_names_every_problem():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"], tone="t",
        disable=["icd203.tc.4", "nope.rule.1"],
        override=[DraftRuleOverride(id="icd203.tc.4", severity="minor"),
                  DraftRuleOverride(id="bogus.id", severity="major")],
    )
    problems = check_draft(draft, base)
    assert problems == [
        "disable: unknown rule id 'nope.rule.1'",
        "override: unknown rule id 'bogus.id'",
        "rule 'icd203.tc.4' is both disabled and overridden; choose one",
    ]
    assert check_draft(ProfileDraft(observations=["x"], tone="t"), base) == []


def test_to_profile_is_a_draft_that_resolves():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"], tone="Be brief.",
        key_judgments=DraftLimits(min=1, max=3), analysis_max_words=800,
        heading_style="numbered",
        handling_markings=["UNCLASSIFIED", "UNCLASSIFIED//FOUO", "UNCLASSIFIED//FOUO"],
        source_descriptors=["a liaison service"],
        disable=["icd203.tc.4"],
        override=[DraftRuleOverride(id="icd203.tc.9", severity="major")],
    )
    profile = to_profile(draft, base, name="team-east", extends="icd203-base")
    assert profile.draft is True and profile.name == "team-east"
    assert profile.tone == "Be brief." and profile.format.heading_style == "numbered"
    assert profile.template is not None and profile.template.key_judgments.max == 3
    assert profile.template.analysis_max_words == 800
    assert profile.lexicon.handling_markings == ["UNCLASSIFIED//FOUO"]  # already-known dropped, deduped
    assert profile.rules.disable == ["icd203.tc.4"]
    assert profile.rules.override[0].id == "icd203.tc.9" and profile.rules.override[0].severity == "major"
    resolved = resolve_profile(profile)
    assert "icd203.tc.4" not in resolved.rule_ids()
    assert resolved.rule("icd203.tc.9").severity == "major"
    assert resolved.profile == "team-east"
    bare = to_profile(ProfileDraft(observations=["x"], tone="t"), base, name="n", extends="icd203-base")
    assert bare.template is None and bare.lexicon.handling_markings == []


async def test_extract_profile_end_to_end(profiler_config, examples_dir):
    examples = read_examples(examples_dir, budget_tokens=16000, bytes_per_token=2.5)
    backend = FakeBackend(name="fake")
    log = CallLog()
    extraction = await extract_profile(
        profiler_config, backends={"fake": backend}, prompts=PromptLibrary(), log=log,
        examples=examples, name="team-east", extends="icd203-base", packs_dir=None,
    )
    assert extraction.profile.draft and extraction.profile.name == "team-east"
    assert extraction.profile.lexicon.handling_markings == ["UNCLASSIFIED//FOUO"]
    assert extraction.profile.format.heading_style == "numbered"
    assert extraction.observations[0] == "3 example reports read"
    assert extraction.examples == ["report-1.md", "report-2.md", "report-3.md"]
    assert extraction.model == "model-b"
    assert log.usage().by_role.keys() == {"profiler"}
    request = backend.requests[0]
    assert request.schema_name == "ProfileDraft"
    assert "icd203.tc.8" in request.messages[1].content  # the pack's rule ids are shown


async def test_extract_profile_requires_the_role_and_a_known_pack(make_config, profiler_config, examples_dir):
    examples = read_examples(examples_dir, budget_tokens=16000, bytes_per_token=2.5)
    with pytest.raises(ConfigError, match="roles.profiler"):
        await extract_profile(
            make_config(), backends={"fake": FakeBackend()}, prompts=PromptLibrary(),
            log=CallLog(), examples=examples, name="n", extends="icd203-base", packs_dir=None,
        )
    from corelata.standards.loader import PackError

    with pytest.raises(PackError, match="nope"):
        await extract_profile(
            profiler_config, backends={"fake": FakeBackend()}, prompts=PromptLibrary(),
            log=CallLog(), examples=examples, name="n", extends="nope", packs_dir=None,
        )


async def test_extract_profile_invalid_draft_gets_one_repair_then_fails(profiler_config, tmp_path):
    d = tmp_path / "ex"
    d.mkdir()
    (d / "r.md").write_text("BADRULE everywhere.\n")
    examples = read_examples(d, budget_tokens=1000, bytes_per_token=2.5)
    backend = FakeBackend(name="fake")
    with pytest.raises(StructuredOutputError, match="unknown rule id 'nope.rule.1'"):
        await extract_profile(
            profiler_config, backends={"fake": backend}, prompts=PromptLibrary(), log=CallLog(),
            examples=examples, name="n", extends="icd203-base", packs_dir=None,
        )
    assert len(backend.requests) == 2  # first answer + one repair turn


def test_profile_yaml_round_trips_with_a_review_header():
    base = load_pack("icd203-base")
    draft = ProfileDraft(observations=["Three reports.", "Numbered headings."], tone="Be brief.",
                         heading_style="numbered", handling_markings=["UNCLASSIFIED//FOUO"])
    extraction = ProfileExtraction(
        profile=to_profile(draft, base, name="team-east", extends="icd203-base"),
        observations=draft.observations, examples=["a.md", "b.docx", "c.md"], model="strong",
    )
    text = profile_yaml(extraction, written_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    head, body = text.split("\n\n", 1)
    assert head.startswith("# Draft profile written by `corelata profile extract` on 2026-10-14")
    assert "#   - a.md" in head and "#   - c.md" in head and "# Model: strong" in head
    assert "#   - Three reports." in head
    assert "set `draft: false`" in head
    assert all(line.startswith("#") for line in head.splitlines())
    data = yaml.safe_load(body)
    assert list(data)[:3] == ["name", "extends", "draft"] and data["draft"] is True
    assert Profile.model_validate(data) == extraction.profile
    assert "rules:" not in body or data.get("rules")  # defaults are not written
    assert "docx_reference" not in body
```

Add to the loader tests:

```python
def test_resolve_profile_resolves_against_the_chain():
    from corelata.standards.loader import resolve_profile
    from corelata.standards.schema import Profile

    profile = Profile(name="p", extends="icd203-base", draft=True, tone="x")
    resolved = resolve_profile(profile)
    assert resolved.profile == "p" and resolved.tone == "x" and len(resolved.rules) == 17
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/test_profiler.py -q --no-cov`
Expected: FAIL with `ModuleNotFoundError: corelata.profiler`.

- [ ] **Step 3: `resolve_profile` in the loader**

In `engine/corelata/standards/loader.py`, after `load_pack`:

```python
def resolve_profile(profile: Profile, *, packs_dir: Path | None = None) -> ResolvedPack:
    """Resolve a profile that is not (yet) in any pack directory against the pack it extends
    (`corelata profile extract` proves its draft loads before writing it)."""
    return resolve(_chain(profile.extends, packs_dir), profile)
```

- [ ] **Step 4: The extractor**

`engine/corelata/profiler.py`:

```python
"""`corelata profile extract` (spec §4.4, §6.5, §6.8): draft a team profile from example
reports. The profiler is the fifth role; it is never used in a run, and what it writes is a
draft a human must approve (`draft: true`)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from corelata.config import ConfigError, CorelataConfig
from corelata.ingest.base import IngestError
from corelata.ingest.registry import check_supported
from corelata.ingest.units import make_source
from corelata.llm.agent import AgentRunner, CallLog
from corelata.llm.types import Backend
from corelata.prompts.library import PromptLibrary
from corelata.schema import ProfileDraft
from corelata.stages.context import estimate_tokens
from corelata.standards.loader import load_pack, resolve_profile
from corelata.standards.schema import (
    ItemLimits,
    LexiconAdditions,
    Profile,
    ProfileFormat,
    ProfileRules,
    ResolvedPack,
    RuleOverride,
    Severity,
    TemplateOverride,
)


@dataclass
class ExampleReport:
    name: str
    units: list[str]
    truncated: bool


def read_examples(
    directory: Path, *, budget_tokens: int, bytes_per_token: float
) -> list[ExampleReport]:
    """Every regular, non-hidden file in `directory`, in name order, read through the ingestors
    and cut to an even share of `budget_tokens` (at least one unit each). Unsupported or
    unreadable files raise IngestError naming the file, before any model call."""
    if not directory.is_dir():
        raise IngestError(f"not a directory: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise IngestError(f"no example reports in {directory}")
    for path in files:
        try:
            check_supported(path)
        except IngestError as e:  # the registry's message names the extension, not the file
            raise IngestError(f"{path.name}: {e}") from e
    share = max(budget_tokens // len(files), 1)
    reports: list[ExampleReport] = []
    for i, path in enumerate(files, 1):
        source = make_source(f"ex{i}", path)
        units: list[str] = []
        spent = 0
        for unit in source.units:
            cost = estimate_tokens(unit.text, bytes_per_token)
            if units and spent + cost > share:
                break
            units.append(unit.text)
            spent += cost
        reports.append(ExampleReport(path.name, units, truncated=len(units) < len(source.units)))
    return reports


def check_draft(draft: ProfileDraft, base: ResolvedPack) -> list[str]:
    """Problems the model must repair: unknown rule ids, a rule both disabled and overridden."""
    known = set(base.rule_ids())
    problems = [f"disable: unknown rule id '{r}'" for r in draft.disable if r not in known]
    problems += [f"override: unknown rule id '{o.id}'" for o in draft.override if o.id not in known]
    both = sorted(set(draft.disable) & {o.id for o in draft.override})
    problems += [f"rule '{r}' is both disabled and overridden; choose one" for r in both]
    return problems


def _new(items: list[str], known: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in known and item not in out:
            out.append(item)
    return out


def to_profile(draft: ProfileDraft, base: ResolvedPack, *, name: str, extends: str) -> Profile:
    template = None
    if draft.key_judgments is not None or draft.analysis_max_words is not None:
        template = TemplateOverride(
            key_judgments=ItemLimits(min=draft.key_judgments.min, max=draft.key_judgments.max)
            if draft.key_judgments is not None
            else None,
            analysis_max_words=draft.analysis_max_words,
        )
    return Profile(
        name=name,
        extends=extends,
        draft=True,
        rules=ProfileRules(
            disable=list(draft.disable),
            override=[RuleOverride(id=o.id, severity=Severity(o.severity)) for o in draft.override],
        ),
        template=template,
        tone=draft.tone.strip(),
        format=ProfileFormat(heading_style=draft.heading_style),
        lexicon=LexiconAdditions(
            handling_markings=_new(draft.handling_markings, base.lexicon.handling_markings),
            source_descriptors=_new(draft.source_descriptors, base.lexicon.source_descriptors),
        ),
    )


class ProfileExtraction(BaseModel):
    profile: Profile
    observations: list[str]
    examples: list[str]  # file names, in the order shown to the model
    model: str  # the model key of the profiler role


async def extract_profile(
    cfg: CorelataConfig,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    examples: list[ExampleReport],
    name: str,
    extends: str,
    packs_dir: Path | None,
) -> ProfileExtraction:
    if cfg.roles.profiler is None:
        raise ConfigError(
            "roles.profiler is not configured; add `profiler: {model: <key>}` under roles"
        )
    base = load_pack(extends, packs_dir=packs_dir)
    model_key = cfg.roles.model_for("profiler")
    runner = AgentRunner(cfg, backends, prompts, log)
    draft = await runner.run(
        role="profiler",
        model_key=model_key,
        prompt_id="profiler",
        prompt_vars={},
        payload={
            "task": "profiler",
            "pack": {
                "name": base.name,
                "version": base.version,
                "rule_ids": base.rule_ids(),
                "rules": [
                    {"id": r.id, "title": r.title, "severity": r.severity.value}
                    for r in base.rules
                ],
                "template": base.template.model_dump(mode="json"),
                "lexicon": {
                    "handling_markings": base.lexicon.handling_markings,
                    "source_descriptors": base.lexicon.source_descriptors,
                    "likelihood_terms": sorted(base.lexicon.terms()),
                },
            },
            "reports": [
                {"name": r.name, "units": r.units, "truncated": r.truncated} for r in examples
            ],
        },
        output_type=ProfileDraft,
        validate=lambda d: check_draft(d, base),
    )
    profile = to_profile(draft, base, name=name, extends=extends)
    resolve_profile(profile, packs_dir=packs_dir)  # a draft that cannot load is a bug here
    return ProfileExtraction(
        profile=profile,
        observations=draft.observations,
        examples=[r.name for r in examples],
        model=model_key,
    )


def profile_yaml(extraction: ProfileExtraction, *, written_at: datetime) -> str:
    """Commented YAML: provenance and observations for the reviewer, then the profile with
    `name`, `extends`, `draft` first and defaults left out."""
    p = extraction.profile
    head = [
        f"# Draft profile written by `corelata profile extract` on {written_at:%Y-%m-%d} "
        f"from {len(extraction.examples)} example reports:",
        *[f"#   - {name}" for name in extraction.examples],
        f"# Model: {extraction.model}. Observations:",
        *[f"#   - {o}" for o in extraction.observations],
        "# Review every line, then set `draft: false` to let runs use this profile.",
    ]
    body = {"name": p.name, "extends": p.extends, "draft": True}
    rest = p.model_dump(mode="json", exclude_defaults=True, exclude={"name", "extends", "draft"})
    body.update(rest)
    return "\n".join(head) + "\n\n" + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
```

Check `exclude_defaults=True` keeps `format: {heading_style: numbered}` (non-default) and drops `format` entirely when plain, and that `Profile.model_validate(data)` of the dumped body equals the profile (pydantic compares field values; a `Path | None` `docx_reference` stays `None`). If `Severity(o.severity)` is redundant because Task 5 used the enum, keep it (harmless).

- [ ] **Step 5: Run the tests**

Run: `cd engine && uv run pytest tests/test_profiler.py tests/standards -q --no-cov`
Expected: pass. If `test_read_examples_in_name_order_within_budget`'s `small` assertion fails because the Markdown ingestor merges paragraphs differently, adjust the fixture's `REPORT` lines so each becomes its own unit (blank lines between them already do that) and keep the assertions.

- [ ] **Step 6: Commit**

```bash
git add engine/corelata/profiler.py engine/corelata/standards/loader.py engine/tests/test_profiler.py engine/tests/standards
git commit -F /path/to/message   # "feat: the profile extractor"
```

---

### Task 7: `corelata profile extract`

**Files:**
- Modify: `engine/corelata/cli.py` (parser, dispatch, `_profile`)
- Test: `engine/tests/test_cli_profile.py`

**Interfaces:**
- Consumes: Task 6's `read_examples`, `extract_profile`, `profile_yaml`; `StructuredOutputError` and `AGENT_FAILURES` from `corelata.llm.agent`; `PackError`; `IngestError`; `ConfigError`; `build_backends`; `validate_prompts`; `PromptLibrary`; `utcnow`.
- Produces the command

```
corelata profile extract --from DIR --out FILE [--name NAME] [--extends PACK] [--packs-dir DIR]
                         [--budget-tokens N] [--force] [--config FILE]
```

`--name` defaults to the `--out` file's stem and must match `^[a-z0-9][a-z0-9\-]*$`; `--extends` defaults to `standards.default_pack`; `--packs-dir` defaults to `standards.packs_dir`; `--budget-tokens` defaults to `pipeline.writer_unit_budget_tokens`. Exit 0 written; 1 the model could not produce a valid draft (after the repair turn) or failed; 2 usage, config, pack or ingest error, or `--out` exists without `--force`. On success prints `wrote <out> (draft profile '<name>' extends '<pack>'; <n> observations)` and the observations, one per line, to stdout.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_cli_profile.py`:

```python
import shutil
from pathlib import Path

import pytest
import yaml

from corelata.cli import main
from corelata.standards.loader import BUILTIN_PACKS_DIR, PackError, load_pack, validate_pack
from corelata.standards.schema import Profile
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG

REPORT = [
    "UNCLASSIFIED//FOUO",
    "1. Key Judgments",
    "BLUF: Varna's container capacity expansion matters to shippers.",
    "The port of Varna expanded its container capacity in 2025.",
]


@pytest.fixture
def fake_server():
    with FakeOpenAIServer() as server:
        yield server


@pytest.fixture
def config_path(tmp_path, fake_server) -> Path:
    data = {
        **BASE_CONFIG,
        "backends": {"fake": {"base_url": fake_server.base_url}},
        "roles": {**BASE_CONFIG["roles"], "profiler": {"model": "model-b"}},
    }
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def examples(tmp_path) -> Path:
    d = tmp_path / "examples"
    d.mkdir()
    for i in range(1, 4):
        (d / f"report-{i}.md").write_text("\n\n".join(REPORT), encoding="utf-8")
    return d


def test_extract_three_example_reports_produce_a_valid_draft_profile(
    config_path, examples, tmp_path, capsys, fake_server
):
    out = tmp_path / "team-east.yaml"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples), "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert captured.out.startswith(f"wrote {out} (draft profile 'team-east' extends 'icd203-base'; 2 observations)")
    assert "3 example reports read" in captured.out
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Draft profile written by `corelata profile extract`")
    data = yaml.safe_load(text)
    profile = Profile.model_validate(data)
    assert profile.draft and profile.extends == "icd203-base"
    assert profile.format.heading_style == "numbered"
    assert profile.lexicon.handling_markings == ["UNCLASSIFIED//FOUO"]
    # the §14 exit test: placed in a pack's profiles/, it validates (as a draft) and is refused for a run
    pack_dir = tmp_path / "packs" / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", pack_dir)
    (pack_dir / "profiles").mkdir()
    shutil.copy(out, pack_dir / "profiles" / "team-east.yaml")
    issues = validate_pack(str(pack_dir))
    assert [(i.level, i.message) for i in issues] == [("warning", "profile 'team-east' is a draft")]
    with pytest.raises(PackError, match="draft"):
        load_pack("icd203-base", packs_dir=pack_dir.parent, profile="team-east")
    resolved = load_pack("icd203-base", packs_dir=pack_dir.parent, profile="team-east", allow_draft=True)
    assert resolved.tone.startswith("Lead with the key judgments")
    assert len(fake_server.requests) == 1  # one profiler call, no repair


def test_extract_refuses_to_overwrite_without_force(config_path, examples, tmp_path, capsys):
    out = tmp_path / "team.yaml"
    out.write_text("name: team\nextends: icd203-base\n")
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples), "--out", str(out)])
    assert rc == 2 and "--force" in capsys.readouterr().err
    assert out.read_text() == "name: team\nextends: icd203-base\n"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(out), "--force"])
    assert rc == 0 and yaml.safe_load(out.read_text())["draft"] is True


def test_extract_name_and_extends_options(config_path, examples, tmp_path, capsys):
    out = tmp_path / "x.yaml"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(out), "--name", "team-west", "--extends", "icd203-base"])
    assert rc == 0
    assert yaml.safe_load(out.read_text())["name"] == "team-west"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(tmp_path / "Bad Name.yaml")])
    assert rc == 2 and "--name" in capsys.readouterr().err
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(tmp_path / "y.yaml"), "--extends", "nope"])
    assert rc == 2 and "nope" in capsys.readouterr().err


def test_extract_unsupported_example_is_a_usage_error_before_any_call(
    config_path, examples, tmp_path, capsys, fake_server
):
    (examples / "notes.xyz").write_text("x")
    out = tmp_path / "t.yaml"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples), "--out", str(out)])
    assert rc == 2
    assert "notes.xyz" in capsys.readouterr().err
    assert not out.exists() and fake_server.requests == []


def test_extract_invalid_draft_twice_exits_1_and_writes_nothing(config_path, tmp_path, capsys, fake_server):
    d = tmp_path / "ex"
    d.mkdir()
    (d / "r.md").write_text("BADRULE everywhere.\n")
    out = tmp_path / "t.yaml"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(d), "--out", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown rule id 'nope.rule.1'" in err and not out.exists()
    assert len(fake_server.requests) == 2


def test_extract_without_profiler_role_is_a_config_error(tmp_path, examples, fake_server, capsys):
    data = {**BASE_CONFIG, "backends": {"fake": {"base_url": fake_server.base_url}}}
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(data))
    rc = main(["profile", "extract", "--config", str(cfg), "--from", str(examples), "--out", str(tmp_path / "t.yaml")])
    assert rc == 2 and "roles.profiler" in capsys.readouterr().err


def test_extract_out_parent_missing_and_budget_option(config_path, examples, tmp_path, capsys):
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(tmp_path / "nowhere" / "t.yaml")])
    assert rc == 2 and "nowhere" in capsys.readouterr().err
    out = tmp_path / "small.yaml"
    rc = main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
               "--out", str(out), "--budget-tokens", "30"])
    assert rc == 0 and out.exists()
    assert main(["profile", "extract", "--config", str(config_path), "--from", str(examples),
                 "--out", str(tmp_path / "z.yaml"), "--budget-tokens", "0"]) == 2
```

`BUILTIN_PACKS_DIR` exists in `corelata/standards/loader.py` (used by `list_packs`); import it as shown.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/test_cli_profile.py -q --no-cov`
Expected: FAIL (argparse: invalid choice 'profile').

- [ ] **Step 3: The command**

In `engine/corelata/cli.py`:

Imports (sorted): `import re`; `from corelata.llm.agent import AGENT_FAILURES, CallLog` (extend the existing CallLog import); `from corelata.pipeline import RunOptions, discover, load_run_pack, run_report, utcnow` (extend); `from corelata.profiler import extract_profile, profile_yaml, read_examples`.

Parser (after `pack`):

```python
    profile = sub.add_parser("profile", help="team profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    ext = profile_sub.add_parser("extract", help="draft a team profile from example reports")
    ext.add_argument("--from", dest="from_dir", type=Path, required=True, help="directory of example reports")
    ext.add_argument("--out", type=Path, required=True, help="profile YAML to write")
    ext.add_argument("--name", help="profile name (default: the --out file's stem)")
    ext.add_argument("--extends", help="pack to extend (default: standards.default_pack)")
    ext.add_argument("--packs-dir", type=Path, help="default: standards.packs_dir")
    ext.add_argument("--budget-tokens", type=int, help="passages budget across all reports (default: pipeline.writer_unit_budget_tokens)")
    ext.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ext.add_argument("--config", type=Path, default=default_config_path())
```

Dispatch: `if args.command == "profile": return _profile(args)`.

Handler:

```python
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _profile(args: argparse.Namespace) -> int:
    name = args.name or args.out.stem
    if not _PROFILE_NAME.match(name):
        return _usage(f"--name '{name}' must match {_PROFILE_NAME.pattern} (lowercase, digits, dashes)")
    if args.out.exists() and not args.force:
        return _usage(f"{args.out} exists; pass --force to overwrite it")
    if not args.out.parent.is_dir():
        return _usage(f"the directory of --out does not exist: {args.out.parent}")
    if args.budget_tokens is not None and args.budget_tokens < 1:
        return _usage("--budget-tokens must be at least 1")
    try:
        cfg, issues = load_config(args.config)
        for issue in issues:
            print(f"{issue.level}: {issue.message}", file=sys.stderr)
        prompts = PromptLibrary(cfg.prompts_dir)
        validate_prompts(cfg, prompts)
        if cfg.roles.profiler is None:
            raise ConfigError(
                "roles.profiler is not configured; add `profiler: {model: <key>}` under roles"
            )
        model = cfg.models[cfg.roles.model_for("profiler")]
        examples = read_examples(
            args.from_dir,
            budget_tokens=args.budget_tokens or cfg.pipeline.writer_unit_budget_tokens,
            bytes_per_token=model.bytes_per_token,
        )
        extends = args.extends or cfg.standards.default_pack
        packs_dir = args.packs_dir if args.packs_dir is not None else cfg.standards.packs_dir
        backends = build_backends(cfg)
    except (ConfigError, IngestError, OSError) as e:
        return _usage(str(e))
    log = CallLog(store_io=False)

    async def go():
        try:
            return await extract_profile(
                cfg,
                backends=backends,
                prompts=prompts,
                log=log,
                examples=examples,
                name=name,
                extends=extends,
                packs_dir=packs_dir,
            )
        finally:
            for backend in backends.values():
                await backend.aclose()

    try:
        extraction = asyncio.run(go())
    except PackError as e:
        return _usage(str(e))
    except AGENT_FAILURES as e:  # (StructuredOutputError, BackendError)
        print(f"error: the profiler could not produce a valid draft: {e}", file=sys.stderr)
        return EXIT_FAILED
    args.out.write_text(profile_yaml(extraction, written_at=utcnow()), encoding="utf-8")
    print(
        f"wrote {args.out} (draft profile '{name}' extends '{extends}'; "
        f"{len(extraction.observations)} observations)"
    )
    for observation in extraction.observations:
        print(f"  - {observation}")
    return EXIT_OK
```

`AGENT_FAILURES` in `corelata/llm/agent.py` is `(StructuredOutputError, BackendError)`, so the import of `StructuredOutputError` is only needed if you reference it elsewhere. The `--budget-tokens 30` test expects success: `read_examples` keeps at least one unit per report, so a tiny budget still works.

- [ ] **Step 4: Run the tests, the whole engine suite and lint**

Run: `cd engine && uv run pytest tests/test_cli_profile.py -q --no-cov`
Expected: pass.

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: pass, coverage ≥ 95%.

- [ ] **Step 5: Commit**

```bash
git add engine/corelata/cli.py engine/tests/test_cli_profile.py
git commit -F /path/to/message   # "feat: corelata profile extract"
```

---

### Task 8: Documentation, follow-ups and spec amendments

**Files:**
- Modify: `README.md` (new "## M6: profiles from examples, and the bench" section before "## Development")
- Modify: `docs/operator-guide.md` (two subsections)
- Modify: `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§6.8, §13, §14 amendments)
- Modify: `docs/m1-followups.md` ("profile extract (M6)" → closed), `docs/m2-followups.md` (the `corelata bench` "Later" bullet → closed), `docs/m5-followups.md` ("M6 … need no packaging change" → one package-data line in the image check)
- Create: `docs/m6-followups.md`

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M6: profiles from examples, and the bench

Two commands for the standards team, both model calls and no database (spec §4.4, §6.8, §13):

    corelata profile extract --from team-east-reports/ --out config/packs/icd203-base/profiles/team-east.yaml
    corelata bench --config corelata.yaml --out bench-2026-10-14/

`profile extract` reads a directory of a team's finished reports (any ingestible format), shows
the `profiler` role the pack the profile will extend, and writes a profile with `draft: true`:
tone guidance, heading style, template limits, extra handling markings and source descriptors,
and any rules the team disables or re-grades. The header comments carry the model's observations.
Review it, then remove `draft: true`; `corelata pack validate` lists a draft as a warning and a
run refuses it. `roles.profiler` must be configured.

`bench` plays the shipped scenario set (`engine/corelata/bench/scenarios/`, or `--scenarios DIR`)
against the configured models and reports agreement with each scenario's expectations: full
agreement (nothing to object to), gate agreement, rule-failure agreement, state agreement, and a
per-rule tally of misses and unexpected failures. `--repeat N` plays each scenario N times;
`--out DIR` keeps `bench.json` and every run's `trace.json`; `--json` prints the report. Exit 0
means full agreement, 3 some disagreement, 1 a run that errored. The scenarios were written for
the synthetic model's markers, so a real model is expected to disagree on some; the bench is
how you measure a model or a prompt change, not a pass/fail gate.
```

- [ ] **Step 2: Operator guide**

Under "### Standards packs", after the paragraph on `draft: true`, add:

```markdown
**Drafting a profile from a team's reports.** Put three or more of the team's finished reports
(`.docx`, `.md`, `.txt`, `.pdf`, `.html`) in a directory inside the files volume, then:

```sh
docker compose cp team-east-reports api:/data/files/team-east-reports
docker compose exec api corelata profile extract \
  --from /data/files/team-east-reports \
  --out /data/files/team-east.yaml
docker compose cp api:/data/files/team-east.yaml config/packs/icd203-base/profiles/team-east.yaml
```

The command needs `roles.profiler` in `config/corelata.yaml` (point it at your strongest model)
and writes a profile with `draft: true` whose header lists the model's observations. It writes to
the files volume because `config/` is mounted read-only inside the containers; the last line
copies the draft into the pack on the host. Review every line, then remove the `draft` flag.
`--extends` picks the pack (default `standards.default_pack`), `--name` the profile name
(default: the file name), `--force` overwrites an existing file; without it an existing profile is
never touched.
```

(`deploy/compose.yaml` mounts `./config:/etc/corelata:ro`; the wording above assumes that.)

Under "## 7. Running it", after the `doctor` command block, add:

```markdown
**Checking a model with the bench.** `corelata bench` plays a set of scenario files (ten ship
with the engine) against the configured models and reports how often the run did what the
scenario expects: gate verdict, failing rules per iteration, final state. Use it when you change
a model, a prompt override or the pack, and compare the numbers with the previous run:

```sh
docker compose exec api corelata bench --out /data/files/bench-$(date +%F)
docker compose exec api corelata bench --only clean-single-source --repeat 3
```

Exit 0 means every run matched, 3 that some disagreed (listed at the end of the report), 1 that a
run could not execute (the scenario's profile is missing, for example). The scenarios were written
for the synthetic model; a real model disagreeing on a few is normal, and the bench is a
measurement, not a gate. A run with ten scenarios makes several dozen model calls.
```

- [ ] **Step 3: Spec amendments**

Append to §6.8 (after the CLI list):

```markdown
*M6 amendment:* `corelata profile extract --from <dir> --out <file> [--name <n>] [--extends <pack>] [--packs-dir <dir>] [--budget-tokens <n>] [--force]`; the output always has `draft: true`; an existing `--out` is never overwritten without `--force`. `corelata bench [--scenarios <dir>] [--only <name>…] [--repeat <n>] [--out <dir>] [--json]` exits 0 on full agreement, 3 on any disagreement, 1 when a run errored.
```

In §13, after the scenario-fixtures bullet:

```markdown
*M6 amendment:* the scenario files ship inside the package at `engine/corelata/bench/scenarios/*.yaml` (not `engine/tests/fixtures/`), so `corelata bench` runs in the deployed image; the tests load them from there. The bench reports full agreement, gate agreement, rule-failure agreement (per audited iteration the scenario specifies) and state agreement, plus a per-rule tally of hits, misses and unexpected failures.
```

In §14, after "M6 may slip past the first customer deployment.":

```markdown
*M6 amendment:* the exit test's "against a hosted open model" half is a manual step: CI proves the extractor and the bench against the synthetic model; the operator guide shows the commands for a real model server.
```

- [ ] **Step 4: Follow-ups**

`docs/m6-followups.md`:

```markdown
# M6 follow-ups

## Divergences from Coglossa

- None: M6 adds no copied module. The bench is Corelata's own (Coglossa's bench scores
  translations with FLORES; the shapes differ).

## Spec deviations

- §13: scenario files moved into the package (`corelata/bench/scenarios/`) so `corelata bench`
  works in the image; recorded in the spec.
- §6.8 / §14: recorded in the spec (flags, exit codes, the manual half of the exit test).
- §4.4 says the profiler "reads example reports"; the implementation also shows it the base
  pack's rule ids, template and lexicon so it proposes only valid overrides.

## Should fix soon

- `profile extract` cuts each report to an even share of the token budget; a team whose
  reports differ greatly in length loses the tail of the long ones. A per-report budget flag or
  a digest pass (as the pipeline does for long sources) would help.
- The profiler proposes `severity` overrides only; `checkability`, `route_to` and added rules
  are left to the reviewer by design (a model inventing rules is worse than none).
- `bench` runs scenarios one at a time; a `--concurrency` flag would speed up a server with
  spare capacity (the backend's `max_concurrency` already bounds load).
- `bench` traces are written with `store_llm_io` off to keep them small; a `--store-io` flag
  would help when diagnosing a disagreement.
- The web app's profile select shows drafts like any profile (M4b); the API's `GET /packs`
  carries `draft`, so the select could mark or hide them.
- `deploy/tests/check-app-image.sh` checks one shipped scenario file; the air-gap test does not
  run `corelata bench` (it would add minutes against the fake model for little proof).

## Later

- Scenarios written for real models (today's ten pin the synthetic responder's markers).
- `corelata pack diff` (§6.8) remains open from M1.
```

Edit `docs/m1-followups.md`: `- profile extract (M6)` → `- profile extract (M6) — **closed in M6** (`corelata profile extract`)`. Edit `docs/m2-followups.md`: the "Later" bullet on `corelata bench` → append ` — **closed in M6**`. Edit `docs/m5-followups.md` "Later": `- M6: `corelata bench` and `profile extract` need no packaging change (same image).` → `- M6 added one package-data path (`bench/scenarios/`) to `check-app-image.sh`; no other packaging change.`

- [ ] **Step 5: Check the commands in the docs exist**

Run: `cd engine && uv run corelata profile extract --help && uv run corelata bench --help`
Expected: both print help with the flags the docs name.

Run: `make deploy-check` (the image-check script changed in Task 1; shellcheck must stay clean).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/operator-guide.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/m1-followups.md docs/m2-followups.md docs/m5-followups.md docs/m6-followups.md
git commit -F /path/to/message   # "docs: M6 README, operator guide, follow-ups and spec amendments"
```

---

## Self-review

- **Spec coverage.** §4.4 profiler row (reads example reports, produces a draft `Profile`, never used in a run): Tasks 5–7 and the Global Constraint on `run_prompt_ids`. §6.5 draft refusal: unchanged loader, pinned in Task 7. §6.8 `profile extract --from --out`: Task 7. §11 `roles.profiler`: already in config; required by Task 6/7. §13 scenario fixtures + `corelata bench` reporting gate and rule-failure agreement: Tasks 1–4. §14 exit tests: extractor from three example reports (Task 7 first test); bench against a hosted model (manual, recorded in Task 8). §10.2 CLI list already names both commands.
- **Placeholders.** None; every step carries its code. The two "check and adjust" notes (import cycle in Task 5, `profile: nope` behaviour in Task 4) tell the implementer what to look at and what to do in either case.
- **Type consistency.** `RunResult.repeat/ok/error/state/status/iterations/duration_s/calls/tokens_in/tokens_out/mismatches/gate_agree/rules_agree/state_agree` used identically in Tasks 2, 3, 4. `run_bench(cfg, scenarios, *, backends, prompts, repeat, out_dir, scenarios_dir, now, clock, progress)` matches between Task 3 and Task 4. `extract_profile(cfg, *, backends, prompts, log, examples, name, extends, packs_dir)` matches between Tasks 6 and 7. `ProfileDraft` field names match between Tasks 5, 6 and the synthetic handler. `resolve_profile(profile, *, packs_dir=None)` matches Tasks 6 and its test.
- **Review Focus.** Each of the five lines names the test that pins it; the tests exist in Tasks 3, 4, 6 and 7.
