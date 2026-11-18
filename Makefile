.PHONY: test test-engine test-api test-web e2e dev-stack lint fmt schema db-up db-down image-app demo demo-down deploy-check bundle airgap-test

CORELATA_VERSION ?= dev
# deploy/bundle.sh refuses any other platform: the bundle is linux/amd64 only
PLATFORM ?= linux/amd64

DB_URL ?= postgresql://corelata:corelata@127.0.0.1:55433/postgres
COMPOSE_DEV = docker compose -f deploy/compose.dev.yaml

test: test-engine test-api test-web

test-engine: db-up
	cd engine && CORELATA_TEST_DATABASE_URL=$${CORELATA_TEST_DATABASE_URL:-$(DB_URL)} uv run pytest

test-api: db-up
	cd api && CORELATA_TEST_DATABASE_URL=$${CORELATA_TEST_DATABASE_URL:-$(DB_URL)} uv run pytest

test-web:
	cd web && pnpm test

e2e: db-up
	cd web && pnpm build && CORELATA_TEST_DATABASE_URL=$${CORELATA_TEST_DATABASE_URL:-$(DB_URL)} pnpm e2e

dev-stack: db-up
	cd api && CORELATA_TEST_DATABASE_URL=$${CORELATA_TEST_DATABASE_URL:-$(DB_URL)} uv run python devstack.py --port 8080

db-up:
	$(COMPOSE_DEV) up -d --wait postgres

db-down:
	$(COMPOSE_DEV) down

lint:
	cd engine && uv run ruff check . && uv run ruff format --check .
	cd api && uv run ruff check . && uv run ruff format --check .
	cd web && pnpm lint

fmt:
	cd engine && uv run ruff format . && uv run ruff check --fix .
	cd api && uv run ruff format . && uv run ruff check --fix .
	cd web && pnpm fmt

schema:
	cd engine && uv run python -m corelata.schema.export ../schema
	cd api && uv run python -m corelata_api.openapi ../schema/openapi.json
	cd web && pnpm gen:api

# --provenance=false: buildx's attestation would make `docker save` a multi-manifest tar
image-app:
	docker build --provenance=false --platform $(PLATFORM) -f deploy/docker/app.Dockerfile \
	  --build-arg VERSION=$(CORELATA_VERSION) -t corelata/app:$(CORELATA_VERSION) .
	deploy/tests/check-app-image.sh corelata/app:$(CORELATA_VERSION)

COMPOSE_DEMO = cd deploy && CORELATA_DB_PASSWORD=$${CORELATA_DB_PASSWORD:-demo} \
  CORELATA_HTTP_BIND=127.0.0.1 docker compose -p corelata-demo -f compose.yaml -f compose.demo.yaml

demo: image-app
	$(COMPOSE_DEMO) up -d --wait
	@echo "Corelata with the demo model: http://127.0.0.1:$${CORELATA_HTTP_PORT:-8080}"

demo-down:
	$(COMPOSE_DEMO) down -v

# Always the pinned shellcheck container, never a local binary or the runner's: a different
# shellcheck version has flagged what another accepts, so local runs and CI must agree.
SHELLCHECK := docker run --rm -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:v0.10.0

deploy-check:
	$(SHELLCHECK) deploy/*.sh deploy/tests/*.sh deploy/hosted/vercel/*.sh
	deploy/tests/test-install.sh
	deploy/tests/test-restore.sh
	python3 deploy/tests/check_compose.py
	python3 deploy/tests/check_workflows.py

bundle:
	deploy/bundle.sh
	deploy/tests/check-bundle.sh dist/$$(ls -t dist | grep -m1 'linux-amd64.tar$$')

airgap-test:
	deploy/tests/airgap-test.sh
