"""Assert the resolved Compose model of deploy/compose.yaml (and the demo overlay): what
operators rely on and what install.sh, backup.sh and restore.sh assume. Runs
`docker compose config --format json`; needs Docker Compose, not a running daemon."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "CORELATA_DB_PASSWORD": "check", "CORELATA_VERSION": "9.9.9"}
LOGGING = {"driver": "json-file", "options": {"max-size": "50m", "max-file": "5"}}


def postgres_pin() -> str:
    """bundle.sh's POSTGRES_IMAGE: the one place the database image's digest is written
    (CRL-115)."""
    text = (DEPLOY / "bundle.sh").read_text()
    tag = re.search(r"^POSTGRES_TAG=(\S+)$", text, re.M)
    digest = re.search(r"^POSTGRES_IMAGE=\$POSTGRES_TAG@(sha256:[0-9a-f]{64})$", text, re.M)
    if not (tag and digest):
        sys.exit("check_compose: bundle.sh must set POSTGRES_TAG and POSTGRES_IMAGE=$POSTGRES_TAG@sha256:<digest>")
    return f"{tag.group(1)}@{digest.group(1)}"


def resolve(*files: str, env: dict | None = None) -> dict:
    cmd = ["docker", "compose", "--env-file", "/dev/null"]
    for f in files:
        cmd += ["-f", str(DEPLOY / f)]
    cmd += ["config", "--format", "json"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env or ENV, cwd=DEPLOY)
    return json.loads(out.stdout)


def expect(condition: bool, what: str) -> None:
    if not condition:
        sys.exit(f"check_compose: {what}")


def check_stack() -> None:
    model = resolve("compose.yaml")
    services = model["services"]
    expect(model["name"] == "corelata", f"project name is {model['name']!r}, want 'corelata'")
    expect(set(services) == {"postgres", "migrate", "worker", "api"}, f"services are {sorted(services)}")
    expect(set(model["volumes"]) == {"pgdata", "files"}, f"volumes are {sorted(model['volumes'])}")
    pg = services["postgres"]
    # the tag the bundle saves its digest-pinned pull under (bundle.sh, CRL-115)
    tag = postgres_pin().split("@")[0]
    expect(pg["image"] == tag, f"postgres image must be {tag}")
    expect(pg["environment"]["POSTGRES_USER"] == "corelata" and pg["environment"]["POSTGRES_DB"] == "corelata", "postgres user/db")
    expect(pg["healthcheck"]["test"][-1].startswith("pg_isready -h 127.0.0.1 -U corelata"), "postgres healthcheck")
    for name in ("postgres", "migrate", "worker", "api"):
        expect(services[name]["logging"] == LOGGING, f"{name} log rotation")
    for name in ("migrate", "worker", "api"):
        svc = services[name]
        expect(svc["image"] == "corelata/app:9.9.9", f"{name} image uses CORELATA_VERSION")
        expect(svc["environment"]["CORELATA_DATABASE_URL"] == "postgresql://corelata:check@postgres:5432/corelata", f"{name} database url")
        mounts = {(m["source"].rsplit("/", 1)[-1] if m["type"] == "bind" else m["source"], m["target"]) for m in svc["volumes"]}
        expect(("config", "/etc/corelata") in mounts and ("files", "/data/files") in mounts, f"{name} mounts: {mounts}")
        expect(any(h.startswith("host.docker.internal") for h in svc["extra_hosts"]), f"{name} extra_hosts")
    expect(services["migrate"]["command"] == ["corelata", "migrate"], "migrate runs `corelata migrate`")
    expect(services["migrate"]["restart"] == "no", "migrate must not restart")
    expect(services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy", "migrate waits for postgres")
    expect(services["worker"]["command"] == ["corelata", "worker"], "worker runs `corelata worker`")
    expect(services["worker"]["stop_grace_period"] in ("5m0s", "5m", 300_000_000_000), f"worker stop_grace_period is {services['worker']['stop_grace_period']!r}")
    for name in ("worker", "api"):
        expect(services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully", f"{name} waits for migrate")
        expect(services[name]["restart"] == "unless-stopped", f"{name} restart policy")
    expect(not services["api"].get("command"), "api uses the image's command")
    ports = services["api"]["ports"]
    expect(len(ports) == 1 and ports[0]["target"] == 8080 and str(ports[0]["published"]) == "8080" and ports[0]["host_ip"] == "0.0.0.0", f"api ports: {ports}")
    expect("/api/health" in services["api"]["healthcheck"]["test"][-1], "api healthcheck hits /api/health")
    overridden = resolve("compose.yaml", env={**ENV, "CORELATA_HTTP_BIND": "127.0.0.1", "CORELATA_HTTP_PORT": "9090"})
    port = overridden["services"]["api"]["ports"][0]
    expect(port["host_ip"] == "127.0.0.1" and str(port["published"]) == "9090", f"CORELATA_HTTP_BIND/PORT are honoured: {port}")


def check_demo() -> None:
    model = resolve("compose.yaml", "compose.demo.yaml")
    services = model["services"]
    expect(model["name"] == "corelata-demo", "demo project name")
    expect(set(services) == {"postgres", "migrate", "worker", "api", "fake-openai"}, f"demo services are {sorted(services)}")
    fake = services["fake-openai"]
    expect(fake["command"] == ["corelata", "fake-openai", "--host", "0.0.0.0", "--port", "8000", "--model", "fake-model"], "fake-openai command")
    expect("/v1/models" in fake["healthcheck"]["test"][-1], "fake-openai healthcheck")
    for name in ("migrate", "worker", "api"):
        expect(services[name]["environment"]["CORELATA_CONFIG"] == "/etc/corelata/corelata.demo.yaml", f"{name} uses the demo config")
    expect(services["worker"]["depends_on"]["fake-openai"]["condition"] == "service_healthy", "worker waits for the fake model")


def check_dev() -> None:
    """The test database pulls the bundle's pinned image (CRL-115)."""
    model = resolve("compose.dev.yaml")
    image = model["services"]["postgres"]["image"]
    expect(image == postgres_pin(), f"compose.dev.yaml postgres image is {image}, want {postgres_pin()}")


def check_password_required() -> None:
    env = {k: v for k, v in ENV.items() if k != "CORELATA_DB_PASSWORD"}
    out = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(DEPLOY / "compose.yaml"), "config", "-q"], capture_output=True, text=True, env=env, cwd=DEPLOY)
    expect(out.returncode != 0 and "run ./install.sh first" in out.stderr, "a missing password must say to run install.sh")


if __name__ == "__main__":
    check_stack()
    check_demo()
    check_dev()
    check_password_required()
    print("check_compose: ok")
