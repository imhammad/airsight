#!/usr/bin/env bash
# Nightly database backups for production (ADR 0014, issue #167).
#
# Runs as the backup service in docker-compose.prod.yml, in the same image as the database so
# pg_dump always matches the server. Every 10 minutes it checks the newest dump; once that is
# older than BACKUP_EVERY_HOURS (or there is none), it makes a new one. Checking often instead
# of at a fixed time means a Mac that slept through the night backs up soon after it wakes.
#
# Each dump is written inside the container first, checked with pg_restore --list, and only
# then copied into /backups (iCloud Drive on the Mac) under a temporary name and renamed, so a
# half-written file never looks like a backup. The newest BACKUP_KEEP dumps are kept.
set -euo pipefail

dir=/backups
every_hours="${BACKUP_EVERY_HOURS:-24}"
keep="${BACKUP_KEEP:-14}"

log() {
  printf '{"time":"%s","level":"%s","msg":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"
}

newest() {
  find "$dir" -maxdepth 1 -name 'airsight-*.dump' -type f | sort | tail -n 1
}

backup() {
  local stamp tmp name size
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="airsight-$stamp.dump"
  tmp="/tmp/$name"
  # Custom format: compressed, and pg_restore can restore all of it or single tables
  pg_dump --format=custom --file="$tmp"
  # A dump pg_restore can't read is not a backup
  pg_restore --list "$tmp" >/dev/null
  cp "$tmp" "$dir/.$name.partial"
  mv "$dir/.$name.partial" "$dir/$name"
  rm -f "$tmp"
  size="$(du -h "$dir/$name" | cut -f1)"
  log info "backup written: $name ($size)"
  # Keep the newest $keep; the names sort by time
  find "$dir" -maxdepth 1 -name 'airsight-*.dump' -type f | sort | head -n -"$keep" | while read -r old; do
    rm -f "$old"
    log info "old backup removed: $(basename "$old")"
  done
}

log info "backups every ${every_hours}h into $dir, keeping $keep"
while true; do
  latest="$(newest)"
  # find -mmin +N matches when the file is older than N minutes
  if [[ -z "$latest" ]] || [[ -n "$(find "$latest" -mmin +"$((every_hours * 60))")" ]]; then
    backup || log error "backup failed; trying again in 10 minutes"
  fi
  sleep "${BACKUP_CHECK_SECONDS:-600}"
done
