#!/usr/bin/env bash
# Start Relay's backend on Railway: migrate, seed on first boot only, then run the API and the
# worker side by side and exit if either stops, so Railway restarts the whole service.
set -euo pipefail

# Railway mounts the volume root-owned. Fix ownership once, then re-exec this script as the
# unprivileged relay user; nothing below this block ever runs as root.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/blobs
  chown -R relay:relay /data/blobs
  chmod 700 /data/blobs
  exec setpriv --reuid=relay --regid=relay --init-groups "$0" "$@"
fi

cd /app

echo "relay-railway: migrating"
alembic upgrade head

# Decide what this database still needs. Two steps, and neither may run twice:
#   `relay-demo seed` is not idempotent — a second run would create a second Brightwater;
#   `relay-demo public-demo` is only half idempotent — the visitor step is, but the AI-consent step
#   files a policy change that Relay refuses once consent already exists ("the policy change
#   changes nothing"). So both run on an empty database, preparation re-runs only if a previous
#   boot died between the two, and a normal restart or redeploy runs neither.
state=$(python - <<'PY'
import sqlalchemy as sa
from relay.core.config import get_settings
from relay.core.db import create_db_engine
from relay.identity.models import DEMO_VISITOR_EMAIL
with create_db_engine(get_settings()).connect() as connection:
    migrations = connection.execute(sa.text("select count(*) from migrations")).scalar_one()
    visitor = connection.execute(
        sa.text("select count(*) from users where email = :email"), {"email": DEMO_VISITOR_EMAIL}
    ).scalar_one()
    consented = connection.execute(
        sa.text("select count(*) from migrations where ai_enabled")
    ).scalar_one()
print("empty" if migrations == 0 else "ready" if visitor and consented else "unprepared")
PY
)
case "$state" in
  empty)
    echo "relay-railway: empty database, seeding Brightwater (fictional)"
    relay-demo seed --fixtures /fixtures/demo/brightwater \
      --mapping-set /fixtures/demo/brightwater_config/column_mapping_set_v1.json
    relay-demo public-demo
    ;;
  unprepared)
    echo "relay-railway: seeded but not prepared (an earlier boot stopped halfway); preparing"
    relay-demo public-demo
    ;;
  *)
    echo "relay-railway: demo already seeded and prepared; starting"
    ;;
esac

relay worker &
worker=$!
uvicorn relay.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log &
api=$!

# Forward Railway's SIGTERM to both, so an in-flight job gets its grace period.
trap 'kill -TERM "$worker" "$api" 2>/dev/null || true' TERM INT

# Whichever stops first takes the other with it; Railway's restart policy brings both back.
set +e
wait -n "$worker" "$api"
status=$?
kill -TERM "$worker" "$api" 2>/dev/null
wait
exit "$status"
