# Relay — Architecture

Status: **Target design. M0 (repository foundation) is implemented; everything else is planned.** See [progress.md](progress.md) for what exists. Update this document when implementation diverges, and record why.

Related: [data-model.md](data-model.md) · [validation-and-reconciliation.md](validation-and-reconciliation.md) · [governance.md](governance.md) · [ai-safety.md](ai-safety.md) · [security-and-correctness.md](security-and-correctness.md)

---

## 1. Architectural principles

1. **Deterministic core, AI at the edge.** Normalization, entity candidates, validation, reconciliation and readiness are pure, deterministic functions. AI reads their outputs through read-only tools. Removing the AI provider removes no correctness.
2. **Immutable inputs, recomputable outputs.** Imported rows are never modified. Every staged record, exception, reconciliation and gate result is a function of `(active imports, approved overlays, policy, rule set version)`. That tuple is hashed into an **input fingerprint**.
3. **Every mutation is a governed event.** State changes that affect financial outcomes happen only by applying an approved change request. Every mutation writes an audit event in the same database transaction.
4. **Lineage everywhere.** Every canonical record points to the source row(s) it came from; every exception points to canonical records; every issue points to exceptions; every gate points to evidence.
5. **Modular monolith.** One backend deployable (API + worker entry points), strong internal module boundaries enforced by import rules. No microservices, no message broker, no Redis.
6. **Boring, explicit money.** `Decimal` in Python, `NUMERIC(20,4)` in Postgres, strings over JSON, no floats anywhere in the financial path.
7. **Typed boundaries.** Pydantic at the API and AI boundaries; SQLAlchemy 2.0 typed models; OpenAPI-generated TypeScript client for the frontend.

---

## 2. System overview

```
┌────────────────────────── Browser ──────────────────────────┐
│ Next.js (App Router) · TypeScript · Tailwind · TanStack      │
│ Query/Table · generated OpenAPI client                       │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTPS JSON (/api/v1), problem+json errors
┌───────────────────────────────▼─────────────────────────────┐
│ relay-api (FastAPI, sync SQLAlchemy, Pydantic v2)            │
│   routers → services → domain (pure) / repositories          │
└───────┬──────────────────────────────┬──────────────────────┘
        │ SQL                          │ enqueue (jobs table)
┌───────▼────────┐            ┌────────▼─────────────────────┐
│ PostgreSQL 16  │◄───────────│ relay-worker (same codebase) │
│ app data,      │  SQL       │ parse/profile imports,       │
│ staged runs,   │            │ pipeline runs, investigations│
│ jobs, audit    │            └────────┬─────────────────────┘
└────────────────┘                     │ HTTPS (optional)
        ▲                     ┌────────▼─────────┐
        │ files (content-     │ LLM provider     │
        │ addressed, local    │ (Anthropic, …)   │
        │ volume in MVP)      └──────────────────┘
┌───────┴────────┐
│ File storage   │
└────────────────┘
```

Docker Compose services: `db` (postgres:16), `migrate` (one-shot `alembic upgrade head`), `api`, `web` — implemented in M0. The `worker` service is added in M3 together with the jobs table; until then there is deliberately no worker process.

### 2.1 Why these choices

