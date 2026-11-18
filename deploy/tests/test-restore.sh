#!/usr/bin/env bash
# Tests restore.sh's validation against a stub `docker` that records its calls: a bad input must be
# refused before any service is stopped. Usage: deploy/tests/test-restore.sh
set -euo pipefail
deploy=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$work/bin" "$work/src" "$work/tmp"
cat >"$work/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"$DOCKER_LOG"
case "$*" in
  *"pg_namespace"*)
    # the restore runs in a process group of its own (set -m below): signal all of it
    [ -z "${STUB_SCHEMA_SIGNAL:-}" ] || kill -"$STUB_SCHEMA_SIGNAL" 0
    [ -z "${STUB_SCHEMA_STDERR:-}" ] || echo "$STUB_SCHEMA_STDERR" >&2
    [ -z "${STUB_SCHEMA_RC:-}" ] || exit "$STUB_SCHEMA_RC"
    printf '%s\n' ${STUB_SCHEMAS:-} ;;
  *"compose stop api worker"*) exit "${STUB_STOP_RC:-0}" ;;
  *"pg_restore -l"*) [ -z "${STUB_BAD_DUMP:-}" ] || exit 1 ;;
  *"--entrypoint sh"*) exit "${STUB_FILES_RC:-0}" ;;
  *"exec -T postgres sh -c"*)
    # the first command after the services were stopped
    [ -z "${STUB_DB_SIGNAL:-}" ] || kill -"$STUB_DB_SIGNAL" 0
    exit "${STUB_DB_RC:-0}" ;;
esac
EOF
chmod +x "$work/bin/docker"
export PATH="$work/bin:$PATH"

echo hello >"$work/src/a.txt"
tar -czf "$work/files.tar.gz" -C "$work/src" .
echo dump >"$work/db.dump"
echo "not gzip" >"$work/bad.tar.gz"

restore() {  # runs restore.sh with --yes; output in $work/out, docker calls in $work/log
  : >"$work/log"
  local rc=0
  TMPDIR="$work/tmp" DOCKER_LOG="$work/log" "$deploy/restore.sh" --yes "$@" >"$work/out" 2>&1 || rc=$?
  # whatever the outcome, restore.sh leaves no temporary file behind
  [ -z "$(ls -A "$work/tmp")" ] || fail "a temporary file was left behind: $(ls -A "$work/tmp")"
  return "$rc"
}

if restore "$work/db.dump" "$work/bad.tar.gz"; then fail "a bad archive was accepted"; fi
grep -q "^error: .*bad.tar.gz is not a valid files archive" "$work/out" || fail "bad archive: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "bad archive: services were stopped"
echo "ok - a bad files archive is refused before anything is stopped"

if restore "$work/files.tar.gz" "$work/db.dump"; then fail "swapped arguments were accepted"; fi
grep -q "^error: .*db.dump is not a valid files archive" "$work/out" || fail "swapped: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "swapped: services were stopped"
echo "ok - swapped arguments are refused"

if STUB_BAD_DUMP=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a bad dump was accepted"; fi
grep -q "^error: .*db.dump is not a valid database dump" "$work/out" || fail "bad dump: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "bad dump: services were stopped"
echo "ok - a bad database dump is refused before anything is stopped"

if "$deploy/restore.sh" "$work/db.dump" "$work/files.tar.gz" </dev/null >"$work/out" 2>&1; then fail "no terminal, no --yes"; fi
grep -q "^error: this needs a terminal" "$work/out" || fail "no tty: $(cat "$work/out")"
echo "ok - no terminal and no --yes is refused"

