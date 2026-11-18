"""A complete local Corelata for a browser: a throwaway database, the fake model server, a
worker, and the API serving the built web app. `make dev-stack` runs it for development (with
`pnpm dev` for live reloading); the Playwright journeys start it as their web server. Ctrl+C (or
SIGTERM) stops everything and drops the database. Copied from Coglossa without the scorer."""

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from types import FrameType

import yaml
from corelata.store.migrate import upgrade
from corelata.testing.postgres import TEST_DB_ENV, create_test_database, drop_test_database

CORELATA = [sys.executable, "-c", "import sys; from corelata.cli import main; sys.exit(main())"]
API = [sys.executable, "-c", "import sys; from corelata_api.main import main; sys.exit(main())"]
CSP_PROXY = [sys.executable, str(Path(__file__).with_name("csp_proxy.py"))]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout_s: float, procs: list[subprocess.Popen[bytes]]) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for p in procs:
            if p.poll() is not None:
                raise RuntimeError(f"{p.args} exited with {p.returncode}")
        with (
            contextlib.suppress(OSError),
            urllib.request.urlopen(url, timeout=1) as response,  # noqa: S310 (local URL)
        ):
            if response.status == 200:
                return
        time.sleep(0.2)
    raise RuntimeError(f"{url} did not answer within {timeout_s:.0f} s")


def config(work: Path, llm_port: int, web_dir: Path | None, progress_poll_s: float = 0.2) -> dict:
    api: dict = {"progress_poll_s": progress_poll_s}
    if web_dir is not None:
        api["web_dir"] = str(web_dir.resolve())
    return {
        "backends": {
            "local": {"base_url": f"http://127.0.0.1:{llm_port}/v1", "max_concurrency": 4}
        },
        "models": {"m1": {"backend": "local", "name": "fake-model", "context_window": 32768}},
        "roles": {role: {"model": "m1"} for role in ("gate", "writer", "conveyor", "auditor")},
        # what a new install's example config says (CRL-93): the Claims tab marks the quotes
        "pipeline": {"evidence_quotes": "required"},
        "storage": {"path": str(work / "files")},
        "worker": {"concurrency": 2, "stalled_after_s": 60},
        "api": api,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--web-dir", type=Path, help="the built web app (web/dist)")
    parser.add_argument(
        "--progress-poll-s",
        type=float,
        default=0.2,
        help="api.progress_poll_s: the poll while the API is not listening (default 0.2)",
    )
    parser.add_argument(
        "--csp-proxy-port",
        type=int,
        help="also serve the stack on this port behind the operator guide's sample CSP",
    )
    args = parser.parse_args(argv)
    admin = os.environ.get(TEST_DB_ENV)
    if not admin:
        print(
            f"error: set {TEST_DB_ENV} to a Postgres admin URL (make dev-stack does)",
            file=sys.stderr,
        )
        return 1
    url = create_test_database(admin)
    work = Path(tempfile.mkdtemp(prefix="corelata-dev-"))
    procs: list[subprocess.Popen[bytes]] = []

    def stop(signum: int | None = None, frame: FrameType | None = None) -> None:
        # Ignore further signals so that a repeated one cannot interrupt the cleanup.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        upgrade(url)
        llm = free_port()
        path = work / "corelata.yaml"
        cfg = config(work, llm, args.web_dir, args.progress_poll_s)
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        env = {**os.environ, "CORELATA_DATABASE_URL": url}
        procs.append(
            subprocess.Popen(
                [*CORELATA, "fake-openai", "--host", "127.0.0.1", "--port", str(llm)], env=env
            )
        )
        procs.append(subprocess.Popen([*CORELATA, "worker", "--config", str(path)], env=env))
        procs.append(
            subprocess.Popen(
                [*API, "--config", str(path), "--host", args.host, "--port", str(args.port)],
                env=env,
            )
        )
        wait_for(f"http://{args.host}:{args.port}/api/health", 60, procs)
        address = f"http://{args.host}:{args.port}"
        if args.csp_proxy_port is not None:
            proxied = f"http://{args.host}:{args.csp_proxy_port}"
            procs.append(
                subprocess.Popen(
                    [*CSP_PROXY, "--upstream", address, "--host", args.host]
                    + ["--port", str(args.csp_proxy_port)]
                )
            )
            wait_for(f"{proxied}/api/health", 30, procs)
            print(f"The same stack behind the sample CSP: {proxied}", flush=True)
        if args.web_dir is not None:
            print(f"Corelata is running at {address} (Ctrl+C to stop)", flush=True)
        else:  # the API alone: the app comes from `pnpm dev`, which forwards /api here
            print(
                f"The Corelata API is running at {address}; for the web app, run `pnpm dev` in "
                "web/ and open the address it prints (Ctrl+C to stop)",
                flush=True,
            )
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("error: a service stopped; shutting down", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=10)
            if p.poll() is None:
                p.kill()
        drop_test_database(admin, url)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