| Decision | Choice | Rejected alternative | Reason |
|---|---|---|---|
| Backend language | Python 3.12 | Node | Decimal ergonomics, data tooling, strong typing via mypy/pydantic |
| Web framework | FastAPI | Django | OpenAPI-first typed contracts; lighter; Django admin not needed |
| DB access | SQLAlchemy 2.0 **sync** + psycopg 3 | async SQLAlchemy | Pipeline is CPU/DB-bound batch work; sync is simpler to reason about, test and transact. FastAPI runs sync handlers in a threadpool. |
| Migrations | Alembic | — | Standard |
| Background work | **Postgres job table** + worker using `FOR UPDATE SKIP LOCKED` | Celery/RQ + Redis; FastAPI BackgroundTasks | Imports and pipeline runs take seconds–a minute: too long for a request, too small to justify a broker. BackgroundTasks die with the process and are untestable. A jobs table is transactional with the data it describes. |
| File storage | Local volume, content-addressed, behind a `BlobStore` interface | S3 | S3 adapter is post-MVP; interface exists from day one. |
| Rules execution | In-memory Python over a loaded run snapshot | SQL pushdown | Pure functions with fixture tests; adequate for ≤ 250k lines. `RuleContext` abstracts data access so SQL-backed rules can be added. |
| Frontend | Next.js + TanStack Query/Table + Radix-based components (shadcn/ui) | SPA with Vite | Routing/layouts for a many-page ops tool; server components not relied on for data (API is the source of truth). |
| JS package manager | **npm** with `package-lock.json` (M0) | pnpm | Ships with Node.js, so the toolchain needs nothing extra; pnpm via corepack was unreliable on the development machine. Revisit only with a concrete need. |
| API client | `openapi-typescript` + `openapi-fetch` | Hand-written types | Contract drift becomes a type error in CI. |
| AI | Provider protocol, tool registry, structured outputs | Framework (LangChain etc.) | Small, auditable surface; tool permissions are ours, not a framework's. |
| Identity (MVP) | Seeded users, dev identity header, role checks in a single dependency | Real auth | Real auth is post-MVP; all authorization flows through `current_actor()` so it can be swapped. |

---

## 3. Backend module structure

Each module owns its tables, schemas and services. Cross-module calls go through the other module's **service** or **read model**, never its tables.

```
backend/src/relay/
├── core/               # no dependencies on other relay modules
│   ├── config.py       # pydantic-settings
│   ├── db.py           # engine, session factory, unit-of-work
│   ├── errors.py       # RelayError hierarchy → problem+json
│   ├── logging.py      # structlog JSON, request/job correlation ids
│   ├── currency.py     # ISO 4217 registry and minor units                      (M0)
│   ├── money.py        # Money, amount validation, FX conversion, parsing       (M0)
│   ├── dates.py        # business dates, explicit formats, fiscal periods        (M0)
│   ├── timestamps.py   # aware-UTC system timestamps, RFC 3339                   (M0)
│   ├── db_types.py     # SQLAlchemy column types enforcing the above             (M0)
│   ├── clock.py        # injectable Clock (frozen in tests)                      (M0)
│   ├── hashing.py      # canonical JSON + sha256 fingerprints                    (M0)
│   └── ids.py          # UUIDv7 generation                                       (M0)
├── identity/           # users, roles, current_actor dependency, dev identity
├── workspace/          # companies, migrations, conversion plans, source systems, datasets
├── ingestion/          # BlobStore, CSV reader, import service, connector protocol
├── profiling/          # profilers → DatasetProfile
├── canonical/          # Canonical Accounting Model types, natural keys, RecordRef
├── mapping/            # column/account mapping sets, transforms, deterministic suggesters
├── entity_resolution/  # blocking, features, scoring, decisions applier
├── validation/         # engine, registry, RuleContext, rules/*.py
├── reconciliation/     # engine, definitions/*.py, explainers/*.py, drilldown
├── pipeline/           # orchestrator, stages, input fingerprint, staging writer, run diff
├── issues/             # fingerprints → issues, lifecycle, comments, exposure
├── changes/            # change requests, approval policy, appliers per kind
├── readiness/          # gate registry, evaluation, waivers, sign-off binding
├── audit/              # event writer, hash chain, verification, query
├── ai/
│   ├── providers/      # LLMProvider protocol; anthropic.py, scripted.py, disabled.py
│   ├── tools/          # read-only tool definitions over read models
│   ├── investigator/   # agent loop, budgets, transcript persistence
│   ├── suggestions/    # column/account mapping suggestion prompts
│   ├── verification.py # finding schema + provenance verification
│   └── prompts/        # versioned prompt templates
├── jobs/               # jobs table, enqueue, worker loop, retry policy
├── demo/               # Brightwater scenario generator, manifest, seed command
├── cli.py              # `relay` CLI (typer): seed, run-pipeline, verify-audit, generate-demo
└── api/
    ├── app.py          # app factory                                             (M0)
    ├── middleware.py   # request id, request logging, security headers           (M0)
    ├── problems.py     # RFC 9457 problem+json exception handlers                (M0)
    ├── deps.py         # session, current_actor, pagination
    └── routers/        # one router per module; health.py                        (M0)
```

