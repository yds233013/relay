# Relay

**Migration operations for ERP implementations: prove the data is right before go-live.**

> **Status:** milestones M0 to M7 are implemented: foundation; canonical model and the Brightwater demo scenario; the deterministic validation and reconciliation engine; persistence, imports, pipeline runs, audit and the read API; the web evidence workspace; governed mappings, change requests, approvals and record overrides; issue workflow, entity decisions, dispositions, re-imports and new migrations; readiness waivers and sign-off. See [docs/progress.md](docs/progress.md) for exactly what exists.

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

## Brightwater demo data (M1)

A deterministic, fictional migration with clean books, independent control reports, 13 seeded issues and 5 legitimate look-alike patterns. Layout:

| Path | What | Who may read it |
|---|---|---|
| `fixtures/demo/brightwater/` | Source-style files Relay ingests: LedgerPro exports (Windows-1252), First Cascade Bank statement and FX rates, target chart and account mapping, `migration.json`, `SHA256SUMS` | Anyone, including runtime code |
| `evaluation/brightwater/golden_manifest.toml` | Hand-authored ground truth: what is wrong, expected reconciliation discrepancies and issues, and what must stay silent | Tests and evaluation tooling only |
| `backend/src/relay_scenarios/` | Generator (clean books, controls, exports, injectors) | Tests and demo tooling only |
| `backend/src/relay_evaluation/` | Manifest loader, reference oracle, verifier | Tests and evaluation tooling only |

Import-linter contracts and tests prevent runtime code (`relay`) from importing the generator or the evaluation truth. They also prevent runtime code from containing scenario-specific identifiers or amounts.

Regenerate the fixtures and print a summary (no answers):

```bash
make demo-data
```

Check that the committed fixtures are byte-identical to a fresh generation:

```bash
make demo-check
```

Evaluation only (reveals expected answers):

```bash
make demo-verify
```

```bash
make demo-manifest
```

Generation is deterministic: every value comes from named random streams derived from seed `20260630`, using integer arithmetic only.

## Deterministic engine (M2)

A pure Python engine (no database, clock or network) reads the source files with line-level lineage, quarantines malformed rows, applies an approved column mapping set, and runs 32 validation rules, reconciliations R1–R6, duplicate-party candidates and readiness gates G1–G12. Every result is bound to an input fingerprint.

```bash
make engine-run
```

On Brightwater Run #1 the engine's findings and reconciliation discrepancies match the hand-authored golden manifest exactly. The documented resolutions reach "all gates pass except sign-off". The engine has no Brightwater-specific code: the same rules give zero findings on a synthetic clean company, and each rule is tested there with a planted defect and a legitimate look-alike.

## Persistence, pipeline runs and audit (M3)

Imports keep every raw row immutable, with file and line lineage. Pipeline runs are idempotent on an input fingerprint and persist staged records, findings, reconciliations and readiness in one transaction. Every governed change writes a hash-chained audit event in the same transaction.

Start the stack, load Brightwater at the "day 9" state (imports, approved column mappings through change requests, Run #1), then verify the audit chains:

```bash
make up
```

```bash
make demo-seed
```

```bash
make verify-audit
```

Open http://127.0.0.1:3000, choose a user, and follow a blocker from the Overview to the reconciliation drill-down and the exact source row behind it. End-to-end tests for that path:

```bash
make test-e2e
```

The API documents itself at http://127.0.0.1:8000/api/v1/docs. Development identity: send `X-Relay-User: maya.chen@relay.example` (seeded users only; refused outside local and test).

Measure throughput on a synthetic clean 250,000-line migration:

```bash
make engine-perf
```

Measured once on an Apple M2 (16 GB): 34.6 s, about 1 GB peak memory. See [docs/progress.md](docs/progress.md) for details and [docs/decisions/0003-deterministic-engine.md](docs/decisions/0003-deterministic-engine.md) for design decisions.

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

Open http://127.0.0.1:3000 for the app (run `make demo-seed` for data) or http://127.0.0.1:3000/status for the health page. The API docs are at http://127.0.0.1:8000/api/v1/docs.

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
- lint (ruff, import-linter contracts, eslint)
- type checks (mypy `--strict`, `tsc`)
- backend unit, property and scenario tests, web unit tests
- Brightwater fixture determinism and golden-manifest verification
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
| [docs/progress.md](docs/progress.md) | What has been built, measured results, deviations from the plan |
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
