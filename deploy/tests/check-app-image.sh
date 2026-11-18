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
label=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' "$image")
[ -n "$label" ] || die "the org.opencontainers.image.version label is empty"
run corelata --version | grep -qF "$label" || die "corelata --version does not carry the image version ($label)"
[ "$(run sh -c 'echo $CORELATA_BUILD_VERSION')" = "$label" ] || die "CORELATA_BUILD_VERSION must equal the image version label"
run corelata-api --help >/dev/null || die "corelata-api --help does not work"
# M19: the S3 client belongs to the hosted demo (the `s3` extra); the air-gapped image has none.
run python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("boto3") is not None)' \
  || die "boto3 is in the image: the app image must not install the s3 extra"
[ "$(run sh -c 'echo $CORELATA_CONFIG')" = /etc/corelata/corelata.yaml ] \
  || die "CORELATA_CONFIG must be /etc/corelata/corelata.yaml"
run test -f /opt/corelata/web/index.html || die "the web app is missing (/opt/corelata/web/index.html)"
run sh -c 'ls /opt/corelata/web/assets/*.js >/dev/null' || die "the web app's assets are missing"
# M18: the theme is set before the first paint by a file of its own (the page's policy allows no
# inline script), and the fonts are served from the image, never from the network.
run test -f /opt/corelata/web/theme-init.js || die "the web app's theme-init.js is missing"
run sh -c 'ls /opt/corelata/web/assets/noto-sans-latin-400-* >/dev/null 2>&1' \
  || die "the web app's fonts are missing (no noto-sans-latin-400 file under /opt/corelata/web/assets)"
run test -f /opt/corelata/examples/varna-port.txt || die "the example source is missing"
run sh -c 'touch /data/files/.probe && rm /data/files/.probe' || die "/data/files is not writable by the app user"
site=$(run python -c 'import corelata, pathlib; print(pathlib.Path(corelata.__file__).parent)')
for f in store/migrations/versions/0002_corelata_schema.py store/migrations/versions/0001_procrastinate_3_10_0.sql \
  prompts/templates/gate/v1.j2 render/templates/report.html.j2 render/templates/report.css \
  standards/packs/icd203-base/pack.yaml \
  ingest/vendor/coglossa-report-1.schema.json bench/scenarios/clean-single-source.yaml \
  bench/scenarios-real/corroborated-port-expansion.yaml; do
  run test -f "$site/$f" || die "package data is missing from the image: $f"
done
# The image's own command refuses to start without a config, with one clear line.
if out=$(docker run --rm --network none "$image" 2>&1); then
  die "corelata-api started without a config; it should refuse"
fi
printf '%s\n' "$out" | grep -q 'config file not found: /etc/corelata/corelata.yaml' \
  || die "the no-config failure should name the config path; got: $out"
echo "ok: $image"