Within a module:

```
module/
├── models.py       # SQLAlchemy tables (only this module writes them)
├── schemas.py      # Pydantic DTOs (API and inter-module)
├── domain.py       # pure logic: no DB, no I/O, no clock reads
├── service.py      # transactions, orchestration, audit writes
└── read_model.py   # query-side functions used by API and AI tools
```

### 3.1 Enforced dependency rules (import-linter)

M0 enforces `core` as the bottom layer (`relay.api` → `relay.core`). The remaining contracts are added in the milestone that creates each module.

- `core` imports nothing from `relay.*`.
- `canonical` imports only `core`.
- `validation.domain`, `reconciliation.domain`, `entity_resolution.domain`, `readiness.domain` import only `core` and `canonical`.
- `ai` may import `*.read_model` and `*.schemas` only — **never** `*.service` or `*.models`. This is the structural guarantee that AI code has no write path.
- `api.routers` import services and read models, never `models` directly.

---

## 4. Pipeline

A pipeline run is the deterministic heart of Relay.

### 4.1 Input fingerprint

```
fingerprint = sha256(canonical_json({
  "migration_id":        ...,
  "conversion_plan":     {opening_balance_date, history_start, cutover_date, ...},
  "active_imports":      {dataset_id: import_sha256, ...},
  "column_mapping_sets": {dataset_id: version, ...},
  "account_mapping_set": version,
  "overrides":           [sorted override ids+versions],
  "entity_decisions":    [sorted decision ids+versions],
  "dispositions":        [sorted ids+versions],
  "policy_version":      n,
  "ruleset_version":     sha256(sorted rule_id@version),
  "reconciliation_set":  sha256(sorted recon_id@version),
  "gate_set":            sha256(sorted gate_id@version),
  "engine_version":      relay package version
}))
```

- A migration's **current fingerprint** is computed on demand from its live configuration.
- A run is **current** iff its fingerprint equals the current fingerprint. Otherwise all its results are shown as stale.
- Triggering a run whose fingerprint equals an existing successful run returns that run (idempotent).
- Applying an approved change request auto-enqueues a run (deduplicated by fingerprint).

### 4.2 Stages

| # | Stage | Input | Output | Pure core |
|---|---|---|---|---|
| 1 | **Load** | active imports' source rows | in-memory source tables | — |
| 2 | **Normalize** | source rows + column mapping sets + record overrides | canonical records w/ lineage; `NORM.*` exceptions | `mapping.domain.apply_column_mapping` |
| 3 | **Map accounts** | canonical GL/TB + account mapping set | target account on each line/balance; unmapped buckets | `mapping.domain.apply_account_mapping` |
| 4 | **Resolve entities** | canonical parties + entity decisions | party clusters (canonical party ids), new candidates | `entity_resolution.domain` |
| 5 | **Validate** | run snapshot | exceptions | `validation.domain` |
| 6 | **Reconcile** | run snapshot | reconciliation results, explained items, discrepancy exceptions | `reconciliation.domain` |
| 7 | **Persist** | all of the above | staged tables, exceptions, results (bulk insert via COPY) | — |
| 8 | **Issues** | run exceptions + existing issues + dispositions | issue upserts, verification, reopen | `issues.domain` |
| 9 | **Readiness** | run + issues + CR state + policy | readiness evaluation | `readiness.domain` |

Stages 2–6 and 8–9's decision logic are pure functions over a `RunSnapshot`; the orchestrator does I/O. A run executes in one worker job. Stages 1–7 write inside a run-scoped transaction; if any stage fails the run is marked `failed` with a structured error and no partial results are visible.

### 4.3 Run diff

`GET /pipeline-runs/{a}/diff/{b}` reports: fingerprint components that changed, exceptions added/removed per rule, reconciliation results whose status changed, gates that changed. The UI uses it for "What did this approval change?".

### 4.4 Retention

Staged records are stored per run. Keep: the latest 5 runs, any run referenced by a sign-off, a readiness evaluation shown in audit, or a finding. Older runs keep summary rows (exceptions counts, recon results, gate results) but drop staged records. Pruning is itself audited.

