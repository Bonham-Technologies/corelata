"""Spec §4.2: the engine library has no knowledge of the database."""

import pkgutil
import subprocess
import sys

import corelata

# Modules that may use the database; everything else in corelata is library code.
DATABASE_MODULES = (
    "corelata.store",
    "corelata.service",
    "corelata.removal",
    "corelata.worker",
    "corelata.doctor",
    "corelata.cli_ops",
    "corelata.cli",  # imports cli_ops
    "corelata.testing.postgres",
    "corelata.testing.pytest_db",
)


def _is_database_module(name: str) -> bool:
    return any(name == d or name.startswith(d + ".") for d in DATABASE_MODULES)


LIBRARY = sorted(
    m.name
    for m in pkgutil.walk_packages(corelata.__path__, "corelata.")
    if not _is_database_module(m.name)
)
FORBIDDEN = ("sqlalchemy", "alembic", "psycopg", "procrastinate")


def test_library_modules_do_not_import_database_packages():
    code = (
        "import importlib, sys\n"
        f"for m in {LIBRARY!r}: importlib.import_module(m)\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r})\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"library imports database packages: {result.stdout}"


def test_discovery_finds_the_library():
    for name in ("corelata.render.docx", "corelata.ingest.pdf", "corelata.pipeline"):
        assert name in LIBRARY
    assert "corelata.store.db" not in LIBRARY
