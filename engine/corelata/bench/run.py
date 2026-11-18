"""Play scenarios against the configured models. Runs execute up to `concurrency` at a time
(default one; the backend's `max_concurrency` still bounds the server), and `bench.json` is
rewritten after every finished run so an interrupted bench keeps what finished. A run that raises
becomes an error entry and the bench continues; a run whose model calls fail ends `failed` like
any run and is scored as a disagreement."""

import asyncio
import os
import shutil
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


def _write_report(out_dir: Path, report: BenchReport) -> None:
    tmp = out_dir / "bench.json.tmp"  # replace, so a reader never sees a half-written file
    tmp.write_text(dump_json(report.model_dump(mode="json")), encoding="utf-8")
    os.replace(tmp, out_dir / "bench.json")


async def run_bench(
    cfg: CorelataConfig,
    scenarios: list[Scenario],
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    repeat: int = 1,
    concurrency: int = 1,
    store_io: bool = False,
    out_dir: Path | None = None,
    scenarios_dir: Path,
    now: Callable[[], datetime] = utcnow,
    clock: Callable[[], float] = time.monotonic,
    progress: Progress | None = None,
) -> BenchReport:
    started = now()
    bench_t0 = clock()
    tallies: dict[str, RuleTally] = {}
    runs: dict[str, list[RunResult]] = {s.name: [] for s in scenarios}
    if out_dir is not None:  # a re-run into the same directory leaves no stale traces
        for scenario in scenarios:
            for stale in (out_dir / scenario.name).glob("run-*"):
                shutil.rmtree(stale, ignore_errors=True)

    def report() -> BenchReport:
        results = [
            ScenarioResult(
                name=s.name,
                description=s.description,
                runs=sorted(runs[s.name], key=lambda r: r.repeat),
            )
            for s in scenarios
        ]
        return BenchReport(
            corelata_version=__version__,
            started_at=started,
            finished_at=now(),
            config_hash=config_hash(cfg),
            models={
                role: cfg.models[key].name or key
                for role, key in cfg.roles.all_roles()
                if role != "profiler"
            },
            scenarios_dir=str(scenarios_dir),
            repeat=repeat,
            scenarios=results,
            rules={rule_id: tallies[rule_id] for rule_id in sorted(tallies)},
            summary=summarize(results, duration_s=clock() - bench_t0),
        )

    if out_dir is not None:  # a Ctrl-C before the first run ends still leaves a current report
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_report(out_dir, report())

    gate = asyncio.Semaphore(concurrency)

    async def one(scenario: Scenario, k: int) -> None:
        async with gate:
            t0 = clock()
            try:
                record = await run_scenario(
                    scenario,
                    cfg,
                    backends=backends,
                    prompts=prompts,
                    log=CallLog(store_io=store_io),
                    now=now,
                )
            except Exception as e:  # noqa: BLE001 - one broken scenario must not end the bench
                result = error_result(
                    repeat=k,
                    error=" ".join(f"{type(e).__name__}: {e}".split()),
                    duration_s=clock() - t0,
                )
            else:
                result = score_run(
                    scenario, record, repeat=k, duration_s=clock() - t0, tallies=tallies
                )
                if out_dir is not None:
                    _write_trace(
                        out_dir, scenario.name, k, dump_json(record.model_dump(mode="json"))
                    )
            runs[scenario.name].append(result)
            if out_dir is not None:
                _write_report(out_dir, report())
            if progress is not None:
                progress(f"{scenario.name} {k}/{repeat}: {_describe(result)}")

    await asyncio.gather(*(one(s, k) for s in scenarios for k in range(1, repeat + 1)))
    final = report()
    if out_dir is not None:
        _write_report(out_dir, final)
    return final


def exit_code(report: BenchReport) -> int:
    """1 when any run errored, 3 when any run disagreed with its scenario, else 0."""
    if report.summary.errors:
        return 1
    if any(not run.agree for s in report.scenarios for run in s.runs):
        return 3
    return 0
