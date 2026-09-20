# CLAUDE.md — Working on Relay

Read this before any change. Keep it accurate: when a command, convention, or boundary changes, update this file in the same change.

---

## What Relay is

Relay is an implementation and migration operations system for ERP deployments. It imports legacy accounting data (GL, trial balances, customers, vendors, invoices, bills, payments, agings, bank transactions), maps it onto a canonical model and a target chart of accounts, **deterministically** validates and reconciles it against independent control reports, turns failures into governed issues, routes fixes through approved change requests, and decides go-live readiness with explicit gates. An AI investigator helps operators understand discrepancies using read-only tools and must cite verifiable evidence.

It is a portfolio project built to production standards. The fictional demo customer is **Brightwater Provisions, Inc.**

Canonical documents (read the relevant one before working in an area):

| Area | Doc |
|---|---|
| Scope, MVP, UX | `docs/product-spec.md` |
| System design, modules, API, jobs | `docs/architecture.md` |
| Tables, types, conventions | `docs/data-model.md` |
| Rules, reconciliations, entity resolution | `docs/validation-and-reconciliation.md` |
| Issues, change requests, approvals, audit, readiness gates | `docs/governance.md` |
| AI boundaries, tools, verification, evals | `docs/ai-safety.md` |
| Demo data and expected results | `docs/demo-scenario.md` |
| Test layers and commands | `docs/testing.md` |
| Deployment overlay, backups, why production serves no users | `docs/deployment.md` |
| Public demo mode: anonymous access, the demo policy, zero-cost AI | `docs/public-demo.md` |
| Security & correctness requirement IDs | `docs/security-and-correctness.md` |
| Milestones and acceptance criteria | `docs/implementation-plan.md` |
| What has actually been built | `docs/progress.md` (created in M0) |
| Requirement-by-requirement verification | `docs/traceability.md` |
| Independent review passes and what they changed | `docs/review-findings.md` |

---

## Current state

Implemented milestones (see `docs/progress.md` for status, commits and verification):
- **M0**: backend and web foundations, financial/date/timestamp primitives (`backend/src/relay/core/`), Alembic baseline, Docker Compose, Makefile, CI.
- **M1**: canonical accounting model (`relay.canonical`), deterministic Brightwater generator (`relay_scenarios`), source fixtures (`fixtures/demo/brightwater/`), hand-authored golden manifest (`evaluation/brightwater/`), evaluation verifier (`relay_evaluation`).
- **M2**: pure deterministic engine: CSV ingestion with quarantine (`relay.ingestion`), declarative column mapping (`relay.mapping`), normalization, rules, reconciliations R1–R6, entity candidates, readiness gates and fingerprints (`relay.engine`); `relay engine run`; engine-vs-manifest comparison (`relay_evaluation.brightwater.engine_compare`); synthetic volume generator (`relay_scenarios.volume`). Decisions: `docs/decisions/0003-deterministic-engine.md`.

- **M3**: persistence (Alembic `0002_persistence`), imports with append-only source rows, column mapping sets, change request core, pipeline runs persisted in one transaction, issue synchronization, hash-chained audit, PostgreSQL job queue and `relay worker`, read API (dev identity), `relay-demo seed`. Decisions: `docs/decisions/0004-persistence-and-pipeline.md`.

