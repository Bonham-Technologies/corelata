import pytest
from corelata.testing.postgres import create_test_database, drop_test_database

from corelata_api import main as main_module


@pytest.fixture
def no_server(monkeypatch):
    calls = []

    def fake_run(app, **options):
        calls.append((app, options))

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    return calls


def test_main_serves_the_app_with_the_given_host_and_port(write_config, no_server, capsys):
    path = write_config()
    code = main_module.main(["--config", str(path), "--host", "0.0.0.0", "--port", "9090"])
    assert code == 0
    [(app, options)] = no_server
    assert app.title == "Corelata" and options == {
        "host": "0.0.0.0",
        "port": 9090,
        "timeout_graceful_shutdown": 5,
    }


def test_main_defaults_and_reads_the_config_from_the_environment(
    write_config, no_server, monkeypatch
):
    path = write_config()
    monkeypatch.setenv("CORELATA_CONFIG", str(path))
    assert main_module.main([]) == 0
    [(_, options)] = no_server
    assert options == {"host": "127.0.0.1", "port": 8080, "timeout_graceful_shutdown": 5}


def test_main_refuses_a_missing_config(no_server, capsys, tmp_path):
    assert main_module.main(["--config", str(tmp_path / "nope.yaml")]) == 1
    assert "config file not found" in capsys.readouterr().err and no_server == []


def test_main_refuses_an_unmigrated_database(
    write_config, no_server, pg_admin, monkeypatch, capsys
):
    url = create_test_database(pg_admin)
    try:
        monkeypatch.setenv("CORELATA_DATABASE_URL", url)
        assert main_module.main(["--config", str(write_config())]) == 1
        assert "run `corelata migrate`" in capsys.readouterr().err
    finally:
        drop_test_database(pg_admin, url)
    assert no_server == []


def test_main_refuses_unwritable_storage(write_config, no_server, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    assert main_module.main(["--config", str(write_config(storage={"path": str(blocker)}))]) == 1
    assert "error:" in capsys.readouterr().err and no_server == []


def test_main_serves_past_a_stuck_check_probe(write_config, no_server, monkeypatch, capsys):
    """The bucket took the probe but would not delete it: serve, and warn with the key (CRL-59)."""
    from corelata.storage import LocalStorage, ProbeLeftover

    def stuck(self):
        raise ProbeLeftover(".corelata-check-abc", "AccessDenied: no")

    monkeypatch.setattr(LocalStorage, "check_writable", stuck)
    assert main_module.main(["--config", str(write_config())]) == 0
    assert "warning: storage check probe .corelata-check-abc" in capsys.readouterr().err
    assert len(no_server) == 1


def test_main_refuses_a_web_dir_without_index(write_config, no_server, tmp_path, capsys):
    empty = tmp_path / "web"
    empty.mkdir()
    code = main_module.main(["--config", str(write_config()), "--web-dir", str(empty)])
    assert code == 1
    assert "has no index.html" in capsys.readouterr().err and no_server == []


def test_main_mounts_the_web_dir(write_config, no_server, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>Corelata</title>")
    assert main_module.main(["--config", str(write_config()), "--web-dir", str(web)]) == 0
    [(app, _)] = no_server
    assert any(getattr(r, "path", "") == "/{path:path}" for r in app.routes)