restore "$work/db.dump" "$work/files.tar.gz" || fail "good restore: $(cat "$work/out")"
grep -q "^compose stop api worker" "$work/log" || fail "good restore: no stop"
# a backup from before a schema-changing upgrade: the newer tables must go too, in the same
# transaction as the restore (the air-gap test restores over a newer schema for real)
grep -q "BEGIN; DROP SCHEMA public CASCADE;" "$work/log" || fail "good restore: the schema is not emptied first"
grep -q 'pg_restore --no-owner -f - && echo "COMMIT;"' "$work/log" || fail "good restore: COMMIT does not wait for pg_restore"
tr '\n' ' ' <"$work/log" | grep -q "compose exec -T postgres sh -c .*DROP SCHEMA public CASCADE.*pg_restore --no-owner" \
  || fail "good restore: DROP SCHEMA and pg_restore are not in one exec call"
grep -q "^compose run --rm --no-deps -T --entrypoint sh worker" "$work/log" || fail "good restore: no files restore"
[ "$(tail -n1 "$work/log")" = "compose up -d --wait" ] || fail "good restore: not restarted: $(cat "$work/log")"
echo "ok - a good restore stops, restores and restarts"

if STUB_FILES_RC=4 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a files failure was ignored"; fi
grep -q "^error: the files restore failed after the old files were removed" "$work/out" || fail "files fail: $(cat "$work/out")"
[ "$(tail -n1 "$work/log")" = "compose up -d" ] || fail "files fail: not restarted: $(cat "$work/log")"
echo "ok - a files failure says so and restarts Corelata"

if STUB_DB_RC=5 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a database failure was ignored"; fi
grep -q "^error: the database restore failed and was rolled back" "$work/out" || fail "db fail: $(cat "$work/out")"
! grep -q -e "--entrypoint sh worker" "$work/log" || fail "db fail: the files were touched: $(cat "$work/log")"
[ "$(tail -n1 "$work/log")" = "compose up -d" ] || fail "db fail: not restarted: $(cat "$work/log")"
echo "ok - a database failure leaves the files alone and restarts Corelata"

if STUB_SCHEMAS="analytics audit" restore "$work/db.dump" "$work/files.tar.gz"; then fail "foreign schemas were accepted"; fi
grep -q "^error: the database holds schemas restore.sh does not manage: analytics audit" "$work/out" || fail "schemas: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "schemas: services were stopped"
echo "ok - a foreign schema is refused before anything is stopped"

if STUB_SCHEMAS="pglogical" restore "$work/db.dump" "$work/files.tar.gz"; then fail "a pg-lookalike schema was accepted"; fi
grep -q "^error: the database holds schemas restore.sh does not manage: pglogical" "$work/out" || fail "pglogical: $(cat "$work/out")"
grep -q "left(nspname, 3)" "$work/log" || fail "the query no longer excludes only pg_ by prefix"
echo "ok - a schema that merely looks like pg_ is refused"

if STUB_SCHEMA_RC=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a failed schema query was ignored"; fi
grep -q "^error: could not list the database's schemas" "$work/out" || fail "schema query: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "schema query: services were stopped"
echo "ok - a failed schema query refuses the restore before anything is stopped"

refused='psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed: Connection refused'
if STUB_SCHEMA_RC=2 STUB_SCHEMA_STDERR="$refused" restore "$work/db.dump" "$work/files.tar.gz"; then fail "a refused connection was ignored"; fi
grep -q "^error: could not list the database's schemas" "$work/out" || fail "refused: $(cat "$work/out")"
grep -q "^psql said:$" "$work/out" || fail "refused: psql's message has no heading: $(cat "$work/out")"
grep -qF "  $refused" "$work/out" || fail "refused: psql's message is missing: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "refused: services were stopped"
echo "ok - a refused connection shows psql's own message"

if STUB_SCHEMA_RC=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a silent schema query failure was ignored"; fi
! grep -q "^psql said:" "$work/out" || fail "silent: an empty psql message got a heading: $(cat "$work/out")"
echo "ok - a schema query that fails silently prints no empty heading"

STUB_SCHEMA_STDERR='WARN[0000] The "X" variable is not set. Defaulting to a blank string.' \
  restore "$work/db.dump" "$work/files.tar.gz" || fail "a warning on stderr refused the restore: $(cat "$work/out")"
echo "ok - a warning on stderr is not read as a schema name"

