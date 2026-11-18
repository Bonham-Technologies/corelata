import pytest

from corelata.config import ConfigError
from corelata.store.db import (
    Database,
    database_url,
    error_reason,
    redact,
    to_libpq_url,
    to_sqlalchemy_url,
)
from tests.conftest import build_config


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgres://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ],
)
def test_to_sqlalchemy_url(url, expected):
    assert to_sqlalchemy_url(url) == expected


def test_to_libpq_url():
    assert to_libpq_url("postgresql+psycopg://u:p@h/d") == "postgresql://u:p@h/d"


@pytest.mark.parametrize("url", ["mysql://u:p@h/d", "not a url", "sqlite:///x.db"])
def test_non_postgres_urls_are_rejected(url):
    with pytest.raises(ConfigError, match="postgresql://"):
        to_sqlalchemy_url(url)


@pytest.mark.parametrize(
    "url", ["postgresql://u:secret@h:abc/d", "postgresql://u:secret@[::1/d", "not a url"]
)
def test_malformed_urls_are_a_config_error_without_the_password(url):
    with pytest.raises(ConfigError, match="invalid database URL") as caught:
        to_sqlalchemy_url(url)
    assert "secret" not in str(caught.value) and caught.value.__cause__ is None


def test_redact_hides_the_password():
    assert redact("postgresql://u:secret@h/d") == "postgresql://u:***@h/d"


def test_database_url(monkeypatch):
    cfg = build_config()
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="set CORELATA_DATABASE_URL"):
        database_url(cfg)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "mysql://x")
    with pytest.raises(ConfigError, match="postgresql://"):
        database_url(cfg)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:p@h/d")
    assert database_url(cfg) == "postgresql://u:p@h/d"


async def test_ping(db):
    await db.ping()


async def test_ping_fails_cleanly_for_an_unreachable_server():
    from sqlalchemy.exc import OperationalError

    database = Database("postgresql://u:p@127.0.0.1:9/nowhere")
    with pytest.raises(OperationalError):
        await database.ping()
    await database.dispose()


def test_error_reason_is_the_first_line_of_the_driver_error():
    from sqlalchemy.exc import OperationalError

    orig = Exception("  connection refused\n\tIs the server running?\n")
    assert error_reason(OperationalError("SELECT 1", {}, orig)) == "connection refused"
    assert error_reason(ValueError("plain\nsecond")) == "plain"
    assert error_reason(ValueError()) == "ValueError"


@pytest.fixture
def silent_server():
    """A TCP port that completes the handshake and then never answers, like a black-holed
    database host: without a connect timeout a client waits for the OS TCP timeout or longer."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    yield f"postgresql://u:p@127.0.0.1:{sock.getsockname()[1]}/d"
    sock.close()


@pytest.fixture
def short_connect_timeout(monkeypatch):
    from corelata.store import db as db_module
    from corelata.store import migrate

    short = {"connect_timeout": 2}  # libpq's minimum
    monkeypatch.setattr(db_module, "CONNECT_ARGS", short)
    monkeypatch.setattr(migrate, "CONNECT_ARGS", short)


def test_connections_have_a_connect_timeout():
    from corelata.store.db import CONNECT_ARGS

    assert CONNECT_ARGS == {"connect_timeout": 10}


async def test_the_database_gives_up_on_a_silent_host(silent_server, short_connect_timeout):
    import asyncio

    from sqlalchemy.exc import OperationalError

    database = Database(silent_server)
    with pytest.raises(OperationalError, match="timeout"):
        await asyncio.wait_for(database.ping(), 15)
    await database.dispose()


async def test_the_migration_check_gives_up_on_a_silent_host(silent_server, short_connect_timeout):
    import asyncio

    from corelata.store.migrate import ensure_migrated

    with pytest.raises(ConfigError, match="cannot connect to the database.*timeout"):
        await asyncio.wait_for(asyncio.to_thread(ensure_migrated, silent_server), 15)
