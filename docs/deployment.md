# Deployment

How to run Relay on a single host with the deployment overlay, what it does not yet do, and how to
back it up. Everything stated here was executed against the overlay on 2026-09-20; the commands are
the ones that were run, not sketches.

Files: [`docker-compose.prod.yml`](../docker-compose.prod.yml),
[`.env.production.example`](../.env.production.example).

---

## 0. Which mode is this?

Three deployment modes exist, as separate `RELAY_ENV` values rather than flags:

| | `local` / `test` | `demo` | `production` |
|---|---|---|---|
| Overlay | none (base compose) | `docker-compose.demo.yml` | `docker-compose.prod.yml` |
| Who is acting | the `X-Relay-User` header | the seeded read-only visitor; header ignored | nobody — 401 everywhere |
| Mutations | all | refused but one, before routing | unreachable |
| AI providers | any | `demo`/`disabled` only, enforced at startup | any |

**This document is about `production`.** For the anonymous public demo — which is the one mode that
is genuinely serviceable to strangers today — see [public-demo.md](public-demo.md).

---

## 1. Before you deploy anything

**Relay has no authentication, and production mode makes that explicit rather than dangerous.**

Real authentication (OIDC/SSO) is post-MVP and always has been — `docs/product-spec.md` §"Out of
scope" and `docs/architecture.md` §Identity both say so. The only identity mechanism is the
development header `X-Relay-User`, which names a seeded user, and SEC-11 requires it to be inert
outside `local` and `test`.

The consequence, measured against the overlay rather than reasoned about:

| Request in `RELAY_ENV=production` | Result |
|---|---|
| `GET /health` | 200 |
| `GET /health/ready` | 200 |
| `GET /api/v1/migrations` — no identity | **401** |
| `GET /api/v1/migrations` — with `X-Relay-User` | **401** |

The stack starts, reports healthy, serves the web tier and answers liveness probes. Every endpoint
that touches a migration returns 401, for everyone. **A production deployment of Relay today serves
no users.** That is the correct behaviour — the alternative is an open door — but it means this
overlay prepares a deployment rather than enabling one.

**Do not work around it by deploying with `RELAY_ENV=local`.** In `local`, `X-Relay-User` is
honoured, so anyone who can reach the web tier can send the customer controller's address and
approve their own change requests. That is not a weakened deployment; it is no access control at
all, on a system whose entire purpose is segregation of duties.

To actually serve users, one thing has to be built: replace `current_actor()` in
`backend/src/relay/api/deps.py` with a real authenticator. Every authorization path in the product
already flows through that single dependency and through `identity.require()`, which is why the
seam exists. Until then, treat this overlay as verified infrastructure waiting on that change.

The startup guards that enforce all of this are real and were exercised:

| Misconfiguration | Result |
|---|---|
| `RELAY_ENV=production` with a password containing `local_dev_only` | refused: *"production requires a real database password"* |
| `RELAY_ENV=production` with an empty password | refused, same error |
| `RELAY_ENV=production` with `RELAY_DEV_IDENTITY_ENABLED=true` | refused: *"the development identity header cannot be enabled in production"* |
| `RELAY_ENV=production` with `RELAY_LOG_FORMAT=console` | refused: *"production requires log_format=json"* |
| `RELAY_AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` **absent** | refused: *"ai_provider=anthropic requires ANTHROPIC_API_KEY in the environment"* |
| `RELAY_AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` set but **empty** or whitespace | refused, same error — a blank value counts as absent |

---

## 2. What the overlay runs

Five services on one Docker network, from the same two images the development stack uses:

| Service | What it is | Published |
|---|---|---|
| `db` | PostgreSQL 16, pinned by digest | no — compose network only |
| `migrate` | one-shot `alembic upgrade head`, then exits | no |
| `api` | FastAPI, non-root uid 10001 | no — reached by `web` at `http://api:8000` |
| `worker` | job worker: imports, pipeline runs, investigations | no |
| `web` | Next.js standalone, non-root uid 10001 | `127.0.0.1:3000` by default |

`api` starts only after `migrate` completes successfully, so the schema is never behind the code.
`api` and `worker` share the `relay-blobs` volume; both must see the same blob store or imports
become unreadable. The browser never calls the API directly (SEC-15), which is why the API needs no
published port and sends no CORS headers.

Two volumes hold all state: **`relay-db`** (PostgreSQL) and **`relay-blobs`** (content-addressed
uploaded files). Section 6 covers backing them up — they must be backed up together.

Differences from the development stack: `RELAY_ENV=production`; credentials from
`.env.production` with no usable defaults; database and API not published; the
`./fixtures/ai-scripts` bind mount dropped, so no repository path is needed at runtime; restart
policies, memory/CPU limits, log rotation, and a worker stop grace period so an in-flight pipeline
run can finish.

---

## 3. Prerequisites

- Docker with Compose v2.24 or newer — the overlay uses the `!reset` and `!override` merge tags
  (verified on 2.35.1)
- A host with enough memory for the configured limits: roughly 6 GB with the defaults
- Somewhere to terminate TLS and apply access control in front of the web tier
- A backup destination that is not the deployment host

---

## 4. Configure

```bash
cp .env.production.example .env.production
```

Fill it in. `RELAY_DB_USER`, `RELAY_DB_PASSWORD` and `RELAY_DB_NAME` have no defaults — the overlay
refuses to render without them, naming the missing variable:

