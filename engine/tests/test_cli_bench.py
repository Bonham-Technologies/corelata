import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from corelata import cli
from corelata.bench import REAL_SCENARIOS_DIR, SCENARIOS_DIR
from corelata.bench.schema import BenchReport
from corelata.cli import main
from corelata.config import ConfigError
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
    rc = main(
        [
            "bench",
            "--config",
            str(config_path),
            "--only",
            "clean-single-source",
            "--only",
            "gate-rejected",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "full agreement 2/2 (100%)" in captured.out
    assert "gate agreement 2/2 (100%)" in captured.out
    assert "rule-failure agreement 1/1 (100%)" in captured.out
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
    assert "PackError" in captured.out and "nope" in captured.out
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
    argv = ["bench", "--config", str(config_path), "--only", "gate-rejected", "--out", str(f)]
    assert main(argv) == 2
    assert "--out" in capsys.readouterr().err


def test_bench_out_that_cannot_be_created_is_a_usage_error(
    config_path, tmp_path, capsys, fake_server
):
    f = tmp_path / "file"
    f.write_text("x")
    argv = [
        "bench",
        "--config",
        str(config_path),
        "--only",
        "gate-rejected",
        "--out",
        str(f / "sub"),
    ]
    assert main(argv) == 2
    assert "--out" in capsys.readouterr().err
    assert fake_server.requests == []


def test_bench_bad_config(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("nonsense: 1\n")
    assert main(["bench", "--config", str(cfg)]) == 2


def test_bench_backend_build_error_is_a_usage_error(config_path, monkeypatch, capsys):
    def boom(_cfg):
        raise ConfigError("no such backend")

    monkeypatch.setattr(cli, "build_backends", boom)
    assert main(["bench", "--config", str(config_path)]) == 2
    assert "no such backend" in capsys.readouterr().err


def test_bench_prints_config_issues_to_stderr(config_path, monkeypatch, capsys):
    real = cli.load_config

    def with_issue(path):
        cfg, issues = real(path)
        return cfg, [*issues, SimpleNamespace(level="warning", message="heads up")]

    monkeypatch.setattr(cli, "load_config", with_issue)
    assert main(["bench", "--config", str(config_path), "--only", "gate-rejected"]) == 0
    assert "warning: heads up" in capsys.readouterr().err


def test_bench_interrupted_keeps_the_partial_report_and_exits_130(
    config_path, tmp_path, capsys, monkeypatch
):
    from corelata import scenarios as scenarios_module

    real = scenarios_module.run_scenario

    async def interrupting(scenario, cfg, **kw):
        if scenario.name == "gate-rejected":
            raise KeyboardInterrupt
        return await real(scenario, cfg, **kw)

    monkeypatch.setattr("corelata.bench.run.run_scenario", interrupting)
    out = tmp_path / "bench"
    rc = main(
        [
            "bench",
            "--config",
            str(config_path),
            "--only",
            "clean-single-source",
            "--only",
            "gate-rejected",
            "--out",
            str(out),
        ]
    )
    err = capsys.readouterr().err
    assert rc == 130 and f"interrupted; the partial report is {out / 'bench.json'}" in err
    report = BenchReport.model_validate_json((out / "bench.json").read_text())
    assert [(s.name, len(s.runs)) for s in report.scenarios] == [
        ("clean-single-source", 1),
        ("gate-rejected", 0),
    ]


def test_bench_interrupted_without_out_says_so(config_path, capsys, monkeypatch):
    async def interrupting(scenario, cfg, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("corelata.bench.run.run_scenario", interrupting)
    rc = main(["bench", "--config", str(config_path), "--only", "clean-single-source"])
    assert rc == 130 and capsys.readouterr().err.strip().endswith("interrupted")


def test_bench_concurrency_and_store_io_flags(config_path, tmp_path, capsys):
    out = tmp_path / "bench"
    rc = main(
        [
            "bench",
            "--config",
            str(config_path),
            "--only",
            "clean-single-source",
            "--only",
            "gate-rejected",
            "--concurrency",
            "2",
            "--store-io",
            "--out",
            str(out),
        ]
    )
    assert rc == 0, capsys.readouterr().err
    trace = json.loads((out / "gate-rejected" / "run-1" / "trace.json").read_text())
    assert trace["llm_calls"] and all(c["request"] is not None for c in trace["llm_calls"])
    assert main(["bench", "--config", str(config_path), "--concurrency", "0"]) == 2
    assert "--concurrency must be between 1 and 16" in capsys.readouterr().err
    assert main(["bench", "--config", str(config_path), "--concurrency", "17"]) == 2


def test_bench_plays_a_shipped_set_by_name(config_path, capsys):
    argv = ["bench", "--config", str(config_path), "--json"]
    rc = main([*argv, "--scenarios", "real", "--only", "off-topic-sources"])
    data = json.loads(capsys.readouterr().out)
    # the synthetic gate supports any statement whose words appear in the sources, so it
    # disagrees with a set written for real models: exit 3, not an error
    assert rc == 3
    assert data["scenarios_dir"] == str(REAL_SCENARIOS_DIR)
    [scenario] = data["scenarios"]
    [run] = scenario["runs"]
    assert scenario["name"] == "off-topic-sources"
    assert "state: expected 'gate_rejected', got 'completed'" in run["mismatches"]
    assert run["gate"]["supported"] is True and run["gate"]["reasons"]
    assert main([*argv, "--scenarios", "synthetic", "--only", "gate-rejected"]) == 0
    assert json.loads(capsys.readouterr().out)["scenarios_dir"] == str(SCENARIOS_DIR)


def test_bench_help_names_the_sets(capsys):
    with pytest.raises(SystemExit):
        main(["bench", "--help"])
    out = capsys.readouterr().out
    assert "'synthetic'" in out and "'real'" in out
