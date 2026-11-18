#!/usr/bin/env bash
# Restore a backup made by backup.sh (operator guide, "Restore"). It REPLACES all of Corelata's
# data with the backup's. Run it from the install directory.
# Usage: ./restore.sh [--yes] DB_DUMP FILES_ARCHIVE
set -euo pipefail
die() { echo "error: $*" >&2; exit 1; }
usage() { echo "usage: ./restore.sh [--yes] DB_DUMP FILES_ARCHIVE" >&2; exit 2; }

yes=false
paths=()
for arg in "$@"; do
  case $arg in
    --yes) yes=true ;;
    -*) usage ;;
    *) paths+=("$arg") ;;
  esac
done
[ ${#paths[@]} -eq 2 ] || usage
for p in "${paths[@]}"; do [ -f "$p" ] || die "$p is not a file"; done
db="$(cd "$(dirname "${paths[0]}")" && pwd)/$(basename "${paths[0]}")"
archive="$(cd "$(dirname "${paths[1]}")" && pwd)/$(basename "${paths[1]}")"
cd "$(dirname "$0")"

# 1. Check both inputs before anything is stopped or changed.
{ gzip -t "$archive" && tar -tzf "$archive" >/dev/null; } 2>/dev/null \
  || die "$archive is not a valid files archive (corelata-files-*.tar.gz); the order is DB_DUMP then FILES_ARCHIVE"
docker compose up -d --wait postgres >/dev/null || die "could not start the database; see the message above"
docker compose exec -T postgres pg_restore -l <"$db" >/dev/null 2>&1 \
  || die "$db is not a valid database dump (corelata-db-*.dump); the order is DB_DUMP then FILES_ARCHIVE"

# Every exit from here on runs on_exit: an error, a refusal, Ctrl-C or a TERM (the INT and
# TERM traps exit, which runs the EXIT trap). It removes psql's message file and, once api and
# worker were stopped, brings Corelata back up after a failure.
psql_err=""
stopped=false
on_exit() {
  local rc=$?
  [ -z "$psql_err" ] || rm -f "$psql_err"
  if $stopped && [ $rc -ne 0 ]; then
    if [ $rc -eq 130 ] || [ $rc -eq 143 ]; then
      echo "restore.sh: interrupted after stopping Corelata; the database may be restored but not the files. Run ./restore.sh again with the same two files." >&2
    fi
    docker compose up -d >/dev/null 2>&1 || echo "error: Corelata could not be restarted; run docker compose up -d" >&2
  fi
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# restore.sh empties and refills `public` only. Anything else in the database (an extension's
# schema, a reporting schema someone added) would be left out of step with the restored data,
# so it is refused here, before anything is stopped. psql's stderr goes to a file of its own, so
# a warning from docker compose can never be read as a schema name, and a failure shows why.
psql_err=$(mktemp "${TMPDIR:-/tmp}/corelata-restore.XXXXXX")
if ! foreign=$(docker compose exec -T postgres psql -X -q -t -A -U corelata -d corelata -c \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema') AND left(nspname, 3) <> 'pg_' ORDER BY 1" 2>"$psql_err" | tr '\n' ' ' | sed 's/ *$//'); then
  echo "error: could not list the database's schemas; is the database up (docker compose ps)?" >&2
  if [ -s "$psql_err" ]; then
    echo "psql said:" >&2
    sed 's/^/  /' "$psql_err" >&2
  fi
  exit 1
fi
rm -f "$psql_err"
psql_err=""
[ -z "$foreign" ] || die "the database holds schemas restore.sh does not manage: $foreign; move or drop them, then run the restore again"

if ! $yes; then
  [ -t 0 ] || die "this needs a terminal to confirm; add --yes to restore without asking"
  read -r -p "This replaces all Corelata data with the backup. Type 'restore' to go on: " answer
  [ "$answer" = restore ] || die "nothing was restored"
fi

# 2. From here on, on_exit brings Corelata back up if anything fails.
stopped=true
docker compose stop api worker >/dev/null || die "could not stop Corelata; nothing was changed"
# One transaction: empty the schema (a newer version's tables too; everything Corelata and its
# job queue create lives in public), then the dump's SQL. COMMIT is sent only when pg_restore
# read the whole dump, so a failure anywhere leaves the database as it was.
docker compose exec -T postgres sh -c 'set -o pipefail
  { echo "SET client_min_messages = warning; BEGIN; DROP SCHEMA public CASCADE;"
    echo "CREATE SCHEMA public AUTHORIZATION pg_database_owner; GRANT USAGE ON SCHEMA public TO PUBLIC;"
    pg_restore --no-owner -f - && echo "COMMIT;"
  } | psql -X -q -v ON_ERROR_STOP=1 -U corelata -d corelata' <"$db" >/dev/null \
  || die "the database restore failed and was rolled back; Corelata is being restarted with the data as it was before the restore"
rc=0
docker compose run --rm --no-deps -T --entrypoint sh worker \
  -c 'find /data/files -mindepth 1 -delete || exit 3; tar -C /data/files -xzf - || exit 4' <"$archive" || rc=$?
case $rc in
  0) ;;
  3) die "the old files could not be cleared, so the stored files may be partly removed; the database is restored; run ./restore.sh again" ;;
  *) die "the files restore failed after the old files were removed; the database is restored but the stored files are incomplete; run ./restore.sh again with a good archive" ;;
esac
stopped=false
docker compose up -d --wait >/dev/null || die "Corelata did not become healthy after the restore; see docker compose ps and docker compose logs"
echo "Restored $db and $archive"
