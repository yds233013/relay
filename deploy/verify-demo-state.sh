#!/usr/bin/env bash
# Check that the public demo is serving the canonical Brightwater state.
#
# The numbers below are a DEPLOYMENT EXPECTATION, not application behaviour. Nothing in
# `relay.*` or in the web tier knows them: they are what the deterministic engine produces from
# the committed fixtures, so if they ever change, the engine, the fixtures or the seed changed and
# somebody needs to know why. Runtime code that branched on them would be exactly the
# scenario-specific special-casing CLAUDE.md forbids.
#
# Usage: deploy/verify-demo-state.sh          (from the repository root, stack running)

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${RELAY_ENV_FILE:-.env.public}"
PROJECT="${RELAY_COMPOSE_PROJECT:-relay-public}"
FILES=(-f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml)

docker compose -p "$PROJECT" --env-file "$ENV_FILE" "${FILES[@]}" \
  run --rm --no-deps -T api python - <<'PYEOF'
import json
import sys
import urllib.request

EXPECTED = {
    "company_prefix": "Brightwater Provisions",
    "gates": 12,
    "failing_gates": 9,
    "unresolved_exposure": "217212.85",
    "currency": "USD",
    "run_sequence": 17,
    "run_is_current": True,
    "work_queue_decisions": 20,
    "investigations": 0,
    "applied_change_requests": 18,
    "largest_queue_amount": "38400.00",
}


def get(path: str):
    with urllib.request.urlopen("http://api:8000/api/v1" + path, timeout=30) as response:
        return json.load(response)


migrations = get("/migrations")
if len(migrations) != 1:
    sys.exit(f"expected exactly one migration, found {len(migrations)}")
migration = migrations[0]
mid = migration["id"]

readiness = get(f"/migrations/{mid}/readiness")
queue = get(f"/migrations/{mid}/work-queue")
applied = get(f"/migrations/{mid}/change-requests?status=applied&limit=100")
investigations = get(f"/migrations/{mid}/investigations")
amounts = sorted((i["amount"] for i in queue["items"] if i["amount"]), key=float, reverse=True)

found = {
    "company_prefix": migration["company_name"][: len(EXPECTED["company_prefix"])],
    "gates": len(readiness["gates"]),
    "failing_gates": sum(1 for g in readiness["gates"] if g["status"] == "fail"),
    "unresolved_exposure": readiness["unresolved_exposure"],
    "currency": readiness["currency"],
    "run_sequence": readiness["run_sequence"],
    "run_is_current": readiness["run_is_current"],
    "work_queue_decisions": len(queue["items"]),
    "investigations": len(investigations),
    "applied_change_requests": len(applied),
    "largest_queue_amount": amounts[0] if amounts else None,
}

width = max(len(k) for k in EXPECTED)
problems = []
for key, expected in EXPECTED.items():
    actual = found[key]
    ok = actual == expected
    print(f"  {key.ljust(width)}  {str(actual).ljust(24)} {'ok' if ok else f'EXPECTED {expected}'}")
    if not ok:
        problems.append(key)

print(f"  {'migration id'.ljust(width)}  {mid}")
if problems:
    sys.exit(f"canonical state does not match: {', '.join(problems)}")
print("canonical demo state verified")
PYEOF
