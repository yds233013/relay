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
| Security & correctness requirement IDs | `docs/security-and-correctness.md` |
| Milestones and acceptance criteria | `docs/implementation-plan.md` |
| What has actually been built | `docs/progress.md` (created in M0) |

---

## Current state

**Planning phase. No application code, build tooling, Docker setup, or tests exist yet.** The only thing in this repository is documentation. Do not start a milestone without explicit user approval; the user approves milestones one at a time.

---

## Commands

### Available now

| Command | Purpose |
|---|---|
| `git status` / `git log` | That's it. Nothing else is set up. |

### Planned (do NOT claim these work until they exist — move each row to "Available now" when implemented)

| Command | Purpose | Milestone |
|---|---|---|
| `make setup` | Install backend (uv) and web (pnpm) dependencies | M0 |
| `make fmt` | ruff format + prettier | M0 |
| `make lint` | ruff check, eslint, import-linter | M0 |
| `make typecheck` | mypy --strict, tsc --noEmit | M0 |
| `make test` | Backend unit/property/pure-scenario + web unit | M0 |
| `make check` | fmt check + lint + typecheck + test | M0 |
| `make up` / `make down` | Docker Compose stack | M0 |
| `uv run relay demo generate --seed 20260630 --out fixtures/demo/brightwater` | Generate demo CSVs | M1 |
| `uv run relay engine run --fixtures … --config …` | Run pure engine from files | M2 |
| `make db-migrate` | Alembic upgrade head | M3 |
| `make test-integration` | Integration tests against Postgres | M3 |
| `uv run relay worker` | Job worker | M3 |
| `uv run relay demo seed` | Seed Brightwater "day 9" state | M3 |
| `uv run relay verify-audit --migration <id>` | Verify audit hash chain | M3 |
| `make openapi` | Regenerate OpenAPI + TS client | M3 |
| `make test-e2e` | Playwright against compose | M4 |
| `uv run relay demo fast-forward --to=before-signoff` | Apply scripted resolutions | M7 |
| `make eval-ai` | Live-model evals (manual, needs key) | M8 |

---

## Architectural principles (non-negotiable)

1. **Deterministic core, AI at the edge.** Normalization, entity candidates, validation, reconciliation, issue lifecycle and readiness are deterministic. Removing AI must not remove correctness.
2. **Immutable inputs, recomputable outputs.** `source_rows` and `audit_events` are never updated or deleted. Staged data, exceptions, reconciliations and gates are recomputed per pipeline run from a fingerprinted input set.
3. **Corrections are overlays.** Mapping versions, record overrides, entity decisions, dispositions and policy versions — each created only by applying an approved change request.
4. **Every governed mutation writes an audit event in the same transaction.**
5. **Lineage everywhere.** Staged record → source row (file, line). Exception → records. Issue → exceptions. Gate → evidence.
6. **Modular monolith** with enforced import contracts. Domain modules (`*/domain.py`, `validation`, `reconciliation`, `entity_resolution`, `readiness` domain) are pure: no DB, no I/O, no clock reads, no randomness.
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
- Everything must work with `RELAY_AI_PROVIDER=disabled`. Tests and CI use the `scripted` provider — never live model calls.
- Before implementing provider code, check current vendor SDK documentation and model identifiers rather than relying on memory.

---

## Coding conventions

### Backend (Python 3.12)
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

1. Run the relevant checks that exist (`make check` once M0 lands; before that, state that no checks exist).
2. Run the tests covering the change; for engine changes, run the scenario manifest tests.
3. For API changes: regenerate OpenAPI and confirm the web typecheck passes.
4. For UI changes: run the relevant Playwright flow or open the page and exercise the flow; say which.
5. For migrations: upgrade from empty DB and run integration tests.
6. Update `docs/progress.md` and any doc whose described behavior changed.
7. Report honestly: what was run, what passed, what failed, what was not verified.
