#!/usr/bin/env bash
# Back up the public deployment: one database dump and one blob archive, in that order.
#
# Order matters, and only in one direction. Relay's blobs are content-addressed and append-only,
# and the database holds the references to them. Dumping the database first and archiving blobs
# second means anything written in between lands in the archive but is not referenced by the dump —
# an orphan, which is harmless. The other order would put a reference in the dump whose blob is
# missing from the archive, and that is a broken restore. So: database, then blobs, always.
#
# This is deliberately two files and a cron line, not backup infrastructure. The demo holds
# fictional data that can be regenerated from the repository in minutes; the point of a backup here
# is to avoid re-seeding and to keep the audit chain of whatever visitors did.
#
# Usage: deploy/public-backup.sh [destination-directory]   (default ./backups)

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${RELAY_ENV_FILE:-.env.public}"
PROJECT="${RELAY_COMPOSE_PROJECT:-relay-public}"
DEST="${1:-./backups}"

test -f "$ENV_FILE" || { echo "missing $ENV_FILE" >&2; exit 1; }

DB_USER="$(grep -E '^RELAY_DB_USER=' "$ENV_FILE" | cut -d= -f2-)"
DB_NAME="$(grep -E '^RELAY_DB_NAME=' "$ENV_FILE" | cut -d= -f2-)"

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" \
    -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml "$@"
}

mkdir -p "$DEST"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
db_file="$DEST/relay-db-$stamp.dump"
blob_file="$DEST/relay-blobs-$stamp.tar.gz"

echo "==> database -> $db_file"
# Custom format: compressed, and pg_restore can read it selectively.
compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom > "$db_file"

echo "==> blobs -> $blob_file"
compose run --rm --no-deps -T --entrypoint tar api -czf - -C /data blobs > "$blob_file"

chmod 600 "$db_file" "$blob_file"
ls -lh "$db_file" "$blob_file"
echo
echo "restore: docs/public-deployment.md §11"
