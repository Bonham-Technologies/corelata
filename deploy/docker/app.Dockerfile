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
# The report stylesheet: the build hashes it into the review frame's policy (CRL-23).
COPY engine/corelata/render/templates/report.css /src/engine/corelata/render/templates/
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
    CORELATA_CONFIG=/etc/corelata/corelata.yaml CORELATA_BUILD_VERSION=${VERSION}
USER 10001:10001
WORKDIR /data
EXPOSE 8080
CMD ["corelata-api", "--host", "0.0.0.0", "--port", "8080", "--web-dir", "/opt/corelata/web"]
