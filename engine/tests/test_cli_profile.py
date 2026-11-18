import shutil
from pathlib import Path

import pytest
import yaml

from corelata import cli
from corelata.cli import main
from corelata.standards.loader import BUILTIN_PACKS_DIR, PackError, load_pack, validate_pack
from corelata.standards.schema import Profile
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG

REPORT = [
    "UNCLASSIFIED//FOUO",
    "## 1. Key Judgments",
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
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert captured.out.startswith(
        f"wrote {out} (draft profile 'team-east' extends 'icd203-base'; 2 observations)"
    )
    assert "3 example reports read" in captured.out
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Draft profile written by `corelata profile extract`")
    data = yaml.safe_load(text)
    profile = Profile.model_validate(data)
    assert profile.draft and profile.extends == "icd203-base"
    assert profile.format.heading_style == "numbered"
    assert profile.lexicon.handling_markings == ["UNCLASSIFIED//FOUO"]
    # the §14 exit test: placed in a pack's profiles/, it validates as a draft, refused for a run
    pack_dir = tmp_path / "packs" / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", pack_dir)
    (pack_dir / "profiles").mkdir()
    shutil.copy(out, pack_dir / "profiles" / "team-east.yaml")
    issues = validate_pack(str(pack_dir))
    assert [(i.level, i.message) for i in issues] == [("warning", "profile 'team-east' is a draft")]
    with pytest.raises(PackError, match="draft"):
        load_pack("icd203-base", packs_dir=pack_dir.parent, profile="team-east")
    resolved = load_pack(
        "icd203-base", packs_dir=pack_dir.parent, profile="team-east", allow_draft=True
    )
    assert resolved.tone.startswith("Lead with the key judgments")
    assert len(fake_server.requests) == 1  # one profiler call, no repair


def test_extract_refuses_to_overwrite_without_force(config_path, examples, tmp_path, capsys):
    out = tmp_path / "team.yaml"
    out.write_text("name: team\nextends: icd203-base\n")
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
        ]
    )
    assert rc == 2 and "--force" in capsys.readouterr().err
    assert out.read_text() == "name: team\nextends: icd203-base\n"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
            "--force",
        ]
    )
    assert rc == 0 and yaml.safe_load(out.read_text())["draft"] is True


def test_extract_name_and_extends_options(config_path, examples, tmp_path, capsys):
    out = tmp_path / "x.yaml"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
            "--name",
            "team-west",
            "--extends",
            "icd203-base",
        ]
    )
    assert rc == 0
    assert yaml.safe_load(out.read_text())["name"] == "team-west"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(tmp_path / "Bad Name.yaml"),
        ]
    )
    assert rc == 2 and "--name" in capsys.readouterr().err
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(tmp_path / "y.yaml"),
            "--extends",
            "nope",
        ]
    )
    assert rc == 2 and "nope" in capsys.readouterr().err


def test_extract_unsupported_example_is_a_usage_error_before_any_call(
    config_path, examples, tmp_path, capsys, fake_server
):
    (examples / "notes.xyz").write_text("x")
    out = tmp_path / "t.yaml"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
        ]
    )
    assert rc == 2
    assert "notes.xyz" in capsys.readouterr().err
    assert not out.exists() and fake_server.requests == []


def test_extract_round_trip_guard_is_a_clean_exit_1(
    config_path, examples, tmp_path, capsys, monkeypatch
):
    def broken(*_args, **_kwargs):
        raise ValueError("profile_yaml: output does not round-trip")

    monkeypatch.setattr(cli, "profile_yaml", broken)
    out = tmp_path / "t.yaml"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    assert "error: profile_yaml: output does not round-trip" in capsys.readouterr().err
    assert not out.exists()


def test_extract_invalid_draft_twice_exits_1_and_writes_nothing(
    config_path, tmp_path, capsys, fake_server
):
    d = tmp_path / "ex"
    d.mkdir()
    (d / "r.md").write_text("BADRULE everywhere.\n")
    out = tmp_path / "t.yaml"
    rc = main(
        ["profile", "extract", "--config", str(config_path), "--from", str(d), "--out", str(out)]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown rule id 'nope.rule.1'" in err and not out.exists()
    assert len(fake_server.requests) == 2


def test_extract_without_profiler_role_is_a_config_error(tmp_path, examples, fake_server, capsys):
    data = {**BASE_CONFIG, "backends": {"fake": {"base_url": fake_server.base_url}}}
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(data))
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(cfg),
            "--from",
            str(examples),
            "--out",
            str(tmp_path / "t.yaml"),
        ]
    )
    assert rc == 2 and "roles.profiler" in capsys.readouterr().err