---

## 5. Ingestion

### 5.1 Import flow

```
POST /datasets/{id}/imports (multipart)
  → stream to temp file, enforce max bytes, compute sha256 while streaming
  → if (dataset_id, sha256) exists: 200 with existing import (idempotent)
  → BlobStore.put(sha256) (content-addressed; filename never used as a path)
  → insert import(status=pending), enqueue job parse_import
  → 202 {import}
worker parse_import:
  → sniff encoding (BOM, strict UTF-8, fallback cp1252 — recorded), delimiter, header row
  → stream rows; enforce max rows/columns/field length
  → malformed rows (field count mismatch, unterminated quote) quarantined with physical line span and raw text
  → COPY source_rows (row_number, physical_line_start/end, raw jsonb of strings, row_hash)
  → status=parsed; enqueue profile_import
  → on success, dataset.active_import_id = this import; previous import status=superseded (audited)
```

### 5.2 Connector abstraction (designed now, implemented later)

```python
class SourceConnector(Protocol):
    kind: str                                  # "csv_upload", "netsuite", ...
    def list_extractable(self) -> list[ExtractableDataset]: ...
    def extract(self, dataset_type: DatasetType, params: ExtractParams) -> Iterator[RawRecord]: ...
```

CSV upload is the MVP connector. A connector produces the same `source_rows` shape, so everything downstream is connector-agnostic.

---

## 6. API design

### 6.1 Conventions

- Base path `/api/v1`. JSON. OpenAPI generated from FastAPI and committed to `web/src/lib/api/openapi.json`; CI fails on drift.
- **Money** is a string decimal (`"12450.00"`) plus a `currency` field. **Business dates** are `YYYY-MM-DD`. **Timestamps** are RFC 3339 UTC.
- **IDs** are UUIDv7 strings. Natural keys are separate fields.
- **Errors**: RFC 9457 `application/problem+json` with a stable `code` (`import.duplicate_header`, `change_request.stale`, `approval.segregation_of_duties`, …), `detail`, and `errors[]` for field validation.
- **Pagination**: cursor-based (`?cursor=&limit=`, max 500). Responses include `next_cursor`.
- **Concurrency**: mutable resources expose `version`; updates require `If-Match`; mismatch → `412` with `code=concurrency.version_mismatch`.
- **Idempotency**: `Idempotency-Key` header accepted on POSTs that create change requests, approvals, pipeline runs and investigations; replays return the original response.
- **Long-running work** returns `202` with a resource that has a `status`; the client polls the resource (no websockets in MVP).
- **Authorization** in one place: every router depends on `current_actor()` and a `require(permission)` guard; policy checks for approvals live in `changes.service`.

### 6.2 Endpoint map

