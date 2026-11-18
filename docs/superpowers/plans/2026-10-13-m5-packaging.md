# Corelata M5: Packaging and Operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver spec §14 M5: one app image (API serving the web build, worker, CLI, fake model server), the Compose stack (`postgres`, one-shot `migrate`, `worker`, `api`) with demo and dev overlays, the offline bundle `corelata-<ver>-linux-amd64.tar` (+ `.sha256`) holding the images, example config and the base pack, `install.sh`, `backup.sh`, `restore.sh`, the operator guide, SBOMs, a manifest and `SHA256SUMS`; `make deploy-check` (shellcheck, install and restore tests, compose check) and `make airgap-test` (install on a network with no route out, run a full report against the fake model, back up, upgrade, restore) green in CI.

**Architecture:** Everything under `deploy/` is copied from Coglossa (spec §4.3) with the product name parameterised and the scorer, weights, tiers, FLORES/bench and GPU parts removed; the app Dockerfile gains Corelata's example sources, the compose `migrate` service runs `corelata migrate`, and the air-gap smoke test drives Corelata's own flow (project → upload → run → report exports) through the API from inside the sealed network. `install.sh` never overwrites `config/corelata.yaml`, `config/packs/` or `.env`; `backup.sh` dumps Postgres and tars the files volume; `restore.sh` replaces both in one transaction with rollback; `bundle.sh` builds the images, saves them, writes manifest, SBOMs (syft) and checksums, and tars with root ownership.

**Tech Stack:** Docker Engine ≥ 24, Docker Compose plugin ≥ 2.24 (`!reset` tag), `python:3.12-slim-bookworm` + `uv 0.13` + `node:22-bookworm-slim` build stages, `postgres:16-alpine`, bash + coreutils + tar, shellcheck `koalaman/shellcheck:v0.10.0` (container), syft `anchore/syft:v1.18.1` (container), GitHub Actions `ubuntu-latest`.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §4.2 (`deploy/`), §4.3 (copy rule), §11 (configuration), §12 (packaging and operations: services, image, overlays, bundle contents, `install.sh` behaviour, CI `deploy-check` and `airgap-test`), §13 (air-gap test), §14 (M5 row: `make airgap-test` green). Follow-ups that bind this milestone: `docs/m3-followups.md` ("M5: compose `migrate` one-shot runs `corelata migrate`; `worker` gets a `stop_grace_period` long enough for a stage; stalled-job cleanup belongs in the operations guide"), `docs/m4a-followups.md` ("M5: the app image's `CMD` is `corelata-api --host 0.0.0.0 --port 8080 --web-dir /opt/corelata/web`; compose `api` depends on `migrate`; healthcheck on `/api/health`"), `docs/m4b-followups.md` ("M5: web stage `pnpm build`, `COPY --from=web /src/web/dist /opt/corelata/web`; `.dockerignore` web entries"). Coglossa source for copied files: `~/Downloads/coglossa/deploy/` (`docker/app.Dockerfile`, `compose.yaml`, `compose.demo.yaml`, `install.sh`, `backup.sh`, `restore.sh`, `bundle.sh`, `tests/{test-install.sh,test-restore.sh,check-bundle.sh,check-app-image.sh,check_compose.py,smoke.py,airgap-test.sh,compose.airgap.yaml}`, `config/*.yaml`), `~/Downloads/coglossa/docs/operator-guide.md`, `~/Downloads/coglossa/.dockerignore`, `Makefile`, `.github/workflows/ci.yml`. The implementer reads the Coglossa file named in each task and applies the listed edits; where a file changes substantially, this plan gives the full content.

**Working directory for every command below:** the repository root (the one containing `Makefile`). Docker must be running; `make db-up` is not needed by this milestone's tests (they use their own compose projects).

## Global Constraints

