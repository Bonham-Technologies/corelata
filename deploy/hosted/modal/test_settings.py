import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from settings import (
    EXAMPLE_PROJECT,
    EXAMPLE_SOURCE,
    HERE,
    HOSTED_TEMPLATE,
    STATEMENT,
    check_database_url,
    check_kick,
    render_config,
    repo_root,
    run_cli,
    seed_command,
)

ENV = {
    "CORELATA_S3_ENDPOINT": "https://ref.storage.supabase.co/storage/v1/s3",
    "CORELATA_S3_REGION": "ca-central-1",
    "CORELATA_KICK_URL": "https://ws--corelata-kick.modal.run",
}
SECRETS = [
    "OPENROUTER_API_KEY",
    "CORELATA_S3_ACCESS_KEY_ID",
    "CORELATA_S3_SECRET_ACCESS_KEY",
    "CORELATA_KICK_TOKEN",
    "CORELATA_PROXY_SECRET",
    "CORELATA_MODAL_KEY",
    "CORELATA_MODAL_SECRET",
]
SPEC = HERE.parents[2] / "docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md"


def test_render_fills_every_placeholder(tmp_path):
    out = render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV)
    text = out.read_text(encoding="utf-8")
    assert "${" not in text
    data = yaml.safe_load(text)
    assert data["worker"]["kick_url"] == ENV["CORELATA_KICK_URL"]
    assert data["storage"]["endpoint_url"] == ENV["CORELATA_S3_ENDPOINT"]
    assert data["storage"]["region"] == "ca-central-1"


@pytest.mark.parametrize("missing", sorted(ENV))
def test_a_missing_value_names_the_variable(tmp_path, missing):
    with pytest.raises(KeyError, match=missing):
        render_config(
            HOSTED_TEMPLATE, tmp_path / "c.yaml", {k: v for k, v in ENV.items() if k != missing}
        )


def test_the_hosted_config_is_the_specs(tmp_path):
    """spec §14, the block under its heading, as data (comments aside)."""
    section = SPEC.read_text(encoding="utf-8").split("## 14. The hosted config", 1)[1]
    block = re.search(r"```yaml\n(.*?)```", section, re.S)
    assert block is not None
    assert yaml.safe_load(HOSTED_TEMPLATE.read_text(encoding="utf-8")) == yaml.safe_load(
        block.group(1)
    )


def test_the_rendered_config_is_valid(tmp_path, monkeypatch):
    corelata_config = pytest.importorskip("corelata.config")
    for var in SECRETS:
        monkeypatch.setenv(var, "x" * 32)
    cfg, issues = corelata_config.load_config(render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV))
    assert [i for i in issues if i.level == "error"] == []
    assert (cfg.storage.kind, cfg.storage.bucket) == ("s3", "corelata-files")
    assert cfg.worker.extra_headers_env == {
        "Modal-Key": "CORELATA_MODAL_KEY",
        "Modal-Secret": "CORELATA_MODAL_SECRET",
    }
    # spec §13.4: a burst worker's limits
    worker = cfg.worker
    assert (worker.stalled_after_s, worker.discovery_start_deadline_s, worker.concurrency) == (
        120,
        600,
        4,
    )
    assert worker.discovery_deadline_s == 600
    # spec §13.1, §13.3, §23.6: the pooler's LISTEN path, Vercel's body limit
    assert (cfg.api.max_upload_mb, cfg.api.progress_poll_s, cfg.api.web_dir) == (4, 1.0, None)
    assert (cfg.auth.mode, cfg.auth.proxy_secret_env, cfg.auth.logout_url) == (
        "trusted_header",
        "CORELATA_PROXY_SECRET",
        "/logout",
    )
    assert cfg.integrations.coglossa is None and cfg.standards.packs_dir is None
    roles = dict(cfg.roles.all_roles())
    assert roles["auditor"] != roles["writer"]  # a different family checks the standards
    assert cfg.models[roles["auditor"]].name == "google/gemini-2.5-flash"


def test_the_rendered_config_needs_every_secret(tmp_path, monkeypatch):
    corelata_config = pytest.importorskip("corelata.config")
    for var in SECRETS:
        monkeypatch.setenv(var, "x" * 32)
    path = render_config(HOSTED_TEMPLATE, tmp_path / "c.yaml", ENV)
    for var in SECRETS:
        monkeypatch.delenv(var)
        with pytest.raises(corelata_config.ConfigError, match=var):
            corelata_config.load_config(path)
        monkeypatch.setenv(var, "x" * 32)


def test_check_kick():
    assert check_kick("Bearer abc", "abc")
    assert not check_kick("Bearer abd", "abc")
    assert not check_kick("abc", "abc")
    assert not check_kick(None, "abc")
    assert not check_kick("", "")  # no empty-token bypass of the "Bearer " prefix
    assert not check_kick("Bearer ", "")  # an empty or unset token opens nothing
    assert not check_kick("Bearer", "")
    assert not check_kick(None, "")