def test_extract_out_parent_missing_and_budget_option(config_path, examples, tmp_path, capsys):
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(tmp_path / "nowhere" / "t.yaml"),
        ]
    )
    assert rc == 2 and "nowhere" in capsys.readouterr().err
    out = tmp_path / "small.yaml"
    rc = main(
        [
            "profile",
            "extract",
            "--config",
            str(config_path),
            "--from",
            str(examples),
            "--out",
            str(out),
            "--budget-tokens",
            "30",
        ]
    )
    assert rc == 0 and out.exists()
    assert (
        main(
            [
                "profile",
                "extract",
                "--config",
                str(config_path),
                "--from",
                str(examples),
                "--out",
                str(tmp_path / "z.yaml"),
                "--budget-tokens",
                "0",
            ]
        )
        == 2
    )


def _extract_argv(config_path, examples, out, *extra):
    return [
        "profile",
        "extract",
        "--config",
        str(config_path),
        "--from",
        str(examples),
        "--out",
        str(out),
        *extra,
    ]


def test_extract_out_that_is_a_directory_is_a_usage_error(
    config_path, examples, tmp_path, capsys, fake_server
):
    out = tmp_path / "somedir"
    out.mkdir()
    assert main(_extract_argv(config_path, examples, out, "--force", "--name", "x")) == 2
    assert "is a directory" in capsys.readouterr().err
    assert fake_server.requests == []


def test_extract_unwritable_out_prints_the_draft_and_exits_1(
    config_path, examples, tmp_path, capsys, monkeypatch
):
    def deny(self, *args, **kwargs):
        raise PermissionError("denied")

    out = tmp_path / "t.yaml"
    out.write_text("old")
    monkeypatch.setattr(Path, "write_text", deny)
    assert main(_extract_argv(config_path, examples, out, "--force")) == 1
    captured = capsys.readouterr()
    assert "error: cannot write" in captured.err
    assert "draft: true" in captured.out


def test_extract_refuses_a_file_that_appeared_during_the_call(
    config_path, examples, tmp_path, capsys, monkeypatch
):
    out = tmp_path / "t.yaml"
    real = cli.extract_profile

    async def racing(*args, **kwargs):
        result = await real(*args, **kwargs)
        out.write_text("someone else's")
        return result

    monkeypatch.setattr(cli, "extract_profile", racing)
    assert main(_extract_argv(config_path, examples, out)) == 2
    captured = capsys.readouterr()
    assert f"error: {out} exists; pass --force" in captured.err
    assert out.read_text() == "someone else's" and "draft: true" in captured.out


def test_extract_default_budget_is_half_a_small_context(
    tmp_path, examples, fake_server, monkeypatch
):
    data = {
        **BASE_CONFIG,
        "backends": {"fake": {"base_url": fake_server.base_url}},
        "models": {**BASE_CONFIG["models"], "small": {"backend": "fake", "context_window": 4096}},
        "roles": {**BASE_CONFIG["roles"], "profiler": {"model": "small"}},
    }
    cfg = tmp_path / "small.yaml"
    cfg.write_text(yaml.safe_dump(data))
    budgets: list[int] = []
    real = cli.read_examples

    def spy(directory, *, budget_tokens, bytes_per_token):
        budgets.append(budget_tokens)
        return real(directory, budget_tokens=budget_tokens, bytes_per_token=bytes_per_token)

    monkeypatch.setattr(cli, "read_examples", spy)
    assert main(_extract_argv(cfg, examples, tmp_path / "t.yaml")) == 0
    assert budgets == [2048]


def test_extract_warns_when_the_name_is_already_a_profile(config_path, examples, tmp_path, capsys):
    pack_dir = tmp_path / "packs" / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", pack_dir)
    (pack_dir / "profiles").mkdir()
    (pack_dir / "profiles" / "team-east.yaml").write_text(
        "name: team-east\nextends: icd203-base\n", encoding="utf-8"
    )
    out = tmp_path / "team-east.yaml"
    packs = str(pack_dir.parent)
    rc = main(_extract_argv(config_path, examples, out, "--packs-dir", packs))
    captured = capsys.readouterr()
    assert rc == 0 and out.is_file()
    assert (
        "warning: profile 'team-east' already exists in pack 'icd203-base'; "
        "a profile file of that name in its profiles/ directory would replace it" in captured.err
    )
    rc = main(
        _extract_argv(config_path, examples, tmp_path / "team-west.yaml", "--packs-dir", packs)
    )
    assert rc == 0 and "warning: profile" not in capsys.readouterr().err
