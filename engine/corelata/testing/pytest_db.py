"""Pytest plugin with the Postgres fixtures shared by the engine (and later API) test suites;
load it with `pytest_plugins = ["corelata.testing.pytest_db"]`. The database imports stay
inside the fixtures so tests that need no database never import SQLAlchemy or psycopg."""

import os
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from corelata.store.db import Database
    from corelata.testing.postgres import RunChannel


@pytest.fixture(scope="session")
def pg_admin() -> str:
    from corelata.testing.postgres import TEST_DB_ENV

    admin = os.environ.get(TEST_DB_ENV)
    if not admin:
        pytest.fail(
            f"{TEST_DB_ENV} is not set. Start Postgres with `make db-up` and set "
            f"{TEST_DB_ENV}=postgresql://corelata:corelata@127.0.0.1:55433/postgres "
            "(`make test-engine` does both).",
            pytrace=False,
        )
    return admin


@pytest.fixture(scope="session")
def pg_url(pg_admin) -> Iterator[str]:
    from corelata.store.migrate import upgrade
    from corelata.testing.postgres import create_test_database, drop_test_database

    url = create_test_database(pg_admin)
    try:
        upgrade(url)
        yield url
    finally:
        drop_test_database(pg_admin, url)


@pytest.fixture
async def db(pg_url) -> AsyncIterator["Database"]:
    from corelata.store.db import Database
    from corelata.testing.postgres import truncate_all

    database = Database(pg_url)
    await truncate_all(database)
    yield database
    await database.dispose()


@pytest.fixture
async def run_channel(pg_url) -> AsyncIterator["RunChannel"]:
    """A LISTEN connection on the run channel, open for the test (CRL-22)."""
    from corelata.testing.postgres import open_run_channel

    async with open_run_channel(pg_url) as channel:
        yield channel
