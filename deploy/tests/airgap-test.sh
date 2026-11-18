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
shipped_name() { # the project name compose.yaml in directory $1 gives, without the override
  (cd "$1" && env -u COMPOSE_PROJECT_NAME docker compose -f compose.yaml config --format json) \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])'
}
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
compose up -d --wait --wait-timeout 300

step "5. no route out"
# only an OSError (no route, refused, timed out, name failure) proves the seal; anything else fails
probe=$(api_py "
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=5)
except OSError as e:
    print(type(e).__name__, e)
else:
    raise SystemExit('connected')
" 2>&1) || die "the api container reached the internet, or the probe failed: $probe"
echo "no route out: $probe"

step "6. doctor and a full report"
compose exec -T api corelata doctor
health=$(api_py "import json, urllib.request
print(json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health'))['version'])")
[ "$health" = "$version" ] || die "/api/health reports '$health'; the bundle is '$version'"
echo "health reports the bundle version $health"
smoke run airgap

step "6a. a scanned PDF page is read by OCR with no network (CRL-95)"
# the demo config sets ingest.ocr: auto; Tesseract and its eng pack come from the bundle's image
grep -q 'ocr: auto' config/corelata.yaml || die "config/corelata.yaml does not set ingest.ocr: auto"
source_id=$(compose exec -T api python3 - "http://127.0.0.1:8080" <"$tests/ocr_smoke.py" | tail -1)
[ "$(sql "SELECT count(*) FROM source_unit WHERE source_id = '$source_id' AND meta->>'ocr' = 'true' AND text LIKE '%Varna%'")" = 1 ] \
  || die "the scanned page's unit is not marked ocr: $(sql "SELECT text, meta FROM source_unit WHERE source_id = '$source_id'")"

step "6b. the guide's housekeeping SQL removes old closed jobs and nothing else"
# The SQL is copied verbatim from the operator guide ("Housekeeping"; the worker runs the same
# statement nightly, this step proves the statement itself). The worker deletes
# succeeded jobs itself (delete_jobs=successful), so what accumulates is failed, cancelled and
# aborted jobs: plant one old and one recent failed job, and expect only the old one to go.
sql "INSERT INTO procrastinate_jobs (queue_name, task_name, status, scheduled_at) VALUES
  ('default', 'airgap.old', 'failed', now() - interval '60 days'),
  ('default', 'airgap.recent', 'failed', now() - interval '1 day')"
before=$(sql "SELECT count(*) FROM procrastinate_jobs")
compose exec -T postgres psql -U corelata -d corelata -c "
WITH old AS (
  SELECT j.id FROM procrastinate_jobs j
  WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted')
    AND COALESCE(j.scheduled_at,
          (SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id))
        < now() - interval '30 days'),
gone AS (DELETE FROM procrastinate_periodic_defers WHERE job_id IN (SELECT id FROM old))
DELETE FROM procrastinate_jobs WHERE id IN (SELECT id FROM old)"
after=$(sql "SELECT count(*) FROM procrastinate_jobs")
[ "$((before - after))" -ge 1 ] || die "the housekeeping SQL deleted no jobs ($before before, $after after)"
[ "$(sql "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'airgap.old'")" = 0 ] || die "the old closed job survived"
[ "$(sql "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'airgap.recent'")" = 1 ] || die "the recent closed job was deleted"
echo "housekeeping deleted $((before - after)) job(s)"
smoke check airgap

step "7. a pack edit and a config change take effect"
rule=config/packs/icd203-base/rules/icd203.tc.8.yaml
grep -q '^title:' "$rule" || die "$rule has no title line"
sed -i.bak 's/^title: .*/title: "Sourcing is clear (edited on site)"/' "$rule" && rm "$rule.bak"
grep -q 'max_upload_mb: 200' config/corelata.yaml || die "config/corelata.yaml has no max_upload_mb: 200 to change"
sed -i.bak 's/max_upload_mb: 200/max_upload_mb: 123/' config/corelata.yaml && rm config/corelata.yaml.bak
worker_before=$(compose ps -q worker)
compose up -d --wait --wait-timeout 300 --force-recreate migrate api worker
[ "$(compose ps -q worker)" != "$worker_before" ] || die "the worker was not recreated"
api_py "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/packs/icd203-base/resolved')); assert any(x['title']=='Sourcing is clear (edited on site)' for x in r['rules']), 'edited rule not served'"
# /api/system/info reports api.max_upload_mb from the config the API loaded
api_py "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/system/info')); assert r['max_upload_mb']==123, r"
compose exec -T api corelata doctor
smoke check airgap

step "8. an invalid config stops migrate and keeps api and worker down"
cp config/corelata.yaml "$tmp/good.yaml"
echo "nonsense: 1" >>config/corelata.yaml
if compose up -d --wait --wait-timeout 300 --force-recreate migrate api worker >"$tmp/bad.log" 2>&1; then
  die "the stack started with an invalid config"
fi
compose logs migrate | grep -qi "nonsense" || die "migrate's log does not name the bad key: $(compose logs migrate | tail -5)"
[ -z "$(compose ps -q --status running api worker)" ] || die "api or worker kept running with an invalid config"
cp "$tmp/good.yaml" config/corelata.yaml
compose up -d --wait --wait-timeout 300 --force-recreate migrate api worker
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
for site in "$site1" "$site2"; do
  name=$(shipped_name "$site") || die "docker compose config failed in $site"
  [ "$name" = corelata ] || die "$site/compose.yaml names project '$name', not corelata"
done
compose up -d --wait --wait-timeout 300
api_py "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/packs/icd203-base/resolved')); assert any(x['title']=='Sourcing is clear (edited on site)' for x in r['rules']), 'edited rule lost on upgrade'"
smoke check airgap

step "11. restore over a newer schema"
compose down -v
compose up -d --wait --wait-timeout 300
if smoke check airgap >/dev/null 2>&1; then die "the data survived down -v; the restore test proves nothing"; fi
sql "CREATE TABLE newer_feature (id int); UPDATE alembic_version SET version_num = '9999_newer';"
./restore.sh --yes "$db" "$files"
[ "$(sql "SELECT count(*) FROM information_schema.tables WHERE table_name = 'newer_feature'")" = 0 ] || die "the newer table survived the restore"
[ "$(sql "SELECT version_num FROM alembic_version")" != "9999_newer" ] || die "alembic_version was not restored"
smoke check airgap

echo
echo "airgap: ok ($version)"
