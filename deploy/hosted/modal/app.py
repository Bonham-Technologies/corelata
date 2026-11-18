"""Corelata hosted demo on Modal (spec §11, §12.2): the API, a burst worker, the kick, a cron, the
daily purge, and migrate, doctor and seed for the operator, all scaling to zero. Copied from
Coglossa's preview without the scorer. Deploy: modal deploy deploy/hosted/modal/app.py"""

from pathlib import Path

import modal
from fastapi import Header  # in the app image through the api's dependencies
from fastapi.responses import JSONResponse

from settings import (
    EXAMPLE_SOURCE,
    HOSTED_TEMPLATE,
    check_database_url,
    check_kick,
    render_config,
    repo_root,
    run_cli,
    seed_command,
)

# A Modal container imports this file as /root/app.py, which has no repository around it.
REPO = repo_root(__file__, modal.is_local())
CONFIG = Path("/etc/corelata/corelata.hosted.yaml")  # the template, baked into the image
RENDERED = Path("/tmp/corelata.yaml")
IGNORE = [".venv", "**/__pycache__", "tests", "node_modules", "dist", "coverage", ".ruff_cache"]
APP_NAME = "corelata"
API_LABEL = "corelata-api"  # the web endpoint URLs are https://<workspace>--<label>.modal.run
KICK_LABEL = "corelata-kick"

app = modal.App(APP_NAME)
secret = modal.Secret.from_name("corelata-hosted")

app_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("uv==0.13.0")
    .add_local_dir(REPO / "engine", "/src/engine", copy=True, ignore=IGNORE)
    .add_local_dir(REPO / "api", "/src/api", copy=True, ignore=IGNORE)
    .run_commands(
        # the locked dependencies, then the two projects, into the system Python Modal runs
        # --extra s3: boto3 for Supabase Storage (the air-gapped app image leaves it out)
        "cd /src/api && uv export --frozen --no-dev --extra s3 --no-emit-project --no-hashes"
        " | grep -v '^-e ' > /tmp/req.txt",
        "uv pip install --system -r /tmp/req.txt /src/engine /src/api",
    )
    .add_local_file(HOSTED_TEMPLATE, str(CONFIG), copy=True)
    .add_local_file(REPO / "docs" / "examples" / "varna-port.txt", EXAMPLE_SOURCE, copy=True)
    .env({"CORELATA_CONFIG": str(RENDERED)})
    .add_local_python_source("settings")  # not copied: must stay the last step
)


def _render() -> None:
    """Every function that touches the database starts here: the guard on the database URL
    (R-M19-23: Coglossa shares the Supabase project) before anything connects."""
    import os

    check_database_url(os.environ["CORELATA_DATABASE_URL"])
    render_config(CONFIG, RENDERED)


def _config():
    from corelata.config import load_config

    _render()
    cfg, _ = load_config(RENDERED)
    return cfg


# Every web endpoint requires Modal proxy auth (Modal-Key/Modal-Secret headers): a request
# without them is refused by Modal and never starts a container. One API container: the
# database connection budget in README.md assumes it, and it holds the one LISTEN connection.
@app.function(
    image=app_image, secrets=[secret], cpu=1.0, memory=2048, scaledown_window=600, max_containers=1
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app(label=API_LABEL, requires_proxy_auth=True)
def api():
    from corelata_api.app import create_app

    return create_app(_config(), RENDERED)


@app.function(image=app_image, secrets=[secret], cpu=2.0, memory=4096, timeout=86400, max_containers=2)
def worker():
    import asyncio

    from corelata.store.db import database_url
    from corelata.worker.app import queue_status, run_worker

    cfg = _config()
    status = asyncio.run(queue_status(database_url(cfg), cfg.worker.stalled_after_s))
    if not status.has_work:
        return  # a late kick or a second spawn: exit at once
    asyncio.run(run_worker(cfg, burst=True, install_signal_handlers=False))


@app.function(image=app_image, secrets=[secret], cpu=0.25)
@modal.fastapi_endpoint(method="POST", label=KICK_LABEL, requires_proxy_auth=True)
def kick(authorization: str | None = Header(None)):
    import os

    if not check_kick(authorization, os.environ.get("CORELATA_KICK_TOKEN", "")):
        return JSONResponse({"detail": "wrong kick token"}, status_code=401)
    worker.spawn()
    return {"spawned": True}


@app.function(image=app_image, secrets=[secret], cpu=0.25, schedule=modal.Period(minutes=5))
def cron():
    """The minute tasks a long-running worker would run (orphaned runs and discoveries, the
    discovery deadlines), then a worker when a job is waiting and none is alive (one queued as a
    worker decided to exit, a failed kick, a retry whose backoff has passed), or when a worker
    that died left jobs stalled (spec §13.5)."""
    import asyncio

    from corelata.worker.app import cron_pass

    if asyncio.run(cron_pass(_config())):
        worker.spawn()


@app.function(image=app_image, secrets=[secret], cpu=0.25, schedule=modal.Cron("17 3 * * *"))
def purge():
    """Closed jobs older than worker.job_retention_days, daily (spec §13.5)."""
    import asyncio

    from corelata.worker.app import purge_pass

    asyncio.run(purge_pass(_config()))


@app.function(image=app_image, secrets=[secret], timeout=900)
def migrate():
    _render()
    run_cli(["corelata", "migrate"])


@app.function(image=app_image, secrets=[secret], timeout=900)
def doctor():
    _render()
    run_cli(["corelata", "doctor"])


@app.function(image=app_image, secrets=[secret], timeout=900)
def seed():
    """Queue the example report once (spec §13.6), then start the deployed app's worker. A
    function spawned from `modal run` belongs to that run's short-lived app and would stop with
    it, so the worker is looked up by name (R-M19-12); the cron would start one within 5
    minutes anyway."""
    import asyncio

    from corelata import service
    from corelata.store.db import Database, database_url

    async def project_names() -> list[str]:
        db = Database(database_url(cfg))
        try:
            return [p.name for p in await service.list_projects(db)]
        finally:
            await db.dispose()

    cfg = _config()
    command = seed_command(asyncio.run(project_names()))
    if command is None:
        print("the example project exists: nothing to seed")
        return
    run_cli(command)
    modal.Function.from_name(APP_NAME, "worker").spawn()
