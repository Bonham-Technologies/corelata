import asyncio
import json
from datetime import UTC, datetime

from corelata import scenarios as scenarios_module
from corelata.bench import SCENARIOS_DIR
from corelata.bench.run import exit_code, run_bench
from corelata.bench.schema import BenchReport
from corelata.llm.types import BackendError
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
    assert report.summary.scenarios == 15 and report.summary.runs == 15
    assert report.summary.errors == 0 and report.summary.full_agreement.ratio == 1.0
    assert report.summary.gate_agreement.total >= 1 and report.summary.rule_agreement.total >= 1
    assert report.models == {
        "gate": "model-a",
        "writer": "model-a",
        "conveyor": "model-b",
        "auditor": "model-b",
    }
    assert report.scenarios_dir == str(SCENARIOS_DIR) and report.repeat == 1
    assert report.started_at == FROZEN and report.corelata_version
    assert exit_code(report) == 0
    assert len(lines) == 15 and lines[0].startswith("badterm-fixed-one-loop 1/1: completed clean")
    trace = tmp_path / "bench" / "clean-single-source" / "run-1" / "trace.json"
    assert json.loads(trace.read_text())["run_id"] == "clean-single-source"
    assert report.rules["icd203.tc.2"].hit >= 1
    BenchReport.model_validate_json(report.model_dump_json())  # round trip