```
Identity
  GET  /me
  GET  /dev/users                                   (local/test only)

Portfolio & workspace
  GET  /migrations                                  portfolio summary rows
  POST /migrations
  GET  /migrations/{mid}
  GET  /migrations/{mid}/overview                   readiness banner, blockers, exposure, queue, stages
  GET  /migrations/{mid}/conversion-plan            PUT → creates policy/plan change request
  GET  /migrations/{mid}/source-systems             POST
  GET  /migrations/{mid}/datasets                   POST

Ingestion & profiling
  POST /datasets/{did}/imports                      multipart upload (202)
  GET  /datasets/{did}/imports
  GET  /imports/{iid}
  GET  /imports/{iid}/rows?cursor=                  raw rows
  GET  /imports/{iid}/quarantine                    malformed rows
  GET  /imports/{iid}/profile

Mapping
  GET  /datasets/{did}/column-mapping-sets          POST (new draft from active/suggestions)
  GET  /column-mapping-sets/{id}                    PUT (draft only, If-Match)
  POST /column-mapping-sets/{id}/suggestions        deterministic + optional AI
  POST /column-mapping-sets/{id}/preview            normalize first N rows, show errors
  GET  /migrations/{mid}/account-mapping-sets       POST
  GET  /account-mapping-sets/{id}                   PUT (draft only)
  POST /account-mapping-sets/{id}/suggestions
  (submitting a draft = POST /change-requests with kind column_mapping_set/account_mapping_set)

Pipeline
  POST /migrations/{mid}/pipeline-runs              202; idempotent on fingerprint
  GET  /migrations/{mid}/pipeline-runs
  GET  /pipeline-runs/{rid}
  GET  /pipeline-runs/{rid}/diff/{other_rid}
  GET  /migrations/{mid}/fingerprint                current fingerprint + components

Validation
  GET  /pipeline-runs/{rid}/rules                   per-rule status + counts
  GET  /pipeline-runs/{rid}/exceptions?rule_id=&severity=&cursor=
  GET  /rules                                       rule catalog with descriptions/params

Reconciliation
  GET  /pipeline-runs/{rid}/reconciliations
  GET  /reconciliation-results/{id}                 summary per grain key
  GET  /reconciliation-results/{id}/lines?status=&cursor=
  GET  /reconciliation-lines/{id}/drilldown         both sides' records, set diff, explainers

Records
  GET  /records/{ref}                               canonical record + source row + lineage + overlays + related issues

Entities
  GET  /migrations/{mid}/entity-candidates?party_type=&status=
  GET  /entity-candidates/{id}                      features + evidence

Issues
  GET  /migrations/{mid}/issues?status=&severity=&nature=&owner=&gate=&cursor=
  POST /migrations/{mid}/issues                     manual issue
  GET  /issues/{id}                                 incl. exceptions in current run, related issues
  PATCH /issues/{id}                                owner, priority, workflow status (limited transitions)
  GET  /issues/{id}/history
  GET  /issues/{id}/comments                        POST

Change requests & approvals
  GET  /migrations/{mid}/change-requests?status=&awaiting=me
  POST /migrations/{mid}/change-requests            draft
  GET  /change-requests/{id}                        payload, before/after, evidence, required approvals, staleness
  PUT  /change-requests/{id}                        draft only
  POST /change-requests/{id}/submit
  POST /change-requests/{id}/approve                {comment}
  POST /change-requests/{id}/reject                 {comment}
  POST /change-requests/{id}/withdraw

Readiness
  GET  /migrations/{mid}/readiness                  latest evaluation for current run (or stale marker)
  GET  /readiness-evaluations/{id}
  (waivers and sign-off are change requests)

Audit
  GET  /migrations/{mid}/audit-events?actor=&action=&entity_type=&entity_id=&from=&to=&cursor=
  GET  /migrations/{mid}/audit-events/verify        hash-chain verification result

AI
  GET  /ai/status                                   provider configured? enabled for migration?
  POST /migrations/{mid}/investigations             {issue_id?, question} (202)
  GET  /investigations/{id}                         status, steps (tool calls), findings
  POST /findings/{id}/accept | /dismiss             {comment}
  POST /findings/{id}/draft-change-request          creates a draft CR owned by the calling user
```

---

## 7. Jobs

```
jobs(id, kind, payload jsonb, dedupe_key unique nullable, status queued|running|succeeded|failed|dead,
     attempts, max_attempts, run_after timestamptz, locked_by, locked_at, heartbeat_at, last_error jsonb,
     created_at, finished_at)
```

- Kinds: `parse_import`, `profile_import`, `run_pipeline`, `run_investigation`, `prune_runs`.
- Worker: `SELECT … WHERE status='queued' AND run_after<=now() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`.
- Heartbeats; a job with a stale heartbeat is re-queued (attempts++). Handlers must be idempotent: `run_pipeline` is keyed by fingerprint, `parse_import` by import id + status check.
- `run_pipeline` jobs for the same migration are serialized with a Postgres advisory lock on the migration id.
- Retries only for transient errors (DB connection, provider 5xx/429 with backoff); domain errors fail immediately.

---

## 8. Frontend structure

```
web/
├── src/app/
│   ├── (shell)/layout.tsx                     # top bar, user switcher (dev), migration nav
│   ├── portfolio/page.tsx
│   └── migrations/[mid]/
│       ├── overview/  data/  mappings/  runs/  validation/  reconciliation/
│       ├── entities/  issues/  approvals/  readiness/  audit/  settings/
├── src/components/
│   ├── money.tsx  business-date.tsx  status-chip.tsx  record-ref.tsx
│   ├── record-inspector/   data-table/   evidence/   ai-finding/
├── src/lib/api/        # openapi.json, generated schema.d.ts, client.ts
├── src/lib/format/     # money/date formatting from strings (no arithmetic)
└── tests/  unit/  e2e/
```

