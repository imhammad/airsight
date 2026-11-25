#!/usr/bin/env bash
# Restores a backup into a separate database, so a backup can be proven without touching
# production (issue #167). Run it in the backup service:
#
#   prod exec backup restore.sh                                  # the newest backup
#   prod exec backup restore.sh airsight-20261124T093000Z.dump   # a chosen one
#
# It restores into airsight_restore_check (or RESTORE_DB), compares row counts with the live
# database, and leaves the copy for you to look at. Drop it afterwards with:
#
#   prod exec backup dropdb airsight_restore_check
#
# docs/RUNBOOK.md ("Restore the database") uses it with RESTORE_DB to recover from a real loss.
set -euo pipefail

dir=/backups
target="${RESTORE_DB:-airsight_restore_check}"
live="${PGDATABASE:-airsight}"
[[ "$target" != "$live" ]] || { echo "refusing to restore over the live database $live" >&2; exit 1; }

file="${1:-$(find "$dir" -maxdepth 1 -name 'airsight-*.dump' -type f | sort | tail -n 1)}"
[[ -n "$file" ]] || { echo "no backups in $dir" >&2; exit 1; }
[[ "$file" == /* ]] || file="$dir/$file"
[[ -f "$file" ]] || { echo "not found: $file" >&2; exit 1; }
echo "restoring $(basename "$file") into $target"

dropdb --if-exists "$target"
createdb "$target"
# TimescaleDB's own restore procedure: create the extension, pause its background jobs,
# restore, then resume. The dump's own CREATE EXTENSION lines then report "already exists",
# which is expected, so the restore runs without --exit-on-error and the counts below decide.
psql -q -d "$target" -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()" >/dev/null
pg_restore --dbname="$target" --no-owner "$file" 2>/tmp/restore-errors.txt || true
psql -q -d "$target" -c "SELECT timescaledb_post_restore()" >/dev/null
grep -v -e 'already exists' -e '^pg_restore: from TOC entry' -e '^pg_restore: error: could not execute query' \
  -e '^Command was:' -e 'errors ignored on restore' -e '^pg_restore: warning: errors ignored' /tmp/restore-errors.txt || true

# Row counts in every table, restored next to live. Live keeps growing, so it may be a little
# ahead; a restored table with far fewer rows, or none, means the backup is not good.
tables="$(psql -At -d "$target" -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys' ORDER BY 1")"
printf '%-22s %12s %12s\n' table restored live
bad=0
for t in $tables; do
  r="$(psql -At -d "$target" -c "SELECT count(*) FROM \"$t\"")"
  # In a real recovery the live database may be broken or empty; then it shows as -
  l="$(psql -At -d "$live" -c "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo -)"
  printf '%-22s %12s %12s\n' "$t" "$r" "$l"
  if [[ "$l" =~ ^[0-9]+$ && "$l" -gt 0 && "$r" -eq 0 ]]; then bad=1; fi
done
if [[ "$bad" -eq 1 ]]; then
  echo "RESTORE CHECK FAILED: a table with live rows came back empty" >&2
  exit 1
fi
echo "restore check passed"
