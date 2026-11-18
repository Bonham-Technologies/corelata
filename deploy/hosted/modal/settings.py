"""Hosted demo settings shared by the Modal app and its tests; no Modal import here. Copied from
Coglossa's preview; the seed (spec §13.6) is Corelata's."""

import hmac
import os
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from string import Template

DATABASE = "corelata"  # the only database the hosted parts may touch (R-M19-23)

HERE = Path(__file__).resolve().parent
HOSTED_TEMPLATE = HERE.parent / "corelata.hosted.yaml"

# The example project the seed writes once (spec §13.6), from the file the image carries.
EXAMPLE_PROJECT = "Example: Varna port"
EXAMPLE_SOURCE = "/etc/corelata/examples/varna-port.txt"
STATEMENT = (
    "The port of Varna's 2025 container expansion, financed by a state bank, is already raising "
    "traffic; shippers and the port authority should plan for higher volumes."
)


def repo_root(app_file: str | Path, local: bool) -> Path:
    """The repository root, from deploy/hosted/modal/app.py. Inside a Modal container app.py
    is /root/app.py and nothing is read from the local tree (the image is already built), so
    any path will do there: "/" stands in for it."""
    return Path(app_file).resolve().parents[3] if local else Path("/")


def render_config(template: Path, out: Path, env: Mapping[str, str] = os.environ) -> Path:
    """The hosted config with ${NAME} filled from the environment (the Modal Secret). A
    missing value raises KeyError naming it, so the container fails at start, not mid-run."""
    out.write_text(Template(template.read_text(encoding="utf-8")).substitute(env), encoding="utf-8")
    return out


def check_kick(authorization: str | None, token: str) -> bool:
    """True when the Authorization header is exactly "Bearer <token>" (constant-time compare).
    An empty token matches nothing: "Bearer " must never open the kick."""
    if not token:
        return False
    return hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode())


def seed_command(project_names: Iterable[str]) -> list[str] | None:
    """The `corelata run` that queues the example report, or None when the example project
    already exists, so a redeploy never writes a second report (spec §13.6). The config comes
    from CORELATA_CONFIG, which the image sets."""
    if EXAMPLE_PROJECT in set(project_names):
        return None
    return ["corelata", "run", "--project", EXAMPLE_PROJECT, "--statement", STATEMENT, EXAMPLE_SOURCE]


def check_database_url(url: str, env: Mapping[str, str] = os.environ) -> None:
    """Raise ValueError unless libpq itself would connect to the database `corelata` (R-M19-23:
    the Supabase project is shared with Coglossa). The URL is read with libpq's own parser, so
    a `dbname=` query parameter counts. A `service` parameter (a service file can set anything)
    and any `options` parameter are refused: the demo needs no options, and Postgres reads `-`
    as `_` in a setting's name, so matching words in them can be sidestepped by spelling
    (CRL-52). libpq also reads PGOPTIONS and PGSERVICE from the environment at connect time,
    so either one being set is refused too."""
    from corelata.store.db import to_libpq_url
    from psycopg.conninfo import conninfo_to_dict

    for name in ("PGOPTIONS", "PGSERVICE"):
        if env.get(name):
            raise ValueError(f"{name} is set: libpq would apply it to the connection; not allowed")
    info = conninfo_to_dict(to_libpq_url(url))
    if info.get("service"):
        raise ValueError("CORELATA_DATABASE_URL sets a libpq service: not allowed")
    if str(info.get("options") or "").strip():
        raise ValueError("CORELATA_DATABASE_URL sets libpq options: not allowed")
    name = info.get("dbname")
    if name != DATABASE:
        raise ValueError(f"CORELATA_DATABASE_URL names the database {name!r}, not {DATABASE!r}")


def run_cli(command: list[str]) -> None:
    """Run a command and raise CalledProcessError when it exits non-zero, so a failed
    `corelata doctor` fails the Modal function (and the deploy step that calls it)."""
    subprocess.run(command, check=True)