Frontend rules: no money arithmetic in TypeScript; server-state only via TanStack Query; URL holds filters so every view is linkable; tables are virtualized for large exception sets.

---

## 9. Observability

- structlog JSON logs with `request_id`, `job_id`, `run_id`, `migration_id`, `actor_id`.
- **Never log** raw row values, file contents, LLM prompts or completions. Log counts, ids and hashes.
- Pipeline stage timings recorded on the run row (`stage_timings jsonb`) and shown in Runs UI.
- Investigation transcripts are stored in the DB (access-controlled), not logs.
- `GET /health` (process liveness, no database) and `GET /health/ready` (database reachable and schema at the Alembic head; 503 otherwise). Implemented in M0. "Ready" is the HTTP sense, unrelated to launch readiness.

---

## 10. Configuration

`pydantic-settings`, env-prefixed `RELAY_`. M0 implements `RELAY_ENV`, `RELAY_DATABASE_URL`, `RELAY_DB_POOL_SIZE`, `RELAY_DB_CONNECT_TIMEOUT_SECONDS`, `RELAY_LOG_LEVEL` and `RELAY_LOG_FORMAT`; the rest arrive with the code that reads them. Planned variables:

| Variable | Default | Notes |
|---|---|---|
| `RELAY_ENV` | `local` | `local`, `test`, `production`. Dev identity refused unless local/test. |
| `RELAY_DATABASE_URL` | — | required |
| `RELAY_STORAGE_DIR` | `/data/blobs` | BlobStore root |
| `RELAY_MAX_UPLOAD_BYTES` | `52428800` | 50 MB |
| `RELAY_MAX_ROWS_PER_IMPORT` | `500000` | |
| `RELAY_MAX_FIELD_CHARS` | `10000` | |
| `RELAY_AI_PROVIDER` | `disabled` | `disabled`, `anthropic`, `scripted` |
| `RELAY_AI_MODEL` | — | e.g. a current Claude model id; verify at implementation time |
| `ANTHROPIC_API_KEY` | — | only read by the anthropic provider |
| `RELAY_AI_MAX_TOOL_CALLS` | `15` | per investigation |
| `RELAY_AI_TIMEOUT_SECONDS` | `120` | per investigation |
| `RELAY_LOG_LEVEL` | `INFO` | |

---

## 11. Key decisions log

| ID | Decision | Status |
|---|---|---|
| D-01 | Raw rows immutable; all corrections are approved overlays; staged data recomputed per run | Accepted |
| D-02 | Control reports (TB, agings, bank) are first-class datasets | Accepted |
| D-03 | Exceptions (per run) vs. issues (fingerprinted, cross-run) vs. findings (AI) | Accepted |
| D-04 | Postgres job table instead of broker | Accepted |
| D-05 | Sync SQLAlchemy | Accepted |
| D-06 | Rules in Python over in-memory snapshot, behind `RuleContext` | Accepted; revisit past 250k lines |
| D-07 | AI package may only import read models; tool DB sessions are `READ ONLY` transactions | Accepted |
| D-08 | Readiness = gates bound to run fingerprint; no score | Accepted |
| D-09 | Business dates as `DATE`; periods derived from dates by fiscal calendar; the target ERP is assumed to derive period from date | Accepted — assumption |
| D-10 | Many-to-one account mapping only in MVP | Accepted |
| D-11 | Signed amounts: debit positive, credit negative, functional currency stored alongside transaction currency | Accepted |
| D-12 | Money representation details (canonical scale, sub-minor precision, FX rounding, equality across currencies): see [decisions/0001-money-representation.md](decisions/0001-money-representation.md) | Accepted (M0) |
| D-13 | npm instead of pnpm for the web app | Accepted (M0) |
| D-14 | Web reads the API server-side only (`RELAY_API_URL`, not exposed to the browser); no CORS configured until the browser needs to call the API | Accepted (M0) |