# A signal while the schema query runs. TERM, not INT: a shell started in the background (a
# CI wrapper, a process substitution) inherits SIGINT ignored, and an ignored-on-entry signal
# can be neither trapped nor delivered; restore.sh traps both the same way. The live rehearsal
# presses Ctrl-C.
: >"$work/log"
set -m # job control: the background restore gets a process group of its own for the stub to signal
STUB_SCHEMA_SIGNAL=TERM TMPDIR="$work/tmp" DOCKER_LOG="$work/log" \
  "$deploy/restore.sh" --yes "$work/db.dump" "$work/files.tar.gz" >"$work/out" 2>&1 &
rc=0
wait $! || rc=$?
set +m
[ "$rc" = 143 ] || fail "TERM: expected exit 143, got $rc: $(cat "$work/out")"
[ -z "$(ls -A "$work/tmp")" ] || fail "TERM: psql's message file was left behind: $(ls -A "$work/tmp")"
! grep -q "stop" "$work/log" || fail "TERM: services were stopped"
! grep -q "interrupted after stopping" "$work/out" || fail "TERM: the interrupted-after-stop line appeared before the stop: $(cat "$work/out")"
echo "ok - a signal during the schema query leaves no temporary file and stops nothing"

# A signal after the services were stopped (during the database restore): Corelata comes back up.
: >"$work/log"
set -m
STUB_DB_SIGNAL=TERM TMPDIR="$work/tmp" DOCKER_LOG="$work/log" \
  "$deploy/restore.sh" --yes "$work/db.dump" "$work/files.tar.gz" >"$work/out" 2>&1 &
rc=0
wait $! || rc=$?
set +m
[ "$rc" = 143 ] || fail "TERM after stop: expected exit 143, got $rc: $(cat "$work/out")"
grep -q "^compose stop api worker" "$work/log" || fail "TERM after stop: services were not stopped: $(cat "$work/log")"
[ "$(tail -n1 "$work/log")" = "compose up -d" ] || fail "TERM after stop: not restarted: $(cat "$work/log")"
grep -qxF "restore.sh: interrupted after stopping Corelata; the database may be restored but not the files. Run ./restore.sh again with the same two files." "$work/out" \
  || fail "TERM after stop: no interrupted line: $(cat "$work/out")"
[ -z "$(ls -A "$work/tmp")" ] || fail "TERM after stop: a temporary file was left behind: $(ls -A "$work/tmp")"
echo "ok - a signal after the services were stopped restarts them and leaves no temporary file"

if STUB_FILES_RC=3 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a clear failure was ignored"; fi
grep -q "^error: the old files could not be cleared" "$work/out" || fail "clear fail: $(cat "$work/out")"
[ "$(tail -n1 "$work/log")" = "compose up -d" ] || fail "clear fail: not restarted: $(cat "$work/log")"
echo "ok - a failure to clear the old files says so and restarts Corelata"

if STUB_STOP_RC=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a stop failure was ignored"; fi
grep -q "^error: could not stop Corelata; nothing was changed" "$work/out" || fail "stop fail: $(cat "$work/out")"
! grep -q "DROP SCHEMA" "$work/log" || fail "stop fail: the database was touched"
echo "ok - a stop failure changes nothing"

restore "$work/db.dump" "$work/files.tar.gz" || fail "ordering: $(cat "$work/out")"
steps=$(sed -n -e 's/^compose stop api worker.*/stop/p' -e 's/^compose exec -T postgres sh -c.*/db/p' -e 's/^compose run --rm --no-deps -T --entrypoint sh worker.*/files/p' -e 's/^compose up -d --wait$/up/p' "$work/log" | tr '\n' ' ' | sed 's/ $//')
[ "$steps" = "stop db files up" ] || fail "ordering: expected stop db files up, got: $steps"
[ "$(grep -c "^compose exec -T postgres sh -c" "$work/log")" = 1 ] || fail "ordering: the database restore ran more than once"
echo "ok - stop, database, files, up happen once and in that order"

echo "restore.sh: all tests passed"
