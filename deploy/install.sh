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
