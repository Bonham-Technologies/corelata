"""Schema migrations (spec §8.3: Alembic). Revision 0001 installs procrastinate's job-queue
schema (3.10.0), revision 0002 the Corelata tables, 0003 the orphan-sweep indexes, 0004
`run.review_state`, 0005 the rerun's fate in it, 0006 the run list's index, 0007 drops the
project index it made redundant, 0008 `run.prior_reports`, 0009 `run.kind` and
`run.report_source_id`, 0010 brings procrastinate's schema to 3.12.0; a procrastinate upgrade
needs a new revision that applies its migration SQL. Copied from Coglossa."""

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.pool import NullPool

from corelata.config import ConfigError
from corelata.store.db import CONNECT_ARGS, error_reason, redact, to_sqlalchemy_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["url"] = to_sqlalchemy_url(url)  # attributes avoid ConfigParser '%' escaping
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


@dataclass(frozen=True)
class MigrationState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


def migration_state(url: str) -> MigrationState:
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    engine = create_engine(
        to_sqlalchemy_url(url), poolclass=NullPool, connect_args=dict(CONNECT_ARGS)
    )
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    return MigrationState(current=current, head=head or "")


class DatabaseUnavailable(ConfigError):
    """The database could not be reached; the message is redacted and safe to show."""


def connect_error(url: str, e: BaseException) -> DatabaseUnavailable:
    return DatabaseUnavailable(
        f"cannot connect to the database at {redact(url)}: {error_reason(e)}"
    )


def ensure_migrated(url: str) -> None:
    """Refuse, with one line, a database that is unreachable or not at the head revision."""
    try:
        state = migration_state(url)
    except (OperationalError, InterfaceError) as e:
        raise connect_error(url, e) from e
    if not state.up_to_date:
        raise ConfigError(
            f"the database schema is at revision {state.current or 'none'} but this version "
            f"needs {state.head}: run `corelata migrate`"
        )
