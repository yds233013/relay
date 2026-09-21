#!/usr/bin/env bash
# Return the public demo to its canonical state.
#
# What this destroys: everything visitors did — investigations, the audit events they produced,
# and any blob written since the last reset. It drops and recreates Relay's database and empties
# the blob volume, then re-seeds Brightwater through the same services a fresh install uses.
#
# What this deliberately leaves alone: the images (nothing is rebuilt), Caddy's certificates and
# configuration (its container is never stopped, so the certificate is not re-issued and the
# Let's Encrypt rate limit is not touched), PostgreSQL's container and its volume, and the compose
# network. The old reset removed volumes and rebuilt; that cost a certificate and several minutes
# for state a `DROP DATABASE` clears in seconds.
#
# During the reset the site answers 502: Caddy is up but the web tier is stopped. That is the
# downtime, and it is printed at the end.
#
# Usage:
#   deploy/public-demo-reset.sh            interactive, asks before destroying anything
#   deploy/public-demo-reset.sh --yes      no prompt (cron, CI, an operator who means it)
#   RELAY_RESET_ASSUME_YES=1 ... --yes     same, for automation that cannot pass flags

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${RELAY_ENV_FILE:-.env.public}"
PROJECT="${RELAY_COMPOSE_PROJECT:-relay-public}"

if [ ! -f "$ENV_FILE" ]; then
  echo "missing $ENV_FILE — copy .env.public.example and fill it in (docs/public-deployment.md)" >&2
  exit 1
fi

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" \
    -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml "$@"
}

# shellcheck disable=SC1090
DB_USER="$(grep -E '^RELAY_DB_USER=' "$ENV_FILE" | cut -d= -f2-)"
DB_NAME="$(grep -E '^RELAY_DB_NAME=' "$ENV_FILE" | cut -d= -f2-)"
: "${DB_USER:?RELAY_DB_USER is not set in $ENV_FILE}"
: "${DB_NAME:?RELAY_DB_NAME is not set in $ENV_FILE}"

assume_yes="${RELAY_RESET_ASSUME_YES:-0}"
for arg in "$@"; do
  case "$arg" in
    --yes|-y) assume_yes=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cat <<'WARNING'

  ============================================================================
  THIS WILL DELETE PUBLIC DEMO INTERACTION STATE

    - every investigation visitors have started
    - the audit events those produced
    - every blob written since the last reset
    - the whole Relay database, which is then recreated and re-seeded

  It does NOT touch Caddy's certificates, the images, or PostgreSQL's volume.
  The site answers 502 while it runs.
  ============================================================================

WARNING

if [ "$assume_yes" != "1" ]; then
  printf 'Type "reset" to continue: '
  read -r answer
  if [ "$answer" != "reset" ]; then
    echo "aborted; nothing was changed"
    exit 1
  fi
fi

started=$(date +%s)

echo "==> stopping the Relay services that write (Caddy and PostgreSQL stay up)"
compose stop web api worker

echo "==> dropping and recreating the database"
# Connect to the maintenance database: a database cannot be dropped from inside itself. FORCE
# detaches anything still connected, which matters because the API's pool may not have drained.
compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE);" \
  -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"

echo "==> emptying the blob volume"
# Content-addressed files; the seed writes them again. Emptying keeps disk bounded across resets.
compose run --rm --no-deps --entrypoint sh api \
  -c 'find /data/blobs -mindepth 1 -maxdepth 1 -exec rm -rf {} +'

echo "==> migrating"
compose run --rm migrate

echo "==> seeding Brightwater (fictional)"
compose run --rm --no-deps -v "$PWD/fixtures:/fixtures:ro" api \
  relay-demo seed --fixtures /fixtures/demo/brightwater \
  --mapping-set /fixtures/demo/brightwater_config/column_mapping_set_v1.json

echo "==> preparing the public demo visitor and the governed demo-AI consent"
compose run --rm --no-deps api relay-demo public-demo

echo "==> starting the Relay services again"
compose up -d --wait web api worker

echo "==> verifying the canonical state"
deploy/verify-demo-state.sh

finished=$(date +%s)
echo
echo "reset complete in $((finished - started))s (site returned 502 for most of that)"