- Product name parameterised (spec §4.3): image `corelata/app`, label title `corelata-app`, source `https://github.com/Bonham-Technologies/corelata`; compose projects `corelata`, `corelata-demo`, `corelata-dev` (existing), test override `corelata-airgaptest`; env `CORELATA_VERSION`, `CORELATA_DB_PASSWORD`, `CORELATA_DATABASE_URL`, `CORELATA_HTTP_BIND`, `CORELATA_HTTP_PORT`, `CORELATA_CONFIG=/etc/corelata/corelata.yaml`; paths `/etc/corelata`, `/opt/corelata/web`, `/opt/corelata/examples`, `/data/files`; database user/db `corelata`; dump `corelata-db-<stamp>.dump`, archive `corelata-files-<stamp>.tar.gz`; bundle `corelata-<version>` / `corelata-<version>-linux-amd64.tar`.
- Container user uid:gid 10001:10001 named `corelata`; `/data/files` owned by it; `config/` mounted read-only and made world-readable by `install.sh` (it holds no secrets: keys live in `.env`, mode 600).
- `install.sh` never overwrites `config/corelata.yaml`, `config/packs/` or `.env`; those files are not in `SHA256SUMS`. It verifies `SHA256SUMS` first, refuses a damaged bundle before loading anything, requires Compose ≥ 2.24.0, loads the images, creates the three artefacts when missing, prints next steps; exit 1 on error, 2 on a bad option.
- The compose `migrate` service runs `corelata migrate` and `api`/`worker` wait for it (`service_completed_successfully`); `worker` has `stop_grace_period: 5m` (a stage may take minutes; an unfinished run is started over by the stalled-job requeue); `api` healthcheck on `/api/health`; `postgres:16-alpine` pinned by tag; log rotation `json-file` 50m × 5; `restart: unless-stopped` except `migrate`; no resource limits.
- Everything Corelata stores lives in Postgres `public` (incl. procrastinate's tables) and `/data/files`; `backup.sh`/`restore.sh` cover exactly those two.
- The bundle contents (spec §12): `images/{app,postgres}.tar`, `config/corelata.example.yaml`, `config/corelata.demo.yaml`, `config/packs/icd203-base/` (a copy of the engine's built-in pack), `examples/varna-port.txt`, `compose.yaml`, `compose.demo.yaml`, `install.sh`, `backup.sh`, `restore.sh`, `operator-guide.md`, `sbom/{app,postgres,web}.cdx.json`, `manifest.json`, `VERSION`, `SHA256SUMS`; tar members owned by uid/gid 0 (`--numeric-owner`); `<tar>.sha256` beside it.
- The version is `--version V`, else the exact git tag at HEAD (leading `v` stripped), else `<corelata.__version__>-g<short sha>`; it becomes the image tag, the `org.opencontainers.image.version` label, the bundle name, `VERSION`, `manifest.json`, and replaces `${CORELATA_VERSION:-dev}` in the bundled compose files. `GET /api/health` keeps returning the package version (`corelata.__version__`), as Coglossa does; recorded as a follow-up.
- Scripts pass shellcheck v0.10.0 (the pinned container) with no directives beyond what the Coglossa originals carry; `python3` scripts use the standard library only.
- `make deploy-check` runs without Docker images being built (stub-docker tests + compose config); `make airgap-test` builds the image and bundle and needs Docker and about 5 GB of disk; both run in CI (`deploy` and `airgap` jobs).
- Every intentional change to a copied file is recorded in `docs/m5-followups.md` under **Divergences from Coglossa** with a one-line reason; improvements Coglossa should take are tagged **backport** (Task 7 writes the file; earlier tasks note what to record).
- No changes to the engine, API or web source except: none expected. If one proves necessary (e.g. a missing CLI flag), stop and rule.
- Commits: conventional prefix (`build:`, `test:`, `docs:`, `fix:`), one task per commit unless a step says otherwise, ending with the attribution lines the session supplies.

## Review Focus

1. **A damaged or incomplete bundle** (an altered example config, a missing image tar, no `SHA256SUMS`) is refused by `install.sh` before any image is loaded or `.env` created, with the bad file names in the message. (Task 3 `test-install.sh` cases; Task 6 air-gap step 2.)
2. **Re-running `install.sh` on an existing install or an upgrade** changes none of `config/corelata.yaml`, `config/packs/**` and `.env`, and the operator's edited pack survives the upgrade and is what the new version uses. (Task 3 `test-install.sh` "second run"; Task 6 air-gap upgrade step asserts the edited pack rule text is served by `GET /api/packs/icd203-base/resolved` after the upgrade.)
3. **`restore.sh` over a newer schema** drops `public` and restores the dump in one transaction; a failing dump rolls back and the stack is restarted with its data intact; the files volume is replaced only after the database restore succeeded. (Task 3 `test-restore.sh`; Task 6 air-gap restore step with a fake newer table and `alembic_version`.)
4. **The stack on a network with no route out** completes a real report run end to end against the fake model: project, upload, run, `completed`, DOCX/HTML/Markdown/trace exports download with the right magic bytes; the API container cannot reach the internet. (Task 6 `smoke.py run` + the `1.1.1.1:443` probe.)
5. **An invalid `config/corelata.yaml` after a change** makes `migrate` fail and keeps `api`/`worker` down, with the reason in `docker compose logs migrate`; a valid change applied with `up -d --wait --force-recreate migrate api worker` restarts the worker and the API and the doctor passes. (Task 6 air-gap config-change step; Task 5 troubleshooting row.)

---

## File structure

| Path | Responsibility |
|---|---|
| `deploy/docker/app.Dockerfile` (new, copied) | three-stage image: web build, Python venv (engine + api), runtime as uid 10001; `/opt/corelata/examples` |
| `.dockerignore` (new, copied) | allowlist build context |
| `deploy/tests/check-app-image.sh` (new, copied) | the image's contract (user, commands, env, web files, package data, label, no-config failure) |
| `deploy/compose.yaml`, `deploy/compose.demo.yaml` (new, copied), `deploy/compose.dev.yaml` (existing) | the stack; the demo overlay with `fake-openai`; the dev database |
| `deploy/config/corelata.example.yaml`, `deploy/config/corelata.demo.yaml` (new) | the operator's starting config (packs dir, roles, storage, api, auth) and the demo config |
| `deploy/tests/check_compose.py` (new) | asserts the resolved compose model |
| `deploy/install.sh`, `deploy/backup.sh`, `deploy/restore.sh` (new, copied) | install/upgrade, backup, restore |
| `deploy/tests/test-install.sh`, `deploy/tests/test-restore.sh` (new, copied) | stub-docker tests of the two scripts |
| `deploy/bundle.sh`, `deploy/tests/check-bundle.sh` (new, copied) | build and verify the offline bundle (images, config, pack, examples, SBOMs, manifest, checksums) |
| `docs/operator-guide.md` (new) | the guide shipped in the bundle |
| `deploy/tests/smoke.py`, `deploy/tests/compose.airgap.yaml`, `deploy/tests/airgap-test.sh` (new) | the sealed-network end-to-end test |
| `Makefile`, `.github/workflows/ci.yml`, `.gitignore` (modify) | `image-app`, `bundle`, `demo`, `demo-down`, `deploy-check`, `airgap-test`; CI `deploy` and `airgap` jobs; ignore `deploy/.env`, `deploy/config/corelata.yaml`, `deploy/config/packs/`, `deploy/backups/` |
| `README.md`, `docs/m5-followups.md`, spec §12 (modify) | documentation |

---

### Task 1: The app image

**Files:**
- Create: `deploy/docker/app.Dockerfile`, `.dockerignore`, `deploy/tests/check-app-image.sh`
- Modify: `Makefile` (`image-app`, `CORELATA_VERSION`, `PLATFORM`)

**Interfaces:**
- Consumes: `engine/` (package `corelata`, `uv.lock`), `api/` (package `corelata_api`, `uv.lock`, script `corelata-api`), `web/` (`pnpm build` → `dist/`), `docs/examples/varna-port.txt`; CLI `corelata --version`, `corelata-api --help`.
- Produces: image `corelata/app:<version>` with `CMD ["corelata-api","--host","0.0.0.0","--port","8080","--web-dir","/opt/corelata/web"]`, `ENV CORELATA_CONFIG=/etc/corelata/corelata.yaml`, user 10001, `/data/files` writable, web at `/opt/corelata/web`, examples at `/opt/corelata/examples`; `deploy/tests/check-app-image.sh IMAGE`; `make image-app` (builds and checks).

- [ ] **Step 1: Write `.dockerignore`**

```
# The build context is an allowlist: only what the image needs. This keeps .venv,
# node_modules, caches and local configs out of the image and the build.
*
!engine/pyproject.toml
!engine/uv.lock
!engine/corelata/
!api/pyproject.toml
!api/uv.lock
!api/corelata_api/
!web/
!docs/examples/
web/node_modules/
web/dist/
web/coverage/
web/playwright-report/
web/test-results/
**/__pycache__/
**/.pytest_cache/
```

- [ ] **Step 2: Write the Dockerfile**

`deploy/docker/app.Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
# The Corelata app image (spec §12): the API serving the built web app, the worker, the CLI
# (migrate, doctor, run) and the fake model server of the demo. Build it from the repository
# root:  docker build -f deploy/docker/app.Dockerfile -t corelata/app:dev .

FROM node:22-bookworm-slim AS web
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /src/web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm AS python
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY engine/pyproject.toml engine/uv.lock engine/
COPY api/pyproject.toml api/uv.lock api/
# Dependencies first, so a code change does not reinstall them.
RUN cd api && uv sync --frozen --no-dev --no-install-project --no-install-package corelata
COPY engine/corelata engine/corelata
COPY api/corelata_api api/corelata_api
RUN cd api && uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
ARG VERSION=dev
LABEL org.opencontainers.image.title="corelata-app" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/Bonham-Technologies/corelata"
RUN groupadd --gid 10001 corelata \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin corelata \
 && mkdir -p /data/files /etc/corelata \
 && chown corelata:corelata /data/files
COPY --from=python /opt/venv /opt/venv
COPY --from=web /src/web/dist /opt/corelata/web
COPY docs/examples/ /opt/corelata/examples/
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CORELATA_CONFIG=/etc/corelata/corelata.yaml
USER 10001:10001
WORKDIR /data
EXPOSE 8080
CMD ["corelata-api", "--host", "0.0.0.0", "--port", "8080", "--web-dir", "/opt/corelata/web"]
```

`uv sync --frozen` inside `api/` installs the engine through the `[tool.uv.sources] corelata = { path = "../engine", editable = true }` entry; `--no-editable` copies it into the venv so `/src` is not needed at runtime. The `web/pnpm-lock.yaml` must be current (`pnpm install --frozen-lockfile` fails otherwise).

- [ ] **Step 3: Write the image check**

`deploy/tests/check-app-image.sh` (the Coglossa original is at `~/Downloads/coglossa/deploy/tests/check-app-image.sh`; this is its Corelata form):

```bash
#!/usr/bin/env bash
# What the app image must provide (spec §12), checked with the image alone and no network.
# Usage: deploy/tests/check-app-image.sh IMAGE
set -euo pipefail
image=${1:?usage: check-app-image.sh IMAGE}
die() { echo "error: $*" >&2; exit 1; }
run() { docker run --rm --network none --entrypoint "" "$image" "$@"; }

echo "Checking $image ..."
[ "$(run id -u):$(run id -g)" = "10001:10001" ] || die "the image must run as uid:gid 10001:10001"
run corelata --version | grep -q '^corelata ' || die "corelata --version does not work"
run corelata-api --help >/dev/null || die "corelata-api --help does not work"
[ "$(run sh -c 'echo $CORELATA_CONFIG')" = /etc/corelata/corelata.yaml ] \
  || die "CORELATA_CONFIG must be /etc/corelata/corelata.yaml"
run test -f /opt/corelata/web/index.html || die "the web app is missing (/opt/corelata/web/index.html)"
run sh -c 'ls /opt/corelata/web/assets/*.js >/dev/null' || die "the web app's assets are missing"
run test -f /opt/corelata/examples/varna-port.txt || die "the example source is missing"
run sh -c 'touch /data/files/.probe && rm /data/files/.probe' || die "/data/files is not writable by the app user"
site=$(run python -c 'import corelata, pathlib; print(pathlib.Path(corelata.__file__).parent)')
for f in store/migrations/versions/0002_corelata_schema.py store/migrations/versions/0001_procrastinate_3_10_0.sql \
  prompts/templates/gate/v1.j2 render/templates/report.html.j2 standards/packs/icd203-base/pack.yaml \
  ingest/vendor/coglossa-report-1.schema.json; do
  run test -f "$site/$f" || die "package data is missing from the image: $f"
done
label=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image")
[ -n "$label" ] || die "the org.opencontainers.image.version label is empty"
# The image's own command refuses to start without a config, with one clear line.
if out=$(docker run --rm --network none "$image" 2>&1); then
  die "corelata-api started without a config; it should refuse"
fi
printf '%s\n' "$out" | grep -q 'config file not found: /etc/corelata/corelata.yaml' \
  || die "the no-config failure should name the config path; got: $out"
echo "ok: $image"
```

Check the prompt template directory names in `engine/corelata/prompts/templates/` (`gate/v1.j2` is expected; adjust if the version file is named differently) before relying on them.

- [ ] **Step 4: Makefile**

Add near the top of the `Makefile`:

```make
CORELATA_VERSION ?= dev
PLATFORM ?= linux/amd64
```

and the target (add `image-app` to `.PHONY`):

```make
image-app:
	docker build --platform $(PLATFORM) -f deploy/docker/app.Dockerfile \
	  --build-arg VERSION=$(CORELATA_VERSION) -t corelata/app:$(CORELATA_VERSION) .
	deploy/tests/check-app-image.sh corelata/app:$(CORELATA_VERSION)
```

- [ ] **Step 5: Build and check**

Run: `chmod +x deploy/tests/check-app-image.sh && make image-app`
Expected: the build succeeds (the web stage runs `pnpm build`; the Python stage `uv sync`), then `ok: corelata/app:dev`. On an Apple Silicon host `--platform linux/amd64` builds under emulation (slower); if the Docker daemon cannot emulate, set `PLATFORM=linux/arm64` for the local check only and say so in the report (CI is amd64).

- [ ] **Step 6: Commit**

```bash
git add deploy/docker/app.Dockerfile .dockerignore deploy/tests/check-app-image.sh Makefile
git commit -m "build: the Corelata app image and its contract check"
```

---

### Task 2: The Compose stack, the demo overlay and the config files

**Files:**
- Create: `deploy/compose.yaml`, `deploy/compose.demo.yaml`, `deploy/config/corelata.example.yaml`, `deploy/config/corelata.demo.yaml`, `deploy/tests/check_compose.py`
- Modify: `Makefile` (`demo`, `demo-down`, `check-compose` line inside `deploy-check` later), `.gitignore`

**Interfaces:**
- Consumes: the image (Task 1), `corelata migrate`, `corelata worker`, `corelata fake-openai --host --port --model`, `CORELATA_DATABASE_URL`, `CORELATA_CONFIG`.
- Produces: the stack `corelata` (services `postgres`, `migrate`, `worker`, `api`; volumes `pgdata`, `files`), the overlay `corelata-demo` (adds `fake-openai`, points `CORELATA_CONFIG` at the demo file), the example and demo configs, `python3 deploy/tests/check_compose.py` (asserts the resolved model), `make demo`/`make demo-down`.

- [ ] **Step 1: Write `deploy/compose.yaml`**

```yaml
# Corelata on one host (spec §12). Run it from the directory this file is in:
#   ./install.sh                  once: loads the images; creates config/corelata.yaml,
#                                 config/packs/ and .env
#   docker compose up -d --wait   start; migrations run first
#   docker compose up -d --wait --force-recreate migrate api worker
#                                 apply a change to config/ or .env (the config is read at start)
#   docker compose exec api corelata doctor
# The operator guide (operator-guide.md) explains every setting.
name: corelata

x-logging: &logging
  driver: json-file
  options: { max-size: 50m, max-file: "5" }

x-app: &app
  image: corelata/app:${CORELATA_VERSION:-dev}
  restart: unless-stopped
  env_file:
    - path: .env # model-server API keys (api_key_env in the config) go here too
      required: false
  environment:
    CORELATA_DATABASE_URL: postgresql://corelata:${CORELATA_DB_PASSWORD:?run ./install.sh first; it creates .env with the database password}@postgres:5432/corelata
  volumes:
    - ./config:/etc/corelata:ro
    - files:/data/files
  extra_hosts:
    - host.docker.internal:host-gateway # a model server on this host (e.g. vLLM, Ollama)
  logging: *logging

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: corelata
      POSTGRES_PASSWORD: ${CORELATA_DB_PASSWORD:?run ./install.sh first; it creates .env with the database password}
      POSTGRES_DB: corelata
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U corelata -d corelata"]
      interval: 5s
      timeout: 5s
      retries: 30
    logging: *logging

  migrate: # creates or upgrades the database schema, then exits; api and worker wait for it
    <<: *app
    restart: "no"
    command: [corelata, migrate]
    depends_on:
      postgres: { condition: service_healthy }

  worker:
    <<: *app
    command: [corelata, worker]
    stop_grace_period: 5m # lets the running stage finish; an unfinished run is started over
    depends_on:
      migrate: { condition: service_completed_successfully }

  api:
    <<: *app # the image's command: corelata-api serving the web app on 8080
    ports:
      - ${CORELATA_HTTP_BIND:-0.0.0.0}:${CORELATA_HTTP_PORT:-8080}:8080
    depends_on:
      migrate: { condition: service_completed_successfully }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5)"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s

volumes:
  pgdata: {}
  files: {}
```

- [ ] **Step 2: Write `deploy/compose.demo.yaml`**

```yaml
# The demo: Corelata with a synthetic model, to try the stack before pointing it at model
# servers (operator guide, "Try it first"). Reports are placeholders built from the sources.
#   docker compose -f compose.yaml -f compose.demo.yaml up -d --wait
# The demo has its own project, so it never shares the real install's volumes.
name: corelata-demo

x-demo-config: &demo-config
  CORELATA_CONFIG: /etc/corelata/corelata.demo.yaml

services:
  fake-openai:
    image: corelata/app:${CORELATA_VERSION:-dev}
    restart: unless-stopped
    command: [corelata, fake-openai, --host, 0.0.0.0, --port, "8000", --model, fake-model]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/models', timeout=5)"]
      interval: 5s
      timeout: 5s
      retries: 12
    logging:
      driver: json-file
      options: { max-size: 50m, max-file: "5" }

  migrate:
    environment: *demo-config
  worker:
    environment: *demo-config
    depends_on:
      fake-openai: { condition: service_healthy }
  api:
    environment: *demo-config
```

- [ ] **Step 3: Write the config files**

`deploy/config/corelata.example.yaml` (the operator's starting point; paths are container paths):

```yaml
# Corelata configuration (operator guide, "Configuration"). install.sh copies this file to
# config/corelata.yaml once and never overwrites it. Edit that copy, then apply it with
#   docker compose up -d --wait --force-recreate migrate api worker
# Any OpenAI-compatible server works: vLLM, Ollama, TGI, llama.cpp server, LM Studio.
backends:
  local:
    base_url: http://host.docker.internal:8000/v1   # a server on this host; or http://<server>:8000/v1
    # api_key_env: CORELATA_LOCAL_KEY    # name of a variable in .env, if the server needs a key
    max_concurrency: 4
    timeout_s: 120

models:
  strong:                          # the key is how roles refer to the model
    backend: local
    name: Qwen/Qwen3-32B           # the model id the server expects
    context_window: 32768
    structured_output: json_schema # json_schema | json_object | none
    max_output_tokens: 8192
    temperature: 0.2

roles:                             # spec §4.4; one model per role
  gate:     { model: strong }
  writer:   { model: strong }
  conveyor: { model: strong }
  auditor:  { model: strong }      # a different model family from the writer is better when you have one

standards:                         # spec §6: your packs live in config/packs (mounted read-only)
  packs_dir: /etc/corelata/packs
  default_pack: icd203-base        # tune or replace it in config/packs/icd203-base
  # default_profile: team-east     # a profile from config/packs/<pack>/profiles

pipeline:                          # spec §7
  max_iterations: 2                # audit loop bound; the report is delivered either way
  digest_threshold_tokens: 6000
  digest_chunk_tokens: 4000
  writer_unit_budget_tokens: 16000
  gate_unit_budget_tokens: 12000

storage: { path: /data/files }     # the `files` volume: uploaded sources, reference documents, exports
worker: { concurrency: 2, stalled_after_s: 900 }
api: { max_upload_mb: 200, progress_poll_s: 1.0 }
auth: { mode: none }               # trusted_header when a reverse proxy signs people in (operator guide)
# auth: { mode: trusted_header, header: X-Remote-User }
# integrations:
#   coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
# The database is set by the containers (CORELATA_DATABASE_URL); do not add a database section.
```

`deploy/config/corelata.demo.yaml`:

```yaml
# The demo configuration: the synthetic model server of compose.demo.yaml (operator guide,
# "Try it first"). Everything else is the example's.
backends:
  demo: { base_url: http://fake-openai:8000/v1, max_concurrency: 4, timeout_s: 60 }
models:
  m1: { backend: demo, name: fake-model, context_window: 32768 }
roles:
  gate: { model: m1 }
  writer: { model: m1 }
  conveyor: { model: m1 }
  auditor: { model: m1 }
standards: { packs_dir: /etc/corelata/packs, default_pack: icd203-base }
storage: { path: /data/files }
worker: { concurrency: 2, stalled_after_s: 120 }
api: { max_upload_mb: 200, progress_poll_s: 0.5 }
```

Both files must load with `load_config` (strict pydantic). Verify from `engine/`: `uv run python -c "from pathlib import Path; from corelata.config import load_config; [print(load_config(Path(p))[0].standards) for p in ('../deploy/config/corelata.example.yaml','../deploy/config/corelata.demo.yaml')]"` — `validate_config` checks `standards.packs_dir` exists, so for this local check create a temporary copy with `packs_dir` removed, or run the check with `packs_dir: ../engine/corelata/standards/packs` substituted; the container path exists at runtime. Say which you did.

- [ ] **Step 4: Write `check_compose.py`**

`deploy/tests/check_compose.py` (standard library only; the Coglossa original at `~/Downloads/coglossa/deploy/tests/check_compose.py` shows the shape; this is Corelata's):

```python
"""Assert the resolved Compose model of deploy/compose.yaml (and the demo overlay): what
operators rely on and what install.sh, backup.sh and restore.sh assume. Runs
`docker compose config --format json`; needs Docker Compose, not a running daemon."""

import json
import os
import subprocess
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "CORELATA_DB_PASSWORD": "check", "CORELATA_VERSION": "9.9.9"}
LOGGING = {"driver": "json-file", "options": {"max-size": "50m", "max-file": "5"}}


def resolve(*files: str) -> dict:
    cmd = ["docker", "compose", "--env-file", "/dev/null"]
    for f in files:
        cmd += ["-f", str(DEPLOY / f)]
    cmd += ["config", "--format", "json"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True, env=ENV, cwd=DEPLOY)
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
    expect(pg["image"] == "postgres:16-alpine", "postgres image must be postgres:16-alpine")
    expect(pg["environment"]["POSTGRES_USER"] == "corelata" and pg["environment"]["POSTGRES_DB"] == "corelata", "postgres user/db")
    expect(pg["healthcheck"]["test"][-1].startswith("pg_isready -U corelata"), "postgres healthcheck")
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
    expect("command" not in services["api"], "api uses the image's command")
    ports = services["api"]["ports"]
    expect(len(ports) == 1 and ports[0]["target"] == 8080 and str(ports[0]["published"]) == "8080" and ports[0]["host_ip"] == "0.0.0.0", f"api ports: {ports}")
    expect("/api/health" in services["api"]["healthcheck"]["test"][-1], "api healthcheck hits /api/health")
    bind = resolve("compose.yaml")  # the defaults above; now the overrides
    env = {**ENV, "CORELATA_HTTP_BIND": "127.0.0.1", "CORELATA_HTTP_PORT": "9090"}
    out = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(DEPLOY / "compose.yaml"), "config", "--format", "json"], check=True, capture_output=True, text=True, env=env, cwd=DEPLOY)
    port = json.loads(out.stdout)["services"]["api"]["ports"][0]
    expect(port["host_ip"] == "127.0.0.1" and str(port["published"]) == "9090", f"CORELATA_HTTP_BIND/PORT are honoured: {port}")
    del bind


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


def check_password_required() -> None:
    env = {k: v for k, v in ENV.items() if k != "CORELATA_DB_PASSWORD"}
    out = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(DEPLOY / "compose.yaml"), "config", "-q"], capture_output=True, text=True, env=env, cwd=DEPLOY)
    expect(out.returncode != 0 and "run ./install.sh first" in out.stderr, "a missing password must say to run install.sh")


if __name__ == "__main__":
    check_stack()
    check_demo()
    check_password_required()
    print("check_compose: ok")
```

Compose renders `stop_grace_period` as a duration string (`5m0s`) in JSON; the tuple above covers the forms seen across versions — print the actual value on failure and adjust the accepted forms if yours differs.

- [ ] **Step 5: Makefile and `.gitignore`**

Add to the `Makefile` (and `.PHONY`):

```make
COMPOSE_DEMO = cd deploy && CORELATA_DB_PASSWORD=$${CORELATA_DB_PASSWORD:-demo} \
  CORELATA_HTTP_BIND=127.0.0.1 docker compose -p corelata-demo -f compose.yaml -f compose.demo.yaml

demo: image-app
	$(COMPOSE_DEMO) up -d --wait
	@echo "Corelata with the demo model: http://127.0.0.1:$${CORELATA_HTTP_PORT:-8080}"

demo-down:
	$(COMPOSE_DEMO) down -v
```

Append to `.gitignore`:

```
deploy/.env
deploy/config/corelata.yaml
deploy/config/packs/
deploy/backups/
```

- [ ] **Step 6: Verify**

Run: `python3 deploy/tests/check_compose.py` → `check_compose: ok`. Then `make demo` (uses the image from Task 1): all services healthy; `docker compose -p corelata-demo -f deploy/compose.yaml -f deploy/compose.demo.yaml exec api corelata doctor` passes (the demo config needs `/etc/corelata/packs/icd203-base` — for this local demo copy the built-in pack: `mkdir -p deploy/config/packs && cp -R engine/corelata/standards/packs/icd203-base deploy/config/packs/` — Task 3's `install.sh` does this on a real install). Then `make demo-down`.

- [ ] **Step 7: Commit**

```bash
git add deploy/compose.yaml deploy/compose.demo.yaml deploy/config deploy/tests/check_compose.py Makefile .gitignore
git commit -m "build: the Compose stack, the demo overlay and the operator config files"
```

---

### Task 3: install, backup and restore scripts with their stub-docker tests; `make deploy-check`; CI `deploy` job

**Files:**
- Create: `deploy/install.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `deploy/tests/test-install.sh`, `deploy/tests/test-restore.sh`
- Modify: `Makefile` (`deploy-check`, `SHELLCHECK`), `.github/workflows/ci.yml` (`deploy` job)

**Interfaces:**
- Consumes: the bundle layout (Global Constraints), `compose.yaml` service names (`postgres`, `api`, `worker`), the database user/db `corelata`.
- Produces: `./install.sh` (no options besides `-h/--help`; creates `config/corelata.yaml` from `config/corelata.example.yaml`, `config/packs/` from `config/packs.example/` — see below — and `.env` with `CORELATA_DB_PASSWORD`), `./backup.sh [DIR]`, `./restore.sh [--yes] DB_DUMP FILES_ARCHIVE`; `make deploy-check` = shellcheck (container) + the two stub tests + `check_compose.py`; CI `deploy` job.

Ruling on the pack directory: the bundle ships the base pack as `config/packs.example/icd203-base/` (in `SHA256SUMS`); `install.sh` copies it to `config/packs/icd203-base/` when `config/packs/` does not exist, so the operator's edits live in `config/packs/` and are never overwritten (spec §12 "upgrades never overwrite the customer's pack directory"). `check-bundle.sh` asserts `config/packs/` is absent from the bundle.

- [ ] **Step 1: Write `deploy/install.sh`**

Start from `~/Downloads/coglossa/deploy/install.sh` and produce:

```bash
#!/usr/bin/env bash
# Install or upgrade Corelata from this bundle (operator guide, "Install"). It checks the
# bundle's checksums, loads its images into Docker, and creates config/corelata.yaml,
# config/packs/ and .env when they do not exist yet; it never overwrites them.
# Usage: ./install.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
self=$here/$(basename "$0")
cd "$here"

MIN_COMPOSE=2.24.0
die() { echo "error: $*" >&2; exit 1; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

for arg in "$@"; do
  case $arg in
    -h | --help) sed -n '2,5s/^# \{0,1\}//p' "$self"; exit 0 ;;
    *) echo "error: unknown option $arg (usage: ./install.sh)" >&2; exit 2 ;;
  esac
done

# 1. The bundle is complete and undamaged.
[ -f SHA256SUMS ] || die "SHA256SUMS is missing: this is not a complete Corelata bundle; copy it again"
echo "Checking the bundle's checksums ..."
if ! report=$(sha256 -c SHA256SUMS 2>&1); then
  # sha256sum and shasum word a missing or altered file differently; collect the names from both.
  bad=$(printf '%s\n' "$report" | { grep -E 'FAILED|No such file' || true; } \
    | sed -E 's/: FAILED.*//; s/^[a-z0-9]*sum: +//; s/: No such file.*//' | sort -u | head -3 | paste -sd ' ' -)
  die "the bundle is damaged or incomplete (${bad:-checksums do not match}); copy it again and re-run ./install.sh"
fi

# 2. Docker and a recent enough Compose.
command -v docker >/dev/null || die "docker is not installed (operator guide, Requirements)"
compose=$(docker compose version --short 2>/dev/null) \
  || die "the Docker Compose plugin is missing; install Docker Compose $MIN_COMPOSE or newer"
compose=${compose#v}
if [ "$(printf '%s\n%s\n' "$MIN_COMPOSE" "$compose" | sort -V | head -n1)" != "$MIN_COMPOSE" ]; then
  die "Docker Compose $compose is too old; Corelata needs $MIN_COMPOSE or newer"
fi

# 3. The images.
for archive in images/*.tar; do
  echo "Loading $archive ..."
  docker load -i "$archive" >/dev/null || die "docker could not load $archive; is the Docker daemon running?"
done

# 4. The config, the packs and the database password: created once, never overwritten.
if [ ! -f config/corelata.yaml ]; then cp config/corelata.example.yaml config/corelata.yaml; fi
if [ ! -d config/packs ]; then cp -R config/packs.example config/packs; fi
# The containers run as uid 10001 and read config/ through a bind mount. A hardened host's
# umask (027, 077) applies to the extracted bundle and to the copies above, so open them up.
# They hold no secrets: model-server keys live in .env, which stays mode 600.
chmod -R a+rX config
if [ ! -f .env ]; then
  password=$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')
  (
    umask 077
    printf '%s\n' \
      "# Created by install.sh. Keep this file: the database was created with this password." \
      "CORELATA_DB_PASSWORD=$password" >.env
  )
fi

cat <<EOF

Corelata $(cat VERSION) is installed. Next:
  1. Edit config/corelata.yaml: your model servers (backends), models and roles.
     Your standards packs live in config/packs (icd203-base to start; tune or replace it).
  2. docker compose up -d --wait
  3. docker compose exec api corelata doctor
Then open http://<host>:8080. The operator guide (operator-guide.md) has the details.
To apply a later change to config/ or .env:
  docker compose up -d --wait --force-recreate migrate api worker
EOF
```

- [ ] **Step 2: Write `deploy/backup.sh` and `deploy/restore.sh`**

Copy `~/Downloads/coglossa/deploy/backup.sh` and `~/Downloads/coglossa/deploy/restore.sh` verbatim with these replacements and nothing else: `Coglossa` → `Corelata`; `coglossa-db-` → `corelata-db-`; `coglossa-files-` → `corelata-files-`; `pg_dump -U coglossa -d coglossa` → `pg_dump -U corelata -d corelata`; `psql ... -U coglossa -d coglossa` → `-U corelata -d corelata`; the confirmation prompt text "This replaces all Coglossa data" → "This replaces all Corelata data". Keep the `restore` typed confirmation, the `--yes` flag, the single-transaction `DROP SCHEMA public CASCADE` restore, the `rc 3/4` file-restore messages and the EXIT-trap restart.

- [ ] **Step 3: Write the stub-docker tests**

Copy `~/Downloads/coglossa/deploy/tests/test-install.sh` and `~/Downloads/coglossa/deploy/tests/test-restore.sh` and adapt:

`test-install.sh`:
- Rename every `coglossa`/`COGLOSSA` to `corelata`/`CORELATA`; the fake bundle it builds must contain `VERSION`, `SHA256SUMS`, `images/app.tar`, `images/postgres.tar` (dummy bytes), `config/corelata.example.yaml`, `config/corelata.demo.yaml`, `config/packs.example/icd203-base/pack.yaml` (one line), `compose.yaml`, `compose.demo.yaml`, `operator-guide.md`, `manifest.json`, plus the three scripts.
- Remove the `--gpu` cases, the `manifest "build": "cpu"` case and the `tiers` file assertions.
- Add: after a fresh install `config/packs/icd203-base/pack.yaml` exists; on a second run after editing `config/packs/icd203-base/pack.yaml` (append a line) and `config/corelata.yaml`, both edits survive and `.env` is byte-identical.
- Keep: the password regex `^CORELATA_DB_PASSWORD=[0-9a-f]{48}$` and `.env` mode 600; damaged / incomplete / no-`SHA256SUMS` bundles refused before any `docker load` and before `.env` exists (the stub `docker` logs its calls to a file; assert no `load` line); Compose `2.20.3` rejected, `v5.1.3` accepted; the interrupted-install completion; `umask 077` behaviour; `--help` prints the usage lines; an unknown option exits 2.

`test-restore.sh`: rename; the regexes for `corelata-db-*.dump` and `corelata-files-*.tar.gz` in the error messages; the stub `docker` must still see `compose stop api worker`, the single-transaction SQL (assert `DROP SCHEMA public CASCADE` and `pg_restore --no-owner` appear in one `exec` call), the files restore `run --rm --no-deps -T --entrypoint sh worker`, and the final `compose up -d --wait`; the rc-4 case ends with `compose up -d`.

Both scripts are self-contained bash (`set -euo pipefail`, a `PATH`-prepended stub `docker`, a temp dir removed by a trap, `pass`/`fail` counters, exit 1 on any failure). Make them executable.

- [ ] **Step 4: Makefile and CI**

Add to the `Makefile`:

```make
# Always the pinned shellcheck container, never a local binary or the runner's: a different
# shellcheck version has flagged what another accepts, so local runs and CI must agree.
SHELLCHECK := docker run --rm -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:v0.10.0

deploy-check:
	$(SHELLCHECK) deploy/*.sh deploy/tests/*.sh
	deploy/tests/test-install.sh
	deploy/tests/test-restore.sh
	python3 deploy/tests/check_compose.py
```

(`deploy-check` in `.PHONY`.) In `.github/workflows/ci.yml`, add:

```yaml
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make deploy-check
```

- [ ] **Step 5: Run it**

Run: `chmod +x deploy/*.sh deploy/tests/*.sh && make deploy-check`
Expected: shellcheck clean (fix every finding in the scripts rather than adding `# shellcheck disable` lines, unless the Coglossa original carries the same directive), `test-install.sh` and `test-restore.sh` print their pass counts and exit 0, `check_compose: ok`.

- [ ] **Step 6: Commit**

```bash
git add deploy/install.sh deploy/backup.sh deploy/restore.sh deploy/tests/test-install.sh deploy/tests/test-restore.sh Makefile .github/workflows/ci.yml
git commit -m "build: install, backup and restore scripts with stub-docker tests; make deploy-check"
```

---

### Task 4: The offline bundle

**Files:**
- Create: `deploy/bundle.sh`, `deploy/tests/check-bundle.sh`
- Modify: `Makefile` (`bundle`)

**Interfaces:**
- Consumes: the image build (Task 1), `check-app-image.sh`, the compose files and configs (Task 2), the scripts (Task 3), `docs/operator-guide.md` (Task 5 — until then the bundle copies a placeholder? No: Task 5 lands before `make bundle` is run in CI; locally, run Task 4's check after Task 5, or create `docs/operator-guide.md` with the Task 5 content first if you work in order — see Step 4), `engine/corelata/standards/packs/icd203-base/`, `docs/examples/`, `engine/corelata/__init__.py` (`__version__`).
- Produces: `deploy/bundle.sh [--version V] [--out DIR] [--allow-dirty] [--keep-stage]` → `dist/corelata-<v>-linux-amd64.tar` + `.sha256`; `deploy/tests/check-bundle.sh TAR`; `make bundle`.

- [ ] **Step 1: Write `deploy/bundle.sh`**

Start from `~/Downloads/coglossa/deploy/bundle.sh` (quoted in full in the Coglossa map) and produce the Corelata version: drop `--weights/--no-weights/--scorer/--flores`, `CUDA_INDEX`, the scorer image build/save/check, `models/`, `bench/`, `tiers.example.yaml`, `bench.example.yaml`, `compose.gpu.yaml`, the `weights`/`bench` manifest fields and the `scorer` SBOM; keep `--version`, `--out`, `--allow-dirty`, `--keep-stage`. The resulting script:

```bash
#!/usr/bin/env bash
# Build the offline bundle (spec §12) on a machine with Docker and internet access.
#   deploy/bundle.sh                      -> dist/corelata-<version>-linux-amd64.tar (+ .sha256)
# Options: --version V (default: the tag at HEAD, else <corelata version>-g<sha>), --out DIR
# (default: dist), --allow-dirty, --keep-stage (keep the unpacked directory next to the tarball).
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
die() { echo "error: $*" >&2; exit 1; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

PLATFORM=${PLATFORM:-linux/amd64}
POSTGRES_IMAGE=postgres:16-alpine
SYFT_IMAGE=anchore/syft:v1.18.1

version="" out="$repo/dist" allow_dirty=false keep=false
while [ $# -gt 0 ]; do
  case $1 in
    --version) version=${2:?--version needs a value}; shift ;;
    --out) out=${2:?--out needs a directory}; shift ;;
    --allow-dirty) allow_dirty=true ;;
    --keep-stage) keep=true ;;
    *) die "unknown option $1 (see the comment at the top of deploy/bundle.sh)" ;;
  esac
  shift
done
if ! $allow_dirty && [ -n "$(git -C "$repo" status --porcelain)" ]; then
  die "the working tree has uncommitted changes; commit them or pass --allow-dirty"
fi
if [ -z "$version" ]; then
  if tag=$(git -C "$repo" describe --tags --exact-match 2>/dev/null); then
    version=${tag#v}
  else
    base=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$repo/engine/corelata/__init__.py")
    version="$base-g$(git -C "$repo" rev-parse --short HEAD)"
  fi
fi

name="corelata-$version"
mkdir -p "$out"
out=$(cd "$out" && pwd)
stage="$out/$name"
rm -rf "$stage"
mkdir -p "$stage/images" "$stage/config" "$stage/sbom" "$stage/examples"
app="corelata/app:$version"

echo "== image ($PLATFORM)"
docker build --platform "$PLATFORM" -f "$repo/deploy/docker/app.Dockerfile" \
  --build-arg VERSION="$version" -t "$app" "$repo"
"$repo/deploy/tests/check-app-image.sh" "$app"
docker pull --platform "$PLATFORM" "$POSTGRES_IMAGE"
docker save -o "$stage/images/app.tar" "$app"
docker save -o "$stage/images/postgres.tar" "$POSTGRES_IMAGE"

echo "== files"
for f in compose.yaml compose.demo.yaml; do
  sed "s/\${CORELATA_VERSION:-dev}/$version/g" "$repo/deploy/$f" >"$stage/$f"
done
cp "$repo/deploy/config/corelata.example.yaml" "$repo/deploy/config/corelata.demo.yaml" "$stage/config/"
# install.sh copies it to config/packs once: the operator's edited packs are not in SHA256SUMS
mkdir -p "$stage/config/packs.example"
cp -R "$repo/engine/corelata/standards/packs/icd203-base" "$stage/config/packs.example/"
find "$stage/config/packs.example" -name '__pycache__' -prune -exec rm -rf {} +
cp "$repo/docs/examples/"* "$stage/examples/"
cp "$repo/deploy/install.sh" "$repo/deploy/backup.sh" "$repo/deploy/restore.sh" "$stage/"
chmod 755 "$stage"/*.sh
cp "$repo/docs/operator-guide.md" "$stage/operator-guide.md"
echo "$version" >"$stage/VERSION"
chmod -R a+rX "$stage/config" "$stage/examples" # the containers run as uid 10001

echo "== SBOMs (CycloneDX)"
# syft runs as the caller (so the SBOMs are theirs) and unpacks every layer into /tmp, which is
# a disk-backed directory under --out, not a tmpfs (RAM).
scratch=$(mktemp -d "$out/.syft-tmp.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
syft=(docker run --rm --user "$(id -u):$(id -g)" -v "$scratch:/tmp" -e HOME=/tmp -e XDG_CACHE_HOME=/tmp
  -v "$stage/sbom:/sbom")
# sbom NAME SOURCE MOUNT [SYFT-ARG...]: no -q, which would hide syft's errors; an empty file is an error too
sbom() {
  local name=$1 source=$2 mount=$3
  shift 3
  if ! "${syft[@]}" -v "$mount" "$SYFT_IMAGE" "$source" "$@" -o "cyclonedx-json=/sbom/$name.cdx.json"; then
    die "the SBOM for $name failed; see the message above"
  fi
  if [ ! -s "$stage/sbom/$name.cdx.json" ]; then
    die "the SBOM for $name is empty; see the message above"
  fi
}
for image in app postgres; do
  sbom "$image" "docker-archive:/images/$image.tar" "$stage/images:/images:ro"
done
sbom web dir:/src "$repo/web:/src:ro" --exclude './node_modules/**'

echo "== manifest and checksums"
python3 - "$stage" "$version" "$(git -C "$repo" rev-parse HEAD)" "$PLATFORM" "$app" "$POSTGRES_IMAGE" <<'PY'
import datetime, json, subprocess, sys
from pathlib import Path
stage, version, commit, platform, *images = sys.argv[1:]
def inspect(image):
    out = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)[0]
    return {"id": info["Id"], "repo_digests": info.get("RepoDigests") or []}
files = ["images/app.tar", "images/postgres.tar"]
manifest = {
    "version": version, "commit": commit, "platform": platform,
    "built_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "images": [{"file": f, "tag": i, **inspect(i)} for f, i in zip(files, images)],
    "packs": sorted(p.name for p in Path(stage, "config", "packs.example").iterdir() if p.is_dir()),
}
Path(stage, "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
(cd "$stage" && find . -type f -print0 | sort -z | xargs -0 bash -c \
  'if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi' _ >"$out/SHA256SUMS.$$")
mv "$out/SHA256SUMS.$$" "$stage/SHA256SUMS"

echo "== tarball"
tarball="$name-linux-amd64.tar"
# Every member is owned by root (uid and gid 0, no names): `sudo tar -xf` keeps the archive's
# owners, and the builder's uid may be some other account on the target host.
if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  owner=(--owner=0 --group=0 --numeric-owner)
else # bsdtar (macOS)
  owner=(--uid 0 --gid 0 --numeric-owner)
fi
(cd "$out" && COPYFILE_DISABLE=1 tar "${owner[@]}" -cf "$tarball" "$name" && sha256 "$tarball" >"$tarball.sha256")
$keep || rm -rf "$stage"
echo "Built $out/$tarball ($(du -h "$out/$tarball" | cut -f1))"
```

- [ ] **Step 2: Write `deploy/tests/check-bundle.sh`**

Start from `~/Downloads/coglossa/deploy/tests/check-bundle.sh` and adapt: rename; the single `corelata-*` directory whose name equals `VERSION`; `.sha256` matches the tar; `SHA256SUMS` verifies; scripts executable; required non-empty files: `compose.yaml`, `compose.demo.yaml`, `config/corelata.example.yaml`, `config/corelata.demo.yaml`, `config/packs.example/icd203-base/pack.yaml`, `examples/varna-port.txt`, `operator-guide.md`, `manifest.json`, `images/app.tar`, `images/postgres.tar`, `sbom/app.cdx.json`, `sbom/postgres.cdx.json`, `sbom/web.cdx.json`; operator-edited artefacts absent (`config/corelata.yaml`, `config/packs/`, `.env`); `compose.yaml` references `corelata/app:$version` and contains no `CORELATA_VERSION` text; no macOS metadata (`._*`, `.DS_Store`); `config/` and `examples/` world-readable; the example config identical to `deploy/config/corelata.example.yaml` and the pack identical to `engine/corelata/standards/packs/icd203-base` (`diff -r`); the Python block checks tar ownership is uid/gid 0, `manifest.version`, `manifest.platform`, `manifest.packs == ["icd203-base"]`, each image tar's internal `manifest.json` carries the expected tag, each SBOM has `bomFormat == "CycloneDX"`; finally `CORELATA_DB_PASSWORD=check docker compose --env-file /dev/null -f compose.yaml config -q` resolves. Executable; `set -euo pipefail`; temp dir removed by a trap.

- [ ] **Step 3: Makefile**

```make
bundle:
	deploy/bundle.sh
	deploy/tests/check-bundle.sh dist/$$(ls -t dist | grep -m1 'linux-amd64.tar$$')
```

(`bundle` in `.PHONY`.)

- [ ] **Step 4: Build and check a bundle**

If `docs/operator-guide.md` does not exist yet (Task 5), create it from Task 5's brief before this step, or run this step after Task 5 — the bundle copies it. Run: `deploy/bundle.sh --allow-dirty --out /tmp/corelata-dist --keep-stage` then `deploy/tests/check-bundle.sh /tmp/corelata-dist/corelata-*-linux-amd64.tar`. Expected: the image builds (cached from Task 1), syft produces three SBOMs, `check-bundle.sh` prints `ok`. Also run `make deploy-check` (shellcheck covers the two new scripts). Remove `/tmp/corelata-dist` afterwards.

- [ ] **Step 5: Commit**

```bash
git add deploy/bundle.sh deploy/tests/check-bundle.sh Makefile
git commit -m "build: the offline bundle with SBOMs, manifest and checksums"
```

---

### Task 5: The operator guide

**Files:**
- Create: `docs/operator-guide.md`

**Interfaces:**
- Consumes: everything an operator touches (Tasks 1–4; `corelata doctor`, `corelata run`, the config keys of `deploy/config/corelata.example.yaml`, the follow-ups' operations notes).
- Produces: the guide the bundle ships as `operator-guide.md` (Task 4 copies it); the README links to it.

Read `~/Downloads/coglossa/docs/operator-guide.md` once for structure and tone, then write Corelata's guide (plain Markdown, about 350–450 lines, 100-column wrap, no scorer/GPU/tiers/bench content) with exactly these sections and contents:

1. **What Corelata is** — two paragraphs (sources + analyst's value statement → an ICD 203-shaped assessment with a full trace; runs unattended behind a job queue; air-gapped, your own OpenAI-compatible model servers). **The bundle** — a tree of the extracted directory (`images/`, `config/corelata.example.yaml`, `config/corelata.demo.yaml`, `config/packs.example/icd203-base/`, `examples/`, `compose.yaml`, `compose.demo.yaml`, `install.sh`, `backup.sh`, `restore.sh`, `operator-guide.md`, `sbom/`, `manifest.json`, `VERSION`, `SHA256SUMS`) with one line each.
2. **Requirements** — Linux x86_64; Docker Engine 24+ with the Compose plugin 2.24+; bash, coreutils, tar; about 2 GB disk for the images plus your data; a model server reachable from the host (vLLM, Ollama, TGI, llama.cpp server, LM Studio) exposing an OpenAI-compatible `/v1` API; no internet access needed.
3. **Install** — numbered: `sha256sum -c corelata-<version>-linux-amd64.tar.sha256`; `tar -xf …`; `cd corelata-<version>`; `./install.sh` (what it creates: `config/corelata.yaml`, `config/packs/`, `.env`; never overwrites; `chmod -R a+rX config` explained by uid 10001); edit `config/corelata.yaml` (backends, models, roles); `docker compose up -d --wait`; `docker compose exec api corelata doctor`; open `http://<host>:8080`.
4. **Try it first** — the demo: `docker compose -f compose.yaml -f compose.demo.yaml up -d --wait` (its own project `corelata-demo`, synthetic model, placeholder reports); run a report from the shell: `docker compose -f compose.yaml -f compose.demo.yaml exec worker corelata run /opt/corelata/examples/varna-port.txt --project demo --statement "Varna port capacity expansion matters to shippers"` then open the UI; `docker compose -f compose.yaml -f compose.demo.yaml down -v` to remove it.
5. **Configuration** — one subsection per concern: *Model servers* (`backends`: `base_url`, `host.docker.internal` for a server on this host, `api_key_env` naming a variable you add to `.env`, `max_concurrency`, `timeout_s`); *Models and roles* (`models`: `name`, `context_window`, `structured_output` `json_schema|json_object|none`, `max_output_tokens`, `temperature`; `roles` gate/writer/conveyor/auditor; a different model family for the auditor when you have one); *Standards packs* (`config/packs/` is yours: `config/packs/icd203-base/` = rules `rules/<id>.yaml` with `severity`, `checkability`, `route_to`, `template.yaml`, `lexicon.yaml`, `profiles/<team>.yaml` overlays with `extends`, `draft: true` while under review, `format.docx_reference` for a team's Word template placed next to the profile; `standards.default_pack`/`default_profile`; `docker compose exec api corelata pack validate /etc/corelata/packs/icd203-base` to check edits; profiles with `draft: true` cannot be used in a run); *Pipeline* (`max_iterations`, the digest and budget tokens — when to raise them); *Uploads and the API* (`api.max_upload_mb`, `api.progress_poll_s`, `auth`); *Coglossa* (`integrations.coglossa` when the sibling product is deployed; what the fetch does); *Applying changes* (`docker compose up -d --wait --force-recreate migrate api worker`; the worker finishes its current stage first, up to 5 minutes; an invalid config stops `migrate` and keeps `api`/`worker` down: `docker compose logs migrate`).
6. **Users, access and the reverse proxy** — `auth: { mode: trusted_header, header: X-Remote-User }` with `CORELATA_HTTP_BIND=127.0.0.1` in `.env`; an nginx `location /` example with `proxy_set_header X-Remote-User $remote_user;`, `client_max_body_size 200m;`, and `proxy_buffering off;` for `/api/runs/` (server-sent events); the warning that with `mode: none` anyone who reaches the port can use Corelata; the API port must be reachable only from the proxy.
7. **Running it** — `docker compose ps`, `docker compose logs -f worker`, what each service does (`postgres`, `migrate` one-shot, `worker` executes runs and discoveries, `api` serves the web app); the CLI inside the containers (`docker compose exec api corelata status <run-id>`, `cancel`, `review --return --note`, `export --out`, `doctor`); where data lives (`pgdata` and `files` volumes belong to the project `corelata`, not the directory); the periodic stalled-job requeue and that closed job copies accumulate in `procrastinate_jobs` (a `DELETE FROM procrastinate_jobs WHERE status IN ('succeeded','failed','cancelled') AND scheduled_at < now() - interval '30 days'` housekeeping example via `docker compose exec postgres psql -U corelata -d corelata -c "…"`).
8. **Backups** — `./backup.sh [DIR]` while running; the two files `corelata-db-<stamp>.dump` and `corelata-files-<stamp>.tar.gz`; a cron example (02:00, keep 14 days); **What a backup does not hold**: `config/corelata.yaml`, `config/packs/`, `.env` — keep them beside the backups.
9. **Restore** — `./restore.sh DB_DUMP FILES_ARCHIVE` (order; `--yes`; it replaces all data in one transaction and restarts the stack); **On a new host**: unpack the same or a newer bundle, `./install.sh`, copy `config/` and `.env`, `docker compose up -d --wait`, `./restore.sh --yes …`, `docker compose exec api corelata doctor`; a lost `.env` is fine (the dump holds no roles or passwords).
10. **Upgrades** — `./backup.sh`; extract the new bundle beside the old; copy `config/corelata.yaml`, `config/packs/` and `.env`; `docker compose down` in the old directory; in the new: `./install.sh`, `docker compose up -d --wait`, `docker compose exec api corelata doctor`; `migrate` upgrades the schema before `api`/`worker` start; going back = `down` in the new directory then `./restore.sh` from the old directory with the pre-upgrade backup (migrations only go forward); new rules in a newer base pack: compare `config/packs.example/icd203-base` with your `config/packs/icd203-base` (`diff -r`) and merge by hand.
11. **Troubleshooting** — a table: `migrate` did not complete → `docker compose logs migrate`, fix the config; doctor fails on a backend → URL/model id/`api_key_env`; "run ./install.sh first" → `.env` missing (copy the old one on upgrade); port 8080 taken → `CORELATA_HTTP_PORT` in `.env`; permission errors on `config/` → `chmod -R a+rX config`; damaged bundle → `sha256sum -c`; a run stays `created` → the worker is down (`docker compose ps worker`); a run ended `failed` with "no queued job" → the worker's sweep after a queue outage, start it again; a profile refused as draft → remove `draft: true`; the web app shows "could not be reached" → `docker compose ps api`, `logs api`.
12. **Uninstall** — `docker compose down -v` (deletes all data), `docker image rm corelata/app:<version> postgres:16-alpine`, remove the directory.
13. **What is inside** — the image contents (API + web, worker, CLI, fake model server), the SBOMs (`sbom/*.cdx.json`, CycloneDX), `manifest.json` (version, commit, platform, images, packs), where the version shows (`VERSION`, the image label; `/api/health` and the web footer show the package version).

Verify every command against the code (`corelata pack validate` takes a directory or name: `engine/corelata/cli.py`; `corelata run ... --project --statement`: `cli.py`/`cli_ops.py`; the SQL uses `procrastinate_jobs.status` values `succeeded|failed|cancelled` and `scheduled_at` — check the vendored SQL for the column names). Commit:

```bash
git add docs/operator-guide.md
git commit -m "docs: the operator guide"
```

---

### Task 6: The air-gap test

**Files:**
- Create: `deploy/tests/smoke.py`, `deploy/tests/compose.airgap.yaml`, `deploy/tests/airgap-test.sh`
- Modify: `Makefile` (`airgap-test`), `.github/workflows/ci.yml` (`airgap` job)

**Interfaces:**
- Consumes: the bundle (Task 4), `install.sh`/`backup.sh`/`restore.sh` (Task 3), the demo overlay (Task 2), the API routes (`/api/health`, `/api/system/doctor`, `/api/projects`, `/api/projects/{id}/sources`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/report?format=`, `/api/runs/{id}/exports/trace.json`, `/api/packs/icd203-base/resolved`).
- Produces: `python3 smoke.py BASE_URL run NAME | check NAME` (standard library only, run inside the stack), the sealed-network overlay, `deploy/tests/airgap-test.sh`, `make airgap-test`, CI `airgap` job.

- [ ] **Step 1: Write `deploy/tests/compose.airgap.yaml`**

```yaml
# The air-gap install test (spec §12): the stack on a network with no route out, reading the
# operator's config/corelata.yaml (the demo overlay only adds the synthetic model server).
networks:
  default:
    internal: true

x-operator-config: &operator-config
  CORELATA_CONFIG: /etc/corelata/corelata.yaml

services:
  migrate:
    environment: *operator-config
  worker:
    environment: *operator-config
  api:
    environment: *operator-config
    ports: !reset []
```

- [ ] **Step 2: Write `deploy/tests/smoke.py`**

```python
"""The analyst's path through a running Corelata, from inside the stack (standard library only):
    python3 smoke.py BASE_URL run NAME     create project NAME, upload the example source, run a
                                           report, wait for it, download every export
    python3 smoke.py BASE_URL check NAME   the project and its completed run still exist and the
                                           exports still download; then a new run completes
Exit 0 on success; any failure raises with the step in the message."""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

STATEMENT = "Varna port capacity expansion matters to shippers"
SOURCE = "/opt/corelata/examples/varna-port.txt"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TERMINAL = {"completed", "gate_rejected", "failed", "cancelled"}


def call(base, method, path, body=None, headers=None, timeout=60):
    data = None
    hdrs = dict(headers or {})
    if body is not None and not isinstance(body, bytes):
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    elif body is not None:
        data = body
    req = urllib.request.Request(base + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def expect(ok, what):
    if not ok:
        raise SystemExit(f"smoke: {what}")


def json_of(status, body, path, want=200):
    expect(status == want, f"{path} answered {status}: {body[:300]!r}")
    return json.loads(body)


def multipart(fields, filename, content):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    out += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    out += b"Content-Type: text/plain\r\n\r\n" + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def wait_terminal(base, run_id, timeout_s=300):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        progress = json_of(*call(base, "GET", f"/api/runs/{run_id}")[0::2], f"/api/runs/{run_id}")
        if progress["state"] in TERMINAL:
            return progress
        time.sleep(1)
    raise SystemExit(f"smoke: run {run_id} did not finish within {timeout_s} s")


def check_exports(base, run_id):
    for fmt, prefix, ctype in (
        ("docx", b"PK", DOCX),
        ("html", b"<!DOCTYPE html", "text/html"),
        ("md", b"", "text/markdown"),
        ("json", b"{", "application/json"),
    ):
        status, headers, body = call(base, "GET", f"/api/runs/{run_id}/report?format={fmt}")
        expect(status == 200, f"report {fmt} answered {status}")
        expect(headers.get("Content-Type", "").startswith(ctype), f"report {fmt} content-type {headers.get('Content-Type')}")
        expect(body.startswith(prefix) and len(body) > 100, f"report {fmt} looks wrong: {body[:40]!r}")
    status, _, body = call(base, "GET", f"/api/runs/{run_id}/exports/trace.json")
    trace = json_of(status, body, "trace.json")
    expect(trace["run_id"] == run_id and trace["state"] == "completed", "trace.json is not this run's completed trace")


def completed_run(base, project_id):
    runs = json_of(*call(base, "GET", f"/api/runs?project_id={project_id}")[0::2], "/api/runs")
    done = [r for r in runs if r["state"] == "completed"]
    expect(done, f"project {project_id} has no completed run")
    return done[0]["run_id"]


def project_named(base, name):
    projects = json_of(*call(base, "GET", "/api/projects")[0::2], "/api/projects")
    found = [p for p in projects if p["name"] == name]
    expect(found, f"no project named {name!r}")
    return found[0]["id"]


def start_run(base, project_id, source_id):
    body = {"project_id": project_id, "source_ids": [source_id], "value_statement": STATEMENT, "max_iterations": 1, "extra_guidance": ""}
    run = json_of(*call(base, "POST", "/api/runs", body)[0::2], "/api/runs", want=202)
    progress = wait_terminal(base, run["run_id"])
    expect(progress["state"] == "completed", f"run ended {progress['state']}: {progress.get('error')}")
    return run["run_id"]


def run(base, name):
    status, _, body = call(base, "GET", "/")
    expect(status == 200 and b'<div id="root">' in body, "the web app is not served at /")
    doctor = json_of(*call(base, "GET", "/api/system/doctor")[0::2], "/api/system/doctor")
    expect(doctor["ok"], "doctor: " + "; ".join(f"{c['name']}: {c['message']}" for c in doctor["checks"] if c["status"] != "pass"))
    project = json_of(*call(base, "POST", "/api/projects", {"name": name})[0::2], "/api/projects", want=201)
    with open(SOURCE, "rb") as f:
        content = f.read()
    data, headers = multipart({"kind": "file"}, "varna-port.txt", content)
    sources = json_of(*call(base, "POST", f"/api/projects/{project['id']}/sources", data, headers)[0::2], "sources", want=201)
    run_id = start_run(base, project["id"], sources[0]["id"])
    check_exports(base, run_id)
    print(f"smoke run: project {project['id']} run {run_id} completed; exports ok")


def check(base, name):
    project_id = project_named(base, name)
    check_exports(base, completed_run(base, project_id))
    sources = json_of(*call(base, "GET", f"/api/projects/{project_id}/sources")[0::2], "sources")
    expect(sources, "the project's sources are gone")
    run_id = start_run(base, project_id, sources[0]["id"])
    check_exports(base, run_id)
    print(f"smoke check: project {project_id} kept its data; new run {run_id} completed")


if __name__ == "__main__":
    base_url, mode, project_name = sys.argv[1:4]
    {"run": run, "check": check}[mode](base_url.rstrip("/"), project_name)
```

`call(...)[0::2]` picks `(status, body)` from the `(status, headers, body)` tuple for `json_of`. The source file path is the image's `/opt/corelata/examples/varna-port.txt`, so the script must run inside an app container (`docker compose exec -T worker python3 - http://api:8080 run NAME <smoke.py`).

- [ ] **Step 3: Write `deploy/tests/airgap-test.sh`**

Start from `~/Downloads/coglossa/deploy/tests/airgap-test.sh` for the structure (trap, logging helpers, two sites); this is Corelata's:

```bash
#!/usr/bin/env bash
# The air-gap test (spec §12, §14 M5): build the bundle, install it on a network with no route
# out, run a full report against the fake model, change the config and a pack, back up, upgrade
# to a second site, restore over a newer schema. Needs Docker, about 5 GB of disk, ~15 minutes.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
tests=$repo/deploy/tests
die() { echo "airgap: error: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

tmp=$(mktemp -d /tmp/corelata-airgap.XXXXXX)
sha=$(git -C "$repo" rev-parse --short HEAD)
version="airgap-$sha"
export COMPOSE_PROJECT_NAME=corelata-airgaptest
site1="" site2=""
cleanup() {
  set +e
  for site in "$site1" "$site2"; do
    [ -n "$site" ] && [ -d "$site" ] && (cd "$site" && docker compose down -v --remove-orphans >/dev/null 2>&1)
  done
  docker image rm -f "corelata/app:$version" >/dev/null 2>&1
  rm -rf "$tmp"
}
trap cleanup EXIT

compose() { docker compose "$@"; }
api_py() { compose exec -T api python3 -c "$1"; }
sql() { compose exec -T postgres psql -X -q -t -A -U corelata -d corelata -c "$1"; }
smoke() { compose exec -T worker python3 - "http://api:8080" "$@" <"$tests/smoke.py"; }

step "1. build the bundle"
"$repo/deploy/bundle.sh" --version "$version" --out "$tmp/dist" --allow-dirty
tar=$tmp/dist/corelata-$version-linux-amd64.tar
"$tests/check-bundle.sh" "$tar"

step "2. a damaged bundle is refused"
mkdir "$tmp/damaged" && tar -C "$tmp/damaged" -xf "$tar"
echo "# tampered" >>"$tmp/damaged/corelata-$version/config/corelata.example.yaml"
if (cd "$tmp/damaged/corelata-$version" && ./install.sh >"$tmp/damaged.log" 2>&1); then
  die "install.sh accepted a damaged bundle"
fi
grep -q "damaged or incomplete" "$tmp/damaged.log" || die "the damaged-bundle message is missing: $(cat "$tmp/damaged.log")"
grep -q "corelata.example.yaml" "$tmp/damaged.log" || die "the damaged file is not named"
[ ! -f "$tmp/damaged/corelata-$version/.env" ] || die "install.sh created .env for a damaged bundle"

step "3. the images come from the bundle only"
docker image rm -f "corelata/app:$version" >/dev/null 2>&1 || true

step "4. install site 1 and start it on a sealed network"
mkdir "$tmp/site1" && tar -C "$tmp/site1" -xf "$tar"
site1=$tmp/site1/corelata-$version
cd "$site1"
./install.sh
cp config/corelata.demo.yaml config/corelata.yaml # the operator's config: the synthetic model
export COMPOSE_FILE="compose.yaml:compose.demo.yaml:$tests/compose.airgap.yaml"
compose up -d --wait

step "5. no route out"
if api_py "import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)" 2>/dev/null; then
  die "the api container reached the internet; the network is not sealed"
fi

step "6. doctor and a full report"
compose exec -T api corelata doctor
smoke run airgap

step "7. a pack edit and a config change take effect"
rule=config/packs/icd203-base/rules/icd203.tc.8.yaml
grep -q '^title:' "$rule" || die "$rule has no title line"
sed -i.bak 's/^title: .*/title: "Sourcing is clear (edited on site)"/' "$rule" && rm "$rule.bak"
worker_before=$(compose ps -q worker)
compose up -d --wait --force-recreate migrate api worker
[ "$(compose ps -q worker)" != "$worker_before" ] || die "the worker was not recreated"
api_py "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/packs/icd203-base/resolved')); assert any(x['title']=='Sourcing is clear (edited on site)' for x in r['rules']), 'edited rule not served'"
smoke check airgap

step "8. an invalid config stops migrate and keeps api and worker down"
cp config/corelata.yaml "$tmp/good.yaml"
echo "nonsense: 1" >>config/corelata.yaml
if compose up -d --wait --force-recreate migrate api worker >"$tmp/bad.log" 2>&1; then
  die "the stack started with an invalid config"
fi
compose logs migrate | grep -qi "nonsense" || die "migrate's log does not name the bad key: $(compose logs migrate | tail -5)"
cp "$tmp/good.yaml" config/corelata.yaml
compose up -d --wait --force-recreate migrate api worker
smoke check airgap

step "9. back up"
./backup.sh "$tmp/backups"
db=$(ls "$tmp/backups"/corelata-db-*.dump)
files=$(ls "$tmp/backups"/corelata-files-*.tar.gz)

step "10. upgrade: the same bundle installed as a second site keeps the data and the pack edit"
compose down
mkdir "$tmp/site2" && tar -C "$tmp/site2" -xf "$tar"
site2=$tmp/site2/corelata-$version
cp "$site1/config/corelata.yaml" "$site2/config/"
cp -R "$site1/config/packs" "$site2/config/packs"
cp "$site1/.env" "$site2/.env"
cd "$site2"
./install.sh
grep -q 'Sourcing is clear (edited on site)' config/packs/icd203-base/rules/icd203.tc.8.yaml || die "install.sh overwrote the operator's pack"
compose up -d --wait
api_py "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/packs/icd203-base/resolved')); assert any(x['title']=='Sourcing is clear (edited on site)' for x in r['rules']), 'edited rule lost on upgrade'"
smoke check airgap

step "11. restore over a newer schema"
compose down -v
compose up -d --wait
if smoke check airgap >/dev/null 2>&1; then die "the data survived down -v; the restore test proves nothing"; fi
sql "CREATE TABLE newer_feature (id int); UPDATE alembic_version SET version_num = '9999_newer';"
./restore.sh --yes "$db" "$files"
[ "$(sql "SELECT count(*) FROM information_schema.tables WHERE table_name = 'newer_feature'")" = 0 ] || die "the newer table survived the restore"
[ "$(sql "SELECT version_num FROM alembic_version")" != "9999_newer" ] || die "alembic_version was not restored"
smoke check airgap

echo
echo "airgap: ok ($version)"
```

The `sed -i.bak` form works with both GNU and BSD sed. Step 8 relies on `load_config` rejecting unknown keys (strict pydantic `extra=forbid`): the engine's message names the key (`nonsense`). If the `compose up --wait` for the bad config hangs instead of failing (Compose waits for `migrate` to complete; a failed one-shot makes `up --wait` return non-zero), add `--wait-timeout 120`.

- [ ] **Step 4: Makefile and CI**

```make
airgap-test:
	deploy/tests/airgap-test.sh
```

(`airgap-test` in `.PHONY`.) In `.github/workflows/ci.yml`:

```yaml
  airgap:
    runs-on: ubuntu-latest
    timeout-minutes: 45 # the image build, then three full stack starts and a restore
    steps:
      - uses: actions/checkout@v4
      - name: free disk space for the image and the bundle
        run: |
          sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL
          df -h /
      - run: make airgap-test
```

- [ ] **Step 5: Run it locally**

Run: `chmod +x deploy/tests/airgap-test.sh && make deploy-check && make airgap-test`
Expected: `deploy-check` green (shellcheck covers the new script); the air-gap test prints every step and ends with `airgap: ok (airgap-<sha>)` in about 10–15 minutes (the fake model answers in milliseconds; the time is image build, saves/loads and stack starts). On failure, the trap tears both sites down; re-run after fixing. Record the wall-clock time in the report.

- [ ] **Step 6: Commit**

```bash
git add deploy/tests/smoke.py deploy/tests/compose.airgap.yaml deploy/tests/airgap-test.sh Makefile .github/workflows/ci.yml
git commit -m "test: the air-gap install, run, upgrade and restore test"
```

---

### Task 7: Documentation, follow-ups and spec amendments

**Files:**
- Create: `docs/m5-followups.md`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§12), `docs/m3-followups.md`, `docs/m4a-followups.md`, `docs/m4b-followups.md` ("Later" closures)

- [ ] **Step 1: README**

Add after the M4b section:

```markdown
## M5: deploy it

One image, one Compose stack, one offline bundle (spec §12). On a build machine with Docker and
internet access:

    make image-app                       # build corelata/app:dev and check its contract
    make demo                            # the stack with the synthetic model on http://127.0.0.1:8080
    make demo-down
    make bundle                          # dist/corelata-<version>-linux-amd64.tar (+ .sha256), with SBOMs
    make deploy-check                    # shellcheck, install/restore tests, compose check (no images needed)
    make airgap-test                     # install the bundle on a sealed network, run a report, back up, upgrade, restore

On the customer's host: verify the checksum, extract, `./install.sh`, edit `config/corelata.yaml`
(and `config/packs/` for the standards), `docker compose up -d --wait`,
`docker compose exec api corelata doctor`. `docs/operator-guide.md` (shipped in the bundle as
`operator-guide.md`) has the whole procedure, backups, restore, upgrades and troubleshooting.
```

- [ ] **Step 2: Spec amendment (§12)**

Append to §12:

```markdown
M5 amendments: the bundle carries the base pack as `config/packs.example/icd203-base/` and
`install.sh` copies it to `config/packs/` once, so the customer's pack directory is never in
`SHA256SUMS` and never overwritten (the operator merges a newer base pack by hand with
`diff -r`). The bundle also carries `examples/` (the sample source) and a `VERSION` file; the
version is the git tag at HEAD, else `<package version>-g<sha>`; `/api/health` and the web footer
show the package version, the image label, `VERSION` and `manifest.json` the bundle version. The
worker's `stop_grace_period` is 5 minutes. There is no GPU overlay and no scorer. The demo
overlay adds a `fake-openai` service and points `CORELATA_CONFIG` at `config/corelata.demo.yaml`.
The air-gap test also covers a pack edit surviving an upgrade and an invalid config stopping
`migrate`. Bundles are built with `make bundle` on a developer machine; no release workflow
publishes them. `install.sh` prints `docker compose up -d --wait` and `corelata doctor` as the
next steps instead of running them, so the operator edits `config/corelata.yaml` first (as in
Coglossa). No `.env.example` ships: `install.sh` creates `.env` with the generated database
password, and the guide documents the other variables (`CORELATA_HTTP_BIND`, `CORELATA_HTTP_PORT`,
model-server keys named by `api_key_env`).
```

- [ ] **Step 3: Follow-ups**

Create `docs/m5-followups.md`:

```markdown
# M5 follow-ups

## Divergences from Coglossa

- `deploy/` copied without the scorer (image, service, GPU overlay, weights, `--gpu`), the
  language tiers (`tiers.yaml`) and FLORES/bench; `install.sh` takes no options.
- The base pack ships as `config/packs.example/` and is copied to `config/packs/` once by
  `install.sh` (Coglossa has no customer-editable directory of this kind).
- The app image carries `/opt/corelata/examples/` (the sample source) for the demo and the
  smoke test; `.dockerignore` allows `docs/examples/`.
- `migrate` runs `corelata migrate` (Coglossa: `coglossa db upgrade`); `worker.stop_grace_period`
  is 5m (Coglossa: 2m) because a Corelata stage is a model call of minutes.
- `smoke.py` drives Corelata's flow (project, source upload, run, exports, trace) and its
  `check` mode also starts a new run after an upgrade or restore.
- `airgap-test.sh` adds a pack-edit-survives-upgrade step and an invalid-config step; it drops
  the tiers and bench steps.
- `check-app-image.sh` checks Corelata's package data (migrations, prompt templates, the
  report template, the base pack, the vendored Coglossa export schema).

## Spec deviations

- §12: recorded in the spec (`config/packs.example`, `examples/`, `VERSION`, version derivation,
  5m grace, no GPU overlay, no release workflow).

## Should fix soon

- `/api/health` and the web footer show `corelata.__version__` (0.1.0), not the bundle version;
  a `VERSION` build-arg read at runtime would align them (Coglossa has the same gap — **backport**).
- `restore.sh` drops the whole `public` schema; it assumes everything Corelata and procrastinate
  create lives there (true today). A future extension schema would need the script changed.
- `backup.sh` reads the files volume through a one-shot `worker` container; a very large volume
  is streamed through `docker compose run`, which is slow on some hosts.
- The air-gap test takes 10–15 minutes and about 5 GB; CI runs it on every push and PR.
- `bundle.sh` refuses a dirty tree without `--allow-dirty`; CI's airgap job passes
  `--allow-dirty` through `airgap-test.sh`.
- Closed procrastinate job copies accumulate; the guide gives a `DELETE` for housekeeping, nothing
  runs it automatically.
- The `postgres:16-alpine` image is pinned by tag, not digest.

## Later

- A release workflow that builds the bundle on a tag and publishes the tar, `.sha256` and
  manifest.
- Compose resource limits once a customer host profile is known.
- M6: `corelata bench` and `profile extract` need no packaging change (same image).
```

In `docs/m3-followups.md`, `docs/m4a-followups.md` and `docs/m4b-followups.md`, replace each "M5:" bullet under "Later" with `- M5: delivered (deploy/).` keeping any still-open note.

- [ ] **Step 4: Verify and commit**

Run: `make deploy-check` (unchanged scripts; confirms nothing regressed) and read the README block against the Makefile targets.

```bash
git add README.md docs/m5-followups.md docs/m3-followups.md docs/m4a-followups.md docs/m4b-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -m "docs: M5 README, follow-ups and spec amendments"
```

---

## Self-review

**Spec coverage (§12, §14 M5 row):** Compose services `postgres`, one-shot `migrate`, `worker`, `api` (Task 2); one app image with API, web build, worker, CLI, fake OpenAI server (Task 1); overlays `compose.demo.yaml` (Task 2) and `compose.dev.yaml` (existing); bundle `corelata-<ver>-linux-amd64.tar` + `.sha256` with `images/*.tar`, `config/` (example yaml, `.env` is created not shipped — spec says `.env.example`: the generated `.env` holds only the password `install.sh` creates, so no example is needed; recorded in Task 7's spec amendment), `packs/icd203-base` (as `config/packs.example/`), `install.sh`, `backup.sh`, `restore.sh`, `operator-guide.md`, `sbom/`, manifest, `SHA256SUMS` (Task 4); `install.sh` verifies checksums, loads images, creates config, pack directory and `.env` only if missing, and tells the operator to run `docker compose up -d --wait` and `corelata doctor` (Task 3 — the spec says `install.sh` "runs" them; Coglossa's prints them as next steps so an operator edits the config first; recorded in Task 7's spec amendment); upgrades never overwrite the pack directory (Tasks 3, 6); CI `make deploy-check` (shellcheck, install and restore tests, compose check) and `make airgap-test` (sealed network, full report against the fake model, back up, upgrade, restore) (Tasks 3, 6); exit test `make airgap-test` green (Task 6 + CI).

**Placeholder scan:** the copied scripts are given in full where they change (install, bundle, smoke, airgap, compose files, configs, `check_compose.py`, `check-app-image.sh`) and as exact edit lists where they do not (backup, restore, the two stub tests, `check-bundle.sh`), each naming the Coglossa source path; the guide task lists every section's required content and commands.

**Type consistency:** service names (`postgres`, `migrate`, `worker`, `api`, `fake-openai`) are the same in compose, `check_compose.py`, `backup.sh`/`restore.sh`, `smoke()`/`sql()`/`api_py()` in `airgap-test.sh`; the bundle layout in `bundle.sh`, `check-bundle.sh`, `install.sh` and the guide agree (`config/packs.example/` → `config/packs/`); env names `CORELATA_DB_PASSWORD`, `CORELATA_VERSION`, `CORELATA_HTTP_BIND/PORT`, `CORELATA_CONFIG` are the same everywhere; `smoke.py` uses the M4a routes as committed in `schema/openapi.json`.

**Review Focus:** each line names its tests; they are in Tasks 3 and 6 as listed.