async def test_models_lists_run_roles_only(make_config):
    from tests.conftest import BASE_CONFIG

    cfg = make_config(roles={**BASE_CONFIG["roles"], "profiler": {"model": "model-b"}})
    scenario = load_scenario(SCENARIOS_DIR / "gate-rejected.yaml")
    report = await run_bench(
        cfg,
        [scenario],
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    assert set(report.models) == {"gate", "writer", "conveyor", "auditor"}


async def test_a_rerun_into_the_same_directory_leaves_no_stale_traces(make_config, tmp_path):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    for repeat in (2, 1):
        await run_bench(
            make_config(),
            [scenario],
            backends={"fake": FakeBackend(name="fake")},
            prompts=PromptLibrary(),
            repeat=repeat,
            out_dir=tmp_path,
            scenarios_dir=SCENARIOS_DIR,
            clock=_ticker(),
        )
    assert [p.name for p in (tmp_path / scenario.name).iterdir()] == ["run-1"]


async def test_repeat_runs_each_scenario_n_times(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    report = await run_bench(
        make_config(),
        [scenario],
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        repeat=3,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    assert [r.repeat for r in report.scenarios[0].runs] == [1, 2, 3]
    assert report.summary.runs == 3 and report.repeat == 3


async def test_a_disagreement_is_exit_3(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    wrong = scenario.model_copy(
        update={"expect": scenario.expect.model_copy(update={"status": "findings_open"})}
    )
    report = await run_bench(
        make_config(),
        [wrong],
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    run = report.scenarios[0].runs[0]
    assert run.ok and run.mismatches == ["status: expected 'findings_open', got 'clean'"]
    assert exit_code(report) == 3


async def test_an_exception_in_one_run_does_not_stop_the_bench(make_config, monkeypatch, tmp_path):
    good = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    broken = good.model_copy(update={"name": "broken", "profile": "nope"})
    real = scenarios_module.run_scenario
    message = "profile 'nope' not found in pack 'icd203-base' or its ancestors"

    async def flaky(scenario, cfg, **kw):
        if scenario.name == "broken":
            raise RuntimeError(message)
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", flaky)
    lines: list[str] = []
    report = await run_bench(
        make_config(),
        [broken, good],
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        out_dir=tmp_path,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
        progress=lines.append,
    )
    first, second = report.scenarios
    assert first.name == "broken" and not first.runs[0].ok
    assert first.runs[0].error == f"RuntimeError: {message}"
    assert second.runs[0].agree
    assert report.summary.errors == 1 and exit_code(report) == 1
    assert lines[0] == f"broken 1/1: error: RuntimeError: {message}"
    assert not (tmp_path / "broken").exists() and (tmp_path / "clean-single-source").is_dir()


async def test_a_model_failure_is_a_failed_record_not_an_error(make_config):
    scenario = load_scenario(SCENARIOS_DIR / "clean-single-source.yaml")
    backend = FakeBackend(name="fake")
    for _ in range(6):  # every retry of the gate call fails
        backend.script("gate", BackendError("connection refused"))
    report = await run_bench(
        make_config(),
        [scenario],
        backends={"fake": backend},
        prompts=PromptLibrary(),
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    run = report.scenarios[0].runs[0]
    assert run.ok and run.state == "failed" and not run.agree
    assert report.summary.errors == 0 and exit_code(report) == 3


async def test_bench_json_is_written_after_every_run(make_config, monkeypatch, tmp_path):
    """Ctrl-C half-way must leave the runs that finished (spec §13, M7)."""
    scenarios = [
        load_scenario(SCENARIOS_DIR / "clean-single-source.yaml"),
        load_scenario(SCENARIOS_DIR / "gate-rejected.yaml"),
    ]
    real = scenarios_module.run_scenario
    seen: list[int] = []

    async def spying(scenario, cfg, **kw):
        partial = tmp_path / "bench.json"
        on_disk = (
            BenchReport.model_validate_json(partial.read_text()) if partial.is_file() else None
        )
        seen.append(on_disk.summary.runs if on_disk else 0)
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", spying)
    report = await run_bench(
        make_config(),
        scenarios,
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        out_dir=tmp_path,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    assert seen == [0, 1]  # before the first run none finished; before the second, one run on disk
    assert not (tmp_path / "bench.json.tmp").exists()
    final = BenchReport.model_validate_json((tmp_path / "bench.json").read_text())
    assert final.summary.runs == 2 and final == report


async def test_an_empty_report_exists_before_the_first_run_finishes(
    make_config, monkeypatch, tmp_path
):
    scenarios = [
        load_scenario(SCENARIOS_DIR / "clean-single-source.yaml"),
        load_scenario(SCENARIOS_DIR / "gate-rejected.yaml"),
    ]
    real = scenarios_module.run_scenario
    first: list[BenchReport] = []

    async def spying(scenario, cfg, **kw):
        if not first:
            first.append(BenchReport.model_validate_json((out / "bench.json").read_text()))
        return await real(scenario, cfg, **kw)

    out = tmp_path / "not" / "yet" / "there"  # run_bench creates the directory
    monkeypatch.setattr("corelata.bench.run.run_scenario", spying)
    await run_bench(
        make_config(),
        scenarios,
        backends={"fake": FakeBackend(name="fake")},
        prompts=PromptLibrary(),
        out_dir=out,
        scenarios_dir=SCENARIOS_DIR,
        clock=_ticker(),
    )
    assert first[0].summary.runs == 0
    assert [s.name for s in first[0].scenarios] == [s.name for s in scenarios]
    assert all(s.runs == [] for s in first[0].scenarios)
    assert not (out / "bench.json.tmp").exists()


async def test_concurrency_overlaps_runs_and_keeps_the_order(make_config, monkeypatch):
    names = ["gate-rejected", "clean-single-source", "clean-two-sources"]
    scenarios = [load_scenario(SCENARIOS_DIR / f"{n}.yaml") for n in names]
    broken = scenarios[1].model_copy(update={"name": "broken", "profile": "nope"})
    scenarios.append(broken)
    real = scenarios_module.run_scenario
    in_flight, peak = [0], [0]
    started = asyncio.Event()
    seen: set[str] = set()

    async def overlapping(scenario, cfg, **kw):
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        if in_flight[0] == 3:
            started.set()
        await started.wait()  # every run waits until three are in flight
        try:
            if scenario.name == "broken":
                raise RuntimeError("boom")
            if scenario.name == names[0] and names[0] not in seen:
                seen.add(names[0])
                await asyncio.sleep(0.05)  # the first call finishes after the second
            return await real(scenario, cfg, **kw)
        finally:
            in_flight[0] -= 1

    monkeypatch.setattr("corelata.bench.run.run_scenario", overlapping)
    lines: list[str] = []
    report = await asyncio.wait_for(
        run_bench(
            make_config(),
            scenarios,
            backends={"fake": FakeBackend(name="fake")},
            prompts=PromptLibrary(),
            repeat=2,
            concurrency=3,
            scenarios_dir=SCENARIOS_DIR,
            clock=_ticker(),
            progress=lines.append,
        ),
        30,
    )
    assert peak[0] == 3
    assert [s.name for s in report.scenarios] == [*names, "broken"]
    assert all(
        [r.repeat for r in s.runs] == [1, 2] for s in report.scenarios
    )  # sorted, not as finished
    assert [r.ok for r in report.scenarios[3].runs] == [False, False]
    assert all(r.ok for s in report.scenarios[:3] for r in s.runs)
    assert report.summary.runs == 8 and report.summary.errors == 2 and len(lines) == 8
    assert exit_code(report) == 1


async def test_store_io_keeps_the_model_text_in_the_traces(make_config, tmp_path):
    scenario = load_scenario(SCENARIOS_DIR / "gate-rejected.yaml")
    for store_io in (False, True):
        await run_bench(
            make_config(),
            [scenario],
            backends={"fake": FakeBackend(name="fake")},
            prompts=PromptLibrary(),
            store_io=store_io,
            out_dir=tmp_path / str(store_io),
            scenarios_dir=SCENARIOS_DIR,
            clock=_ticker(),
        )
    calls = {
        store_io: json.loads(
            (tmp_path / str(store_io) / scenario.name / "run-1" / "trace.json").read_text()
        )["llm_calls"]
        for store_io in (False, True)
    }
    assert calls[False] and calls[True]
    assert all(c["request"] is None and c["response"] is None for c in calls[False])
    assert all(c["request"] is not None and c["response"] is not None for c in calls[True])
