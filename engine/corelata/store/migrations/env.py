"""Alembic environment: online migrations against the URL corelata.store.migrate passes in."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from corelata.store.db import CONNECT_ARGS
from corelata.store.models import Base


def _ours(name: str | None, type_: str, parent_names: object) -> bool:
    # procrastinate's tables share the database; autogenerate must never touch them
    return type_ != "table" or name in Base.metadata.tables


engine = create_engine(
    context.config.attributes["url"], poolclass=NullPool, connect_args=dict(CONNECT_ARGS)
)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_name=_ours,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
