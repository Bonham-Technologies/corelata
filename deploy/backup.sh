#!/usr/bin/env bash
# Back up Corelata's database and stored files (operator guide, "Backups"). Run it from the
# install directory while Corelata is running. The backups hold every document: keep them private.
# Usage: ./backup.sh [DIR]    default DIR: ./backups
set -euo pipefail
umask 077
dir=${1:-backups}
mkdir -p "$dir"
dir=$(cd "$dir" && pwd)
cd "$(dirname "$0")"
die() { echo "error: $*" >&2; exit 1; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
db="$dir/corelata-db-$stamp.dump"
files="$dir/corelata-files-$stamp.tar.gz"
# Each file is written as <name>.partial and renamed only when both backups are complete,
# so a failed run never leaves something that looks like a backup.
trap 'rm -f "$db.partial" "$files.partial"' EXIT

docker compose exec -T postgres pg_dump -U corelata -d corelata --format=custom >"$db.partial" \
  || die "the database backup failed; is Corelata running (docker compose ps)?"
docker compose run --rm --no-deps -T --entrypoint tar worker -C /data/files -czf - . >"$files.partial" \
  || die "the files backup failed; see the message above"
# The files volume streams through a one-shot container; a very large volume is slow on some hosts (a bind mount read directly would be faster but ties the script to the volume's location).
gzip -t "$files.partial" || die "the files backup is damaged (is the disk full?); nothing was kept"
[ -s "$db.partial" ] || die "the database backup is empty; nothing was kept"
mv "$db.partial" "$db"
mv "$files.partial" "$files"
echo "Backed up to $db and $files"