- **M4**: web evidence workspace (Next.js Server Components over the API): portfolio, overview with evidence links, data, runs with diff, validation, reconciliation with drill-down, record inspector, issues, readiness, audit log; Playwright E2E-1 with axe. Decisions: `docs/decisions/0005-web-evidence-workspace.md`.
- **M5**: governed changes: account mapping sets (replace the mapping file's pairs in runs), column mapping suggestions and preview, change request kinds `column_mapping_set`, `account_mapping_set`, `record_override`, `policy_change`, `revert` with SoD, staleness and atomic apply plus run request; Mappings, Approvals, change request, Overrides pages; E2E-2. Decisions: `docs/decisions/0006-governed-changes.md`. E2E tests change demo state: `make demo-reset` before rerunning.
- **M6**: issue workflow (owner, status, comments, links, history, manual issues), `entity_decision` and multi-issue `disposition` kinds, `revert` for every overlay, re-imports with committed unfiltered re-exports (`fixtures/demo/brightwater_reexport/`), new migration and setup pages; E2E-3, E2E-4, E2E-8. Decisions: `docs/decisions/0007-issue-workflow-and-decisions.md`.
- **M7**: scope-bound gate waivers that lapse, fingerprint-bound readiness sign-off with invalidation, readiness re-evaluation jobs, shared change request orchestration (`relay.pipeline.approvals`), `relay-demo fast-forward --to before-signoff`, Readiness and Settings pages; E2E-5. Decisions: `docs/decisions/0008-readiness-waivers-signoff.md`.

- **M8**: AI investigation layer: providers (`disabled`, `scripted`, `anthropic` over the standard library), 15 read-only tools with redaction, investigator loop with budgets, provenance verification, findings to operator-owned draft change requests, consent through `policy_change` (`ai_enabled`), `run_investigation` jobs (`relay.investigations`), investigation UI, scripted evals E1–E6 (`relay_evaluation.ai`); E2E-7. No live eval run recorded (no key). Decisions: `docs/decisions/0009-ai-investigation-layer.md`.

- **M9**: security review against every requirement ID (`docs/traceability.md`), errored rule and reconciliation stages (FC-10), the over-explanation invariant (FC-11), CSP, upload rate limiting, route inventory and static guards, measured pipeline performance (`make pipeline-perf`) and the read-path fix behind it, two more seeded migrations, E2E-6, `make test-all`, README demo guide and the retrospective. Decisions: `docs/decisions/0010-m9-hardening.md`.

After M9, six review passes went over the finished system (accounting correctness, adversarial,
anti-cheating, code quality, UX, documentation). They changed real behaviour — superseded runs,
stricter G5, a real R6 source side, ASCII-only numerals, a nonce CSP — so read
`docs/review-findings.md` alongside the milestone log.

A later productization pass turned the same capabilities into an operator-facing product: a work
queue (`relay.pipeline.work_queue`, `GET /migrations/{id}/work-queue`) that groups findings into the
decisions a person actually makes, an implementation command center, an overview built around "can
this customer go live?", and readiness restated as six operator questions with G1–G12 preserved
underneath. **The work queue composes engine output — it must never branch on scenario knowledge**;
the mapping decision exists because a reconciliation attributed a difference to one legacy account
whose mapping the compatibility check doubts, not because a demo has such an account.

`docs/progress.md` is the recovery log: read it first in a new session.

Layout:
- `backend/src/relay/`: **runtime** package. Pure: `core`, `canonical`, `ingestion`, `mapping`, `profiling`, `engine`. Database: `audit`, `identity`, `workspace`, `jobs`, `imports`, `mapping_sets`, `changes`, `issues`, `pipeline`, `investigations`. AI (read models only): `ai`. Entry points: `api`, `worker.py`, `cli.py`. Layers are enforced by import-linter (see `backend/pyproject.toml`).
- `backend/src/relay_scenarios/`: **demo/evaluation-only** scenario generators (they know which issues they plant)
- `backend/src/relay_evaluation/`: **evaluation-only** golden-manifest loader, reference oracle, verifier
- `backend/migrations/` (Alembic), `backend/tests/{unit,integration,scenario,ai}`
- `evals/results/`: recorded live investigator eval runs (none yet)
- `fixtures/demo/brightwater/`: generated source-style files Relay ingests (no answers inside)
- `fixtures/demo/brightwater_config/`: the approved column mapping set for those files (configuration, no answers)
- `evaluation/brightwater/golden_manifest.toml`: hand-authored ground truth (never read by runtime code)
- `fixtures/demo/kestrel/`, `fixtures/demo/kestrel_config/`, `evaluation/kestrel/expected.toml`: the **second company** (Kestrel Instruments Ltd), the generalization test — a different legacy system, file conventions, currency, fiscal year and defects, run through the same unchanged engine ([0011](docs/decisions/0011-second-company-generalization.md))
- `web/`: Next.js app. `src/app` (routes; Server Components call the API server-side), `src/components` (shared UI, including the design layer in `ui.tsx` and the work-item card), `src/lib` (API client and generated types, formatting, session, and the readiness-category translation in `readiness.ts`), `e2e/` (Playwright)
  - `web/AGENTS.md` and `web/CLAUDE.md` are generated and re-created by `next dev`. They only point to the Next.js 16 docs bundled in `node_modules/next/dist/docs/`. Read those docs before writing Next.js code; every rule in this file still applies inside `web/`.
- `docs/`: planning documents, `decisions/`, `progress.md`

---

## Commands

Toolchain: uv, Node.js 24 + npm (not pnpm), Docker Compose v2. Run from the repository root. `make help` lists everything.

### Available now (verified)

| Command | Purpose |
|---|---|
| `make setup` | Install backend (uv, `backend/uv.lock`) and web (npm, `web/package-lock.json`) dependencies |
| `make fmt` | Format Python (ruff format + import sort) and web (prettier) |
| `make fmt-check` | Check formatting without writing |
| `make lint` | ruff check, import-linter contracts, eslint (`--max-warnings=0`) |
| `make typecheck` | mypy `--strict` (src, tests, migrations), `next typegen && tsc --noEmit` |
| `make test` | Backend unit + property tests (`-m "not integration"`) and web Vitest tests |
| `make test-integration` | Starts Compose Postgres, runs `-m integration` against database `relay_test` (dropped/recreated) |
| `make check` | **Canonical full verification**: fmt-check, lint, typecheck, test, demo-check, demo-verify, demo-kestrel-check, demo-kestrel-verify, test-integration, build-web, compose-config |
| `make build-web` | Next.js production build |
| `make build` | build-web + `docker compose build` |
| `make compose-config` | Validate `docker-compose.yml` |
| `make demo-config` | Render and validate the public-demo overlay against `.env.demo`; starts nothing |
| `make demo-up` / `make demo-down` | Build and start the PUBLIC DEMO stack locally in its own compose project (`relay-demo`, own volumes) from a fresh database — migrate, seed, `relay-demo public-demo`, serve / stop it and delete its volumes |
| `make prod-config` | Render the deployment overlay (`docker-compose.prod.yml`) against `.env.production` and validate it; starts nothing. Needs `.env.production` (from `.env.production.example`); see `docs/deployment.md` |
| `make db-up` / `make db-stop` | Start (and wait for healthy) / stop Compose PostgreSQL |
| `make db-migrate` | `alembic upgrade head` against the local database |
| `make db-downgrade` | `alembic downgrade -1` |
| `make db-current` | Show current revision |
| `make db-revision m="message"` | New Alembic revision (post-write hook runs ruff on it) |
| `make up` / `make down` | Build and start the full stack (db, migrate, api, worker, web) and wait for health / stop it (volumes kept) |
| `make smoke` | Against a running stack: API health, readiness, and web page showing both healthy with migrations at head |
| `make dev` | API (uvicorn `--reload`) + web (`next dev`) on the host, Compose Postgres; `make dev-api`, `make dev-web` run one each. Host-run backend processes store blobs in `backend/.data/blobs` |
| `make logs` | Follow Compose logs |
| `make demo-data` | Regenerate Brightwater fixtures (`relay-demo generate`) and print a summary without answers |
| `make demo-check` | Committed fixtures equal a fresh generation byte for byte |
| `make demo-verify` | **Evaluation only**: verify fixtures against the golden manifest |
| `make demo-kestrel` | Regenerate the second company's fixtures (`relay-demo generate-kestrel`) |
| `make demo-kestrel-check` | Committed second-company fixtures equal a fresh generation byte for byte |
| `make demo-kestrel-verify` | **Evaluation only**: run the engine over the second company and compare with `evaluation/kestrel/expected.toml` |
| `make demo-manifest` | **Evaluation only**: print the golden manifest |
| `make demo-seed` | With the stack up (`make up`): load Brightwater at the day-9 state through the services, inside Compose so the worker shares blob storage. `make demo-seed-host` does the same with host-run processes (stop the Compose worker first) |
| `make worker` | Run the job worker on the host (`relay worker`; `relay worker --once` drains and exits) |
| `make verify-audit` | Recompute every audit hash chain (`relay verify-audit [--migration ID]`) |
| `make openapi` | Regenerate `web/src/lib/api/openapi.json`; `tests/unit/test_openapi.py` fails on drift. Then `cd web && npm run api:types` regenerates `schema.d.ts` (a web test fails on drift) |
| `make test-e2e` | Playwright end-to-end tests against a freshly seeded stack (`make up`, then `make demo-seed` or `make demo-reset`); uses the locally installed Chrome. The tests change demo state |
| `make demo-reset` | **Destroys** the local Compose database, recreates it, migrates and seeds Brightwater again |
| `make eval-ai-scripted` | Investigator evals E1–E6 with the scripted provider against the local seeded database (no model calls; at most 20 investigations per person per hour) |
| `make demo-ai` | Restart the stack with the **demo** provider and record AI consent through an approved policy change, so investigations can be shown with no key and no network |
| `make demo-ai-off` | Restart the stack with AI off (the recorded consent stays; the provider is what changes) |
| `make eval-ai` | **Manual, costs money**: live investigator evals against the local seeded database; needs `ANTHROPIC_API_KEY` (refuses without it, verified); writes `evals/results/investigator-<timestamp>.json`. Never in CI. Not yet run with a key |
| `make demo-portfolio` | With the stack up and seeded: add two more fictional migrations (Harborline signed off, Northwind early stage) so the portfolio shows a spread of states |
| `make demo-fast-forward` | With the stack up and seeded: apply the documented resolutions as the seeded users so only sign-off remains (`relay-demo fast-forward --to before-signoff`) |
| `make engine-run` | Run the engine over the Brightwater fixtures: gates, reconciliation statuses, findings by rule. Direct form: `uv run relay engine run --migration DIR --mapping-set FILE [--overlays FILE] [--json OUT]` (from `backend/`) |
| `make pipeline-perf` | Measure the **persisted** pipeline (imports, runs, readiness, read endpoints) on a synthetic 250,000-line migration in a throwaway database it creates and drops (several minutes) |
| `make engine-perf` | Generate a synthetic clean 250,000-line migration and measure one engine run (about a minute); exits non-zero if the clean data produces any finding |
| `make test-all` | `make check`, then build and start the stack, smoke-test it, reseed the demo and run the Playwright suite (the M9 acceptance command) |
| `make clean` | Remove caches and build output |

Host ports default to db 55432, API 8000 and web 3000. Override them with `RELAY_DB_HOST_PORT`, `RELAY_API_HOST_PORT` and `RELAY_WEB_HOST_PORT` in the environment or `.env`.

### Planned (do NOT claim these work until they exist — move each row to "Available now" when implemented and verified)

| Command | Purpose | Milestone |
|---|---|---|
| _(none: every planned command is implemented)_ | | |

---

## Architectural principles (non-negotiable)

1. **Deterministic core, AI at the edge.** Normalization, entity candidates, validation, reconciliation, issue lifecycle and readiness are deterministic. Removing AI must not remove correctness.
2. **Immutable inputs, recomputable outputs.** `source_rows` and `audit_events` are never updated or deleted. Staged data, exceptions, reconciliations and gates are recomputed per pipeline run from a fingerprinted input set.
3. **Corrections are overlays.** Mapping versions, record overrides, entity decisions, dispositions and policy versions — each created only by applying an approved change request.
4. **Every governed mutation writes an audit event in the same transaction.**
5. **Lineage everywhere.** Staged record → source row (file, line). Exception → records. Issue → exceptions. Gate → evidence.
6. **Modular monolith** with enforced import contracts. The pure core (`core`, `canonical`, `ingestion`, `mapping`, `profiling`, `engine` — which holds validation, reconciliation, entity resolution and readiness) does no DB, no I/O, no clock reads and no randomness; `*/domain.py` in the database modules is pure for the same reason.
7. **Don't add infrastructure** (brokers, caches, services) without a measured need and a docs update.

---

## Financial correctness rules

- **Money is `Decimal`** (Python), `NUMERIC(20,4)` (Postgres), **string** (JSON). Never `float`, never `int` cents mixed with decimals, never JS arithmetic on money.
- Every amount has an explicit currency. Functional amounts are separate fields.
- **Sign convention:** canonical ledger amounts are debit-positive, credit-negative.
- **Never round source amounts.** Quantize only for FX conversion (`ROUND_HALF_UP`, currency minor units, per line) and display.
- Compare exact differences to tolerances.
- **Business dates are `date`**, never timezone-converted. System timestamps are UTC `TIMESTAMPTZ`. Periods are derived from dates via the fiscal calendar.
- Date parsing requires an explicit format. No locale guessing.
- A rule or reconciliation that errors must fail readiness, never pass silently.
- Explainers may only explain amounts backed by matched records (timing items). Error indicators are hints, not explanations.
- Rule-backed issues are **resolved only by a current run no longer producing their fingerprint.** Nobody (human or code path) sets `resolved` manually.
- Real legacy misstatements (`source_anomaly`) are **dispositioned**, not silently fixed in migration history.
- Changing a rule's/reconciliation's/gate's behavior requires bumping its `version`, updating docs, and updating golden manifests with an explanation.

Requirement IDs (FC-xx, GV-xx, SEC-xx) live in `docs/security-and-correctness.md`. Reference them in tests.

---

## Evaluation-truth boundary (anti-cheating, non-negotiable)

- Runtime code (`relay.*`) must never import `relay_scenarios` or `relay_evaluation`, read `evaluation/`, or branch on scenario knowledge: `DS-*`/`TN-*` ids, Brightwater record ids (`JE-AP-20455`, `INV-10877`, `V-1042`, ...), Kestrel's (`KS-0x`, `K-000x`, `JNL-00xxx`, `NB-8842`, ...), party names, system names, or known defect amounts. Enforced by import-linter contracts and `tests/scenario/test_determinism_and_boundaries.py`.
- `relay_scenarios` must never import `relay_evaluation`: generators cannot read the answers.
- The golden manifest is hand-authored from the specification. **Never change it to match engine or generator output.** A mismatch is classified (engine bug / generator bug / manifest bug / specification ambiguity) with evidence, and truth changes only when justified by the accounting specification, recorded in `docs/decisions/`.
- Source fixtures must not contain answer-revealing text, flags or file names (tested, both companies).
- A second company exists so that "the engine agrees with the manifest" cannot mean "the engine learned the manifest". If something only works for Brightwater, it is broken: generalize it rather than special-casing.
- Identifiers are opaque (SC-05 – SC-07): never infer chronology from identifier magnitude.

## AI safety boundaries

- The `relay.ai` package may import only `*.read_model` and `*.schemas`. **Never** services, models, or sessions that can write. This is enforced by import-linter; do not add exceptions.
- Tool DB sessions run `SET TRANSACTION READ ONLY`.
- `migration_id` and `run_id` are bound server-side in `ToolContext`; never add them as tool arguments.
- No generic query/SQL/file/network tools. Ever.
- Findings must pass provenance verification; `failed` findings cannot be promoted to change requests.
- `requires_approval` is computed by server policy, not taken from model output.
- AI is never a change-request requester or reviewer, and never changes issue status, severity or owner.
- Data from imported files is untrusted; render AI output and data as plain text.
- Tool outputs apply the redaction policy (tax ids, bank accounts, emails, free-text notes).
- Everything must work with `RELAY_AI_PROVIDER=disabled` (the default). Tests and CI use the `scripted` provider — never live model calls.
- `scripted` and `demo` replay authored transcripts. **Never present either as a model**: the UI labels them, and evals never report their output as live-model performance. The tools they call do run for real, so their evidence is genuine.
- AI consent (`ai_enabled`) is an approved `policy_change`. There is no code path that sets it directly, and there must never be one.
- Before implementing provider code, check current vendor SDK documentation and model identifiers rather than relying on memory.

---

## Coding conventions

### Backend (Python 3.12)
- Money: use `relay.core.money.Money` / `validate_amount`; never construct amounts from floats; never add `*` or `/` to `Money`. FX goes through `convert()` only. See `docs/decisions/0001-money-representation.md`.
- Dates: `relay.core.dates` for business dates (`BusinessDate` in Pydantic models), `relay.core.timestamps` for system times (`UtcTimestamp`). Database columns use `relay.core.db_types` (`AmountType`, `FxRateType`, `CurrencyCodeType`, `BusinessDateType`, `UtcTimestampType`), never raw `Numeric`/`Date`/`DateTime`.
- Type everything; `mypy --strict` clean. No `Any` in domain code without a comment explaining why.
- Pydantic v2 models at API/AI/JSONB boundaries with `extra="forbid"`; frozen dataclasses in pure domain code.
- SQLAlchemy 2.0 typed ORM, **sync** sessions, explicit unit-of-work; services own transactions; routers never commit.
- Module layout: `models.py`, `schemas.py`, `domain.py`, `service.py`, `read_model.py`. Only a module writes its own tables.
- Errors: raise subclasses of `RelayError` with a stable `code`; the API maps them to problem+json. Don't raise `HTTPException` from services.
- Enums: `StrEnum` + `TEXT` with `CHECK` constraint.
- IDs: UUIDv7 from `core.ids`. Time: `core.clock` only — never `datetime.now()` directly.
- Logging: structlog with ids/counts/hashes; never log row values, file contents, prompts, or completions.
- Rules: register with `@rule(spec)`; pure; deterministic ordering; include positive/negative/near-miss fixtures.
- Alembic: one migration per logical change; never edit an applied migration; include downgrade.

### Frontend (TypeScript)
- `strict: true`. API types only from the generated OpenAPI client — no hand-written API types.
- Server state via TanStack Query; filters in the URL.
- Money via `<Money value="…" currency="…">`; no arithmetic. Dates via `<BusinessDate>`; timestamps via `<Timestamp>`.
- Status never conveyed by color alone.
- No `dangerouslySetInnerHTML`.
- AI content rendered only through the `ai-finding` components.

### General
- Prefer small, explicit code over frameworks and metaprogramming.
- Match the surrounding code's style and comment density.
- Keep docs in sync with behavior in the same change.

---

## Testing expectations

- Add tests at the lowest layer that can catch the bug (see `docs/testing.md`).
- Rules/reconciliations/gates: unit fixtures **and** scenario manifest coverage.
- Anything touching change requests, audit, or append-only tables: integration tests against real Postgres (never SQLite).
- Golden manifests must match **exactly**. If you change expected results, explain precisely why in the commit message; never update a manifest just to make a test pass.
- No network in tests. Frozen clock. Fixed seeds.

---

## Never do

- Never modify or delete `source_rows`, `quarantined_rows`, or `audit_events` rows, or add a code path that could.
- Never use `float` for money or convert business dates through timezones.
- Never let AI code write data, approve, submit, or change issue state; never add a write-capable tool.
- Never bypass approval policy or segregation of duties, including in seeds and fast-forward scripts (they must act as the seeded users through the same services).
- Never mark a rule-backed issue `resolved` manually or make a failing gate pass by special-casing demo data.
- Never special-case Brightwater natural keys, names or amounts in engine code. The demo must be detected by general rules.
- Never compute a readiness "score".
- Never commit secrets, `.env`, real customer data, or large generated artifacts outside `fixtures/`.
- Never claim a command, test, or feature works without having run it.
- Never start the next milestone without the user's approval.

---

## Verify before claiming completion

Before saying a task is done:

1. Run `make check` (it starts PostgreSQL itself). Do not pipe it through `tail`/`head` in a way that hides the exit code.
2. Run the tests covering the change; for engine changes, run the scenario manifest tests.
3. For API changes: regenerate OpenAPI and confirm the web typecheck passes.
4. For UI changes: run the relevant Playwright flow (from M4) or open the page and exercise the flow; say which. For stack-level changes: `make up` then `make smoke`.
5. For migrations: upgrade from empty DB and run integration tests.
6. Update `docs/progress.md` and any doc whose described behavior changed.
7. Report honestly: what was run, what passed, what failed, what was not verified.
