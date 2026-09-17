# Relay

**Migration operations for ERP implementations: prove the data is right before go-live.**

> **Status: milestone M0 (repository foundation) implemented.** The backend and web foundations, financial primitives, database tooling, Docker Compose stack and CI exist. **None of Relay's product features exist yet.** That includes imports, mappings, validation, reconciliation, issues, approvals, readiness, audit and AI. See [docs/progress.md](docs/progress.md) and [docs/implementation-plan.md](docs/implementation-plan.md).

---

## What Relay will be

Moving a company onto a new ERP isn't just importing CSVs. Legacy exports quietly drop inactive records. Mappings put contra-accounts in the wrong place. Old books carry duplicate vendors and double payments. Fixes get made in spreadsheets nobody can audit. And the go-live decision often comes down to "looks good" in a meeting.

Relay is designed as an internal command center for implementation teams:

- **Import** legacy ledgers, subledgers, control reports and bank data. Raw rows stay immutable, and every row keeps its file and line lineage.
- **Map** source fields and legacy accounts onto a canonical model and a target chart of accounts, using versioned, approved mappings.
- **Validate** with a deterministic, extensible rules engine.
- **Reconcile** extracted detail against independent control reports (trial balance, AR/AP agings, bank statement), and source against staged data. Every discrepancy drills down to the records behind it.
- **Govern** fixes as change requests with segregation of duties and an append-only, hash-chained audit log.
- **Investigate** with an AI agent that has read-only tools and must cite verifiable evidence.
- **Decide** go-live with deterministic readiness gates bound to a reproducible pipeline run.

The planned demo is **Brightwater Provisions, Inc.**, a fictional food distributor whose data includes 13 realistic seeded defects. See [docs/demo-scenario.md](docs/demo-scenario.md).

## What exists today (M0)

| Area | Contents |
|---|---|
| `backend/` | FastAPI app with `GET /health` and `GET /health/ready` (database reachable and migrations at head); settings validation; structured JSON logging; problem+json errors; SQLAlchemy and Alembic (empty baseline revision) |
| `backend/src/relay/core/` | Financial primitives: `Money` (Decimal-only, explicit currency, no silent rounding), FX conversion, source amount parsing, debit/credit sign convention; business dates vs. UTC system timestamps; UUIDv7; canonical hashing; database column types that enforce these invariants |
| `web/` | Next.js + TypeScript (strict) development page that shows backend and database health |
| `docker-compose.yml` | PostgreSQL 16, a one-shot migration job, API, web |
| `.github/workflows/ci.yml` | Runs `make check`, then builds and smoke-tests the stack |

Design decisions for money handling are in [docs/decisions/0001-money-representation.md](docs/decisions/0001-money-representation.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.12 or newer. It installs Python 3.12 if needed.
- Node.js 24 with npm.
- Docker with Compose v2.
- GNU Make, or the BSD make that ships with macOS.

## Setup

```bash
make setup
```

This installs backend dependencies from `backend/uv.lock` and web dependencies from `web/package-lock.json`.

Optional: to change host ports or the local database password, copy `.env.example` to `.env` and edit it. By default the database listens on `127.0.0.1:55432`, the API on `127.0.0.1:8000` and the web app on `127.0.0.1:3000`.

## Run

Full stack in Docker (db, migrations, API, web), then verify end to end:

```bash
make up
```

```bash
make smoke
```

Open http://127.0.0.1:3000 to see the status page. The API docs are at http://127.0.0.1:8000/api/v1/docs.

To stop the stack (the database volume is kept):

```bash
make down
```

Alternatively, run the API and web app on the host with auto-reload, using Compose only for PostgreSQL:

```bash
make dev
```

## Verify

```bash
make check
```

`make check` runs, in order:
- format check (ruff, prettier)
- lint (ruff, import-linter, eslint)
- type checks (mypy `--strict`, `tsc`)
- backend unit and property tests, web unit tests
- integration tests against PostgreSQL (started automatically)
- Next.js production build
- Docker Compose config validation

Individual steps: `make fmt-check`, `make lint`, `make typecheck`, `make test`, `make test-integration`, `make build-web`, `make compose-config`.

## Database

```bash
make db-migrate
```

Other database targets:
- `make db-current` shows the current revision.
- `make db-downgrade` rolls back one revision.
- `make db-revision m="message"` creates a new revision, auto-formatted with ruff.

Integration tests use a separate `relay_test` database, which is dropped and recreated on each run.

## All commands

```bash
make help
```

## Documentation

| Doc | Contents |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for contributors and AI coding sessions |
| [docs/progress.md](docs/progress.md) | What has been built, and deviations from the plan |
| [docs/product-spec.md](docs/product-spec.md) | Problem, critique of the original brief, MVP scope, UX |
| [docs/architecture.md](docs/architecture.md) | System design, modules, pipeline, API, jobs |
| [docs/data-model.md](docs/data-model.md) | Domain model and schema |
| [docs/validation-and-reconciliation.md](docs/validation-and-reconciliation.md) | Rules engine, reconciliations, entity resolution |
| [docs/governance.md](docs/governance.md) | Issues, change requests, approvals, audit, readiness gates |
| [docs/ai-safety.md](docs/ai-safety.md) | AI tools, verification, threat model, evals |
| [docs/demo-scenario.md](docs/demo-scenario.md) | Brightwater scenario and expected results |
| [docs/testing.md](docs/testing.md) | Test strategy |
| [docs/security-and-correctness.md](docs/security-and-correctness.md) | Requirement IDs for correctness and security |
| [docs/implementation-plan.md](docs/implementation-plan.md) | Milestones and acceptance criteria |
| [docs/decisions/](docs/decisions/) | Architecture decision records |