```
error while interpolating x-prod-env.RELAY_DATABASE_URL: required variable RELAY_DB_USER is
missing a value: set RELAY_DB_USER in .env.production
```

`.env.production` is git-ignored (`.env.*`, with `!.env.*.example` keeping the templates
committable). Prefer your platform's secret store over the file for `RELAY_DB_PASSWORD` and
`ANTHROPIC_API_KEY`; anything written into the file sits on disk in plain text.

Leave `RELAY_AI_PROVIDER=disabled` unless you have decided otherwise. Every workflow works without
it, which an end-to-end test asserts. Never deploy with `demo` or `scripted`: they replay authored
transcripts, and outside the demo their output could be mistaken for a model's reasoning.

Check the rendered configuration before starting anything:

```bash
make prod-config
```

---

## 5. Start it

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

`--wait` returns only when every healthcheck passes; `migrate` exiting 0 is part of that. Then
verify, from outside the containers where possible:

```bash
# Web tier
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/status      # expect 200

# API liveness and the schema, from inside the network
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5).status)"
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T api alembic current      # expect '<revision> (head)'

# Audit chains, any time
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps api relay verify-audit
```

A migration endpoint answering 401 is expected, not a fault — see §1.

---

## 6. Back it up

The database references blobs by content hash. A backup of one without the other is not a backup.

Blobs are append-only, so **dump the database first and archive the blob volume second**. That
order can only ever leave the archive holding blobs the dump does not reference yet, which is
harmless. The reverse order can leave the dump referencing blobs the archive does not contain,
which is data loss that only surfaces when someone opens a source row months later.

```bash
set -euo pipefail
source .env.production
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PROJECT=$(docker compose -f docker-compose.yml -f docker-compose.prod.yml config --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')

# 1. database
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T db pg_dump -U "$RELAY_DB_USER" -d "$RELAY_DB_NAME" --format=custom \
  > "relay-db-$STAMP.dump"

# 2. blobs
docker run --rm -v "${PROJECT}_relay-blobs:/blobs:ro" -v "$PWD:/out" alpine \
  tar czf "/out/relay-blobs-$STAMP.tgz" -C /blobs .
```

For a fully quiescent backup, stop the worker first
(`... stop worker`) so no import is mid-write, and start it again afterwards. The ordering above
exists so you do not have to.

Restore into an empty stack, in the same order:

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --wait db
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T db pg_restore -U "$RELAY_DB_USER" -d "$RELAY_DB_NAME" --clean --if-exists \
  < relay-db-<stamp>.dump
docker run --rm -v "${PROJECT}_relay-blobs:/blobs" -v "$PWD:/in" alpine \
  sh -c 'tar xzf /in/relay-blobs-<stamp>.tgz -C /blobs'
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --wait
```

Then run `relay verify-audit`: every hash chain must report `valid`. A chain that does not is the
signal that the restore was incomplete or that rows were altered.

---

## 7. Upgrade and roll back

```bash
git pull
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

`migrate` runs before `api` starts, so schema and code move together. Take a backup first, every
time — that is the rollback path for anything a migration changed.

Every Alembic migration has a downgrade, so `alembic downgrade -1` exists, but prefer restoring the
backup when a migration touched data. Downgrades are tested for schema reversibility, not for
recovering rows a migration transformed.

Rolling back code alone (no migration between the two revisions) is just rebuilding at the older
commit.

---

## 8. Operating notes

- **Logs** are JSON on stdout, rotated by Docker at 10 MB × 5 per container. They contain ids,
  counts and hashes — never row values, file contents, prompts or completions (SEC-20). Ship them
  with whatever collector you already run.
- **The worker is the throughput limit.** Imports, pipeline runs and investigations are jobs; one
  worker processes them in order. A run over a large migration takes minutes and holds the worker.
  `RELAY_WORKER_STOP_GRACE` (default 120s) is how long a deploy lets an in-flight job finish.
- **Upload limits** are `RELAY_MAX_UPLOAD_BYTES` (50 MiB), `RELAY_MAX_ROWS_PER_IMPORT` (500,000)
  and `RELAY_MAX_UPLOADS_PER_HOUR` (300 per person, SEC-17). Loading one migration uploads about 16
  files, so the default hourly budget is roughly 18 migrations per person per hour.
- **Health endpoints** are `/health` (liveness) and `/health/ready` (database reachable, schema at
  head). Point your orchestrator at `/health/ready`.
- **Database maintenance** goes through `docker compose exec db psql` or an SSH tunnel; the port is
  deliberately not published.

---

## 9. Known gaps

Blocking a real deployment:

- **Authentication does not exist** (§1). This is the one that matters.
- **SEC-25 is not implemented**: the application connects as a role with full DML rights. The
  append-only guarantees on `source_rows`, `quarantined_rows` and `audit_events` are enforced in
  application code and verified by the hash chains, not by database grants, and migrations run as
  the same role rather than a separate one. Deliberately deferred.

Worth knowing:

- **No horizontal scaling story.** One worker, one API, single host, local volumes. Nothing forbids
  more, but nothing has been measured beyond `make pipeline-perf` on one node.
- **No TLS in the stack.** The web tier is plain HTTP on loopback; termination is the reverse
  proxy's job.
- **No secret rotation procedure.** Changing `RELAY_DB_PASSWORD` after the volume exists requires
  `ALTER ROLE` inside PostgreSQL; the environment variable alone does not change it.
- **Backups are manual.** Section 6 is a procedure, not a scheduled job.
