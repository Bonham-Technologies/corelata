"""Start the hosted demo clean (spec §17, §23.1): empty Corelata's tables in the database
`corelata` and its files in the bucket `corelata-files`, then run the seed again.

Coglossa's preview lives in the same Supabase project, with its own database and its bucket
`coglossa-files`. This script touches neither: it refuses a database URL that does not name
`corelata` (read as libpq reads it, query parameters included), checks again on the open connection, and only ever addresses `corelata-files`. The
schema and its migrations stay; only rows and files go.

Run it from engine/ with the hosted values in the environment (nothing is printed but counts):
    set -a; . ~/.config/corelata/hosted.env; set +a
    uv run --extra s3 python ../deploy/hosted/modal/start_clean.py --yes
    uv run --with-requirements ../deploy/hosted/modal/requirements.txt \
        modal run ../deploy/hosted/modal/app.py::seed
"""

import argparse
import os
import sys
from typing import Any

DATABASE = "corelata"
BUCKET = "corelata-files"
KEY_SPACES = ("projects", "runs")  # every stored key starts with one (corelata.service)
PROBE_PREFIX = ".corelata-check-"  # doctor's write probe, left in the root when its delete failed


def check_url(url: str) -> None:
    """Refuse (SystemExit) a database URL that names any database but `corelata`."""
    import psycopg
    from settings import check_database_url

    from corelata.config import ConfigError

    try:
        check_database_url(url)
    except ValueError as e:
        sys.exit(f"refusing: {e}")
    except (ConfigError, psycopg.Error) as e:
        # Never echo the message: a parser may quote part of the URL, and the URL holds the password.
        sys.exit(f"refusing: CORELATA_DATABASE_URL cannot be read as a database URL ({type(e).__name__})")


def tables() -> list[str]:
    """Corelata's tables and procrastinate's, never alembic_version (the schema stays)."""
    from corelata.store.models import Base
    from corelata.testing.postgres import PROCRASTINATE_TABLES

    return [t.name for t in Base.metadata.sorted_tables] + list(PROCRASTINATE_TABLES)


def clear_database(conn: Any) -> int:
    """TRUNCATE every table on an open psycopg connection, after checking it is connected to
    `corelata`; returns how many tables were emptied."""
    current = conn.execute("SELECT current_database()").fetchone()[0]
    if current != DATABASE:
        sys.exit(f"refusing: connected to the database {current!r}, not {DATABASE!r}")
    names = tables()
    conn.execute(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")
    conn.commit()
    return len(names)


def clear_bucket(storage: Any) -> int:
    """Delete every stored file of `corelata-files` (an S3Storage for it) and any doctor probe left
    in its root; returns the count."""
    if storage.cfg.bucket != BUCKET:
        sys.exit(f"refusing: the bucket is {storage.cfg.bucket!r}, not {BUCKET!r}")
    count = 0
    for space in KEY_SPACES:
        count += len(storage.list_keys(space))
        storage.delete_prefix(space)
    pages = storage._s3.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET, Prefix=PROBE_PREFIX
    )
    for key in [o["Key"] for page in pages for o in page.get("Contents", [])]:
        storage._s3.delete_object(Bucket=BUCKET, Key=key)
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--yes", action="store_true", help="really delete the demo's data")
    args = parser.parse_args(argv)
    names = ["CORELATA_DATABASE_URL", "CORELATA_S3_ENDPOINT", "CORELATA_S3_REGION"]
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"{', '.join(missing)} not set: export ~/.config/corelata/hosted.env first")
    url = os.environ["CORELATA_DATABASE_URL"]
    check_url(url)
    if not args.yes:
        sys.exit(f"this empties the database {DATABASE!r} and the bucket {BUCKET!r}: add --yes")

    import psycopg

    from corelata.config import S3StorageConfig
    from corelata.storage import S3Storage
    from corelata.store.db import to_libpq_url

    with psycopg.connect(to_libpq_url(url), connect_timeout=10) as conn:
        emptied = clear_database(conn)
    storage = S3Storage(
        S3StorageConfig(
            kind="s3",
            endpoint_url=os.environ["CORELATA_S3_ENDPOINT"],
            region=os.environ["CORELATA_S3_REGION"],
            bucket=BUCKET,
        )
    )
    files = clear_bucket(storage)
    print(f"emptied {emptied} tables in {DATABASE} and {files} files in {BUCKET}; now run the seed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