def test_the_kick_endpoint_signature_works_under_fastapi():
    # Same signature style as kick() in app.py: a Header parameter resolvable in module globals.
    web = FastAPI()

    @web.post("/")
    def kick(authorization: str | None = Header(None)):
        if not check_kick(authorization, "tok"):
            return JSONResponse({"detail": "wrong kick token"}, status_code=401)
        return {"spawned": True}

    client = TestClient(web)
    right = client.post("/", headers={"Authorization": "Bearer tok"})
    assert (right.status_code, right.json()) == (200, {"spawned": True})
    assert client.post("/", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/").status_code == 401


def test_repo_root_locally_and_in_a_container():
    assert repo_root(HERE / "app.py", local=True) == HERE.parents[2]
    assert (repo_root(HERE / "app.py", local=True) / "engine" / "pyproject.toml").is_file()
    # Modal mounts app.py at /root/app.py: there is no repository around it
    assert repo_root("/root/app.py", local=False) == Path("/")


def test_seed_runs_only_when_the_example_is_missing():
    """Review Focus 5: a redeploy, or a second `modal run …::seed`, never writes a second
    example report (spec §13.6)."""
    command = seed_command(["Black Sea"])
    assert command == [
        "corelata",
        "run",
        "--project",
        EXAMPLE_PROJECT,
        "--statement",
        STATEMENT,
        EXAMPLE_SOURCE,
    ]
    assert seed_command([]) == command
    assert seed_command(["Black Sea", EXAMPLE_PROJECT]) is None
    assert seed_command(iter([EXAMPLE_PROJECT])) is None


def test_the_seed_uses_the_specs_statement_and_the_example_the_image_carries():
    assert EXAMPLE_PROJECT == "Example: Varna port"
    spec = " ".join(SPEC.read_text(encoding="utf-8").split())
    assert f'STATEMENT is a constant in `app.py`: "{STATEMENT}"' in spec
    assert (HERE.parents[2] / "docs" / "examples" / Path(EXAMPLE_SOURCE).name).is_file()


URL = "postgresql://postgres.ref:pw@aws-1-ca-central-1.pooler.supabase.com:5432/corelata?sslmode=require"


def test_the_database_guard_accepts_only_corelata():
    check_database_url(URL, env={})
    check_database_url(URL.replace("/corelata?", "/%63orelata?"), env={})
    check_database_url(URL.replace("postgresql://", "postgresql+asyncpg://"), env={})
    for bad in (
        URL.replace("/corelata?", "/postgres?"),
        URL.replace("/corelata?", "/corelatafoo?"),
        URL.replace("/corelata?", "/corelata?dbname=postgres&"),
        URL.replace("/corelata?", "/corelata?service=x&"),
        URL + "&options=-c%20search_path%3Dcoglossa",
        URL + "&options=-c%20search-path%3Dcoglossa",  # Postgres reads - as _ in a GUC name
        URL + "&options=--search-path%3Dcoglossa",
        URL + "&options=-c%20statement_timeout%3D0",  # the demo needs no options at all
    ):
        with pytest.raises(ValueError, match="CORELATA_DATABASE_URL"):
            check_database_url(bad, env={})


@pytest.mark.parametrize("name", ["PGOPTIONS", "PGSERVICE"])
def test_the_database_guard_refuses_libpq_environment_overrides(name):
    """libpq reads PGOPTIONS and PGSERVICE at connect time, whatever the URL says (CRL-52)."""
    check_database_url(URL, env={"PGHOST": "ignored"})
    with pytest.raises(ValueError, match=name):
        check_database_url(URL, env={name: "-c search_path=coglossa"})


def test_the_database_guard_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("PGOPTIONS", "--search-path=coglossa")
    with pytest.raises(ValueError, match="PGOPTIONS"):
        check_database_url(URL)


def test_a_failing_command_fails_the_function():
    """doctor runs through run_cli: a non-zero exit raises."""
    run_cli([sys.executable, "-c", "pass"])
    with pytest.raises(subprocess.CalledProcessError):
        run_cli([sys.executable, "-c", "raise SystemExit(3)"])


def test_the_ci_overlay_pins_equal_requirements_txt():
    """Dependabot bumps requirements.txt, not ci.yml: a pin in the hosted-modal step that drifts
    from the file fails here until the workflow follows."""
    root = repo_root(HERE / "app.py", local=True)
    pins = {}
    for line in (root / "deploy/hosted/modal/requirements.txt").read_text().splitlines():
        if m := re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+)", line.strip()):
            pins[m[1].lower()] = m[2]
    ci = (root / ".github/workflows/ci.yml").read_text()
    step = ci[ci.index("  hosted-modal:") :]
    step = step[: step.index("  airgap:")]
    overlay = re.findall(r"--with ([A-Za-z0-9_.-]+)==(\S+)", step)
    assert overlay, "the hosted-modal step pins no --with package"
    for name, version in overlay:
        assert pins.get(name.lower()) == version, f"ci.yml pins {name}=={version}; requirements.txt has {pins.get(name.lower())}"
