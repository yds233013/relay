# Relay — Progress Log

One entry per milestone: what was built, what changed from the plan, and why.

---

## M0 — Repository foundation

Status: **Complete.** Committed as `ca169bf` (`feat: establish Relay application foundation`).

### Built

**Backend (`backend/`)** — Python 3.12, uv, FastAPI, SQLAlchemy 2.0 (sync) + psycopg 3, Alembic, Pydantic v2, structlog.

- `relay.core.currency`: ISO 4217 registry with minor units.
- `relay.core.money`: `Money`, amount validation against the `NUMERIC(20,4)` envelope, exact arithmetic, currency-safe comparison, tolerance checks, FX conversion (the only rounding), debit/credit → signed amounts, explicit-format parsing of source amount text, Pydantic integration. Decisions: [decisions/0001-money-representation.md](decisions/0001-money-representation.md).
- `relay.core.dates`: business dates (`date` only, datetimes rejected), explicit-format parsing, ambiguity detection, fiscal periods, Pydantic `BusinessDate` type.
- `relay.core.timestamps`: aware-UTC timestamps, RFC 3339 parse/format, Pydantic `UtcTimestamp` type.
- `relay.core.clock`, `ids` (UUIDv7), `hashing` (canonical JSON, SHA-256), `errors`, `config`, `logging`.
- `relay.core.db`: engine (UTC session time zone), session factory, unit-of-work scope, declarative base with naming conventions, Alembic helpers.
- `relay.core.db_types`: column types that reject floats, over-scale amounts, naive timestamps and datetimes posing as dates *before* PostgreSQL can round or coerce them.
- `relay.api`: app factory, `GET /health`, `GET /health/ready`, problem+json errors, request-id and request-logging middleware, baseline security headers.
- Alembic baseline revision `0001_baseline` (empty schema) and a ruff post-write hook for new revisions.
- Tests: unit, property-based (Hypothesis), and integration tests against PostgreSQL 16.

**Web (`web/`)** — Next.js 16, React 19, TypeScript strict, Tailwind 4, ESLint, Prettier, Vitest.

- Server-side config parsing (`RELAY_API_URL`), health probe with runtime response validation, and one development status page showing API and database health.

**Infrastructure**

- `docker-compose.yml`: `db` (PostgreSQL 16.15), `migrate` (one-shot), `api`, `web`. Localhost-only ports, digest-pinned base images, non-root containers, health checks.
- `Makefile` as the developer interface; `make check` is the canonical verification.
- GitHub Actions: `make setup`, `make check`, then `make up` and `make smoke`.
- `.env.example`, root `.gitignore`.

### Changed from the plan, and why

| Change | Reason |
|---|---|
| Health endpoints are `/health` and `/health/ready`, not `/healthz`/`/readyz` | Requested for M0; "ready" is documented as the HTTP sense, not launch readiness. |
| npm instead of pnpm | pnpm via corepack failed on the development machine; npm ships with Node and removes a toolchain dependency. Lockfile is `web/package-lock.json`. |
| No `worker` service or `relay.jobs` package | The jobs table and worker belong to M3. Creating a worker process with nothing to do would be fake functionality. |
| No `fixtures/` or `evals/` directories | They would be empty until M1/M8. |
| Added `core/currency.py`, `core/timestamps.py`, `core/db_types.py`, `api/problems.py`, `api/middleware.py` | Separating these kept `money.py`, `dates.py` and `app.py` focused. |
| `httpx2` instead of `httpx` for the test client | Starlette 1.6 deprecates `httpx` for `TestClient`. |
| Web calls the API from the server only | Avoids exposing the API URL to browsers and needing CORS before any browser-side API use exists. |
| Import-linter has one contract (`api` → `core` layers) | The other contracts reference modules that do not exist yet; they are added with those modules. |

### Known warnings and limitations

- `pytest` ignores exactly one third-party `DeprecationWarning` raised when `starlette.testclient` is imported (a deprecated anyio alias). All other warnings fail tests.
- `eslint@9` prints an npm deprecation notice on install; it is the version `eslint-config-next@16.3.5` supports.
- GitHub Actions has not been run yet (no remote). Every CI step was run locally.
- Security headers do not yet include a Content Security Policy (SEC-15). A nonce-based CSP for Next.js is deferred until there is real UI.
- No authentication exists (planned for M3 as a development identity only).
- `web/AGENTS.md` and `web/CLAUDE.md` are written by `next dev` (Next.js 16) and point agents at the bundled Next.js docs. They are regenerated if deleted, so they are kept.
- Tests do not yet block network sockets globally (testing.md §1.4); the only network-shaped unit test targets a refused localhost port. Add socket blocking when external integrations appear.
- GitHub Actions are pinned by major version tag, not commit SHA.

---

## M1 — Canonical model and Brightwater scenario generator

Status: **Complete** (see commit log for the M1 commit).

### Built

- **Specification corrections before implementation** (committed separately first):
  [decisions/0002-brightwater-spec-corrections.md](decisions/0002-brightwater-spec-corrections.md)
  - SC-01 – SC-07: approved by the owner.
  - SC-08: an autonomous correction uniquely implied by the rule catalog, recorded while authoring the manifest and before any engine existed.
- **Canonical accounting model**, `relay.canonical` (runtime):
  - accounts with subtype semantics, parties, journal entries and lines (signed, transaction and functional amounts)
  - documents, payments with applications, bank transactions, FX rates
  - control balances, aging items, natural keys, source-location lineage
  - Records validate shape only, so defective data stays representable.
- **Brightwater generator**, `relay_scenarios.brightwater` (evaluation/demo only):
  - clean books first:
    - carried-forward open documents from 2025
    - Q1 manual COGS relief, perpetual inventory from April (SC-06)
    - weekly pay runs, payroll, month-end accruals and reversals
    - line-of-credit calibration to the fixed cash facts
  - identifier assignment: pinned documented ids; invoice numbers reserved at order entry (SC-05); bill numbers independent (SC-03); journal-number gaps (SC-06)
  - independent control reports computed from the full legacy universe, not the exports
  - LedgerPro/bank export writers with realistic quirks
  - 13 bounded injectors (DS-01 – DS-13) with preconditions and dependencies
  - the traps (TN-01 – TN-05) are legitimate clean-book activity
- **Golden manifest** `evaluation/brightwater/golden_manifest.toml` (hand-authored):
  - facts per defect and trap
  - the exact expected reconciliation discrepancy set (R1, R2, R3, R3b, R4, R6), R5 explained items and totals
  - expected rule-level issues and candidates for M2
  - Run #1 gates
- **Evaluation layer**, `relay_evaluation` (evaluation only):
  - manifest loader
  - independent CSV reader
  - reference oracle computing R1–R6 from fixture files only
  - verifier and the `relay-eval` CLI
- **Fixtures** `fixtures/demo/brightwater/`: 17 files plus `SHA256SUMS`.
- **Commands**: `make demo-data`, `make demo-check`, `make demo-verify`, `make demo-manifest`.

### Measured (seed 20260630)

| | |
|---|---|
| Legacy / target accounts | 132 (127 active) / 69 |
| Customers | 408 in LedgerPro, 171 active and exported |
| Vendors | 94 |
| Invoices / bills (incl. carried forward) | 1,037 / 1,331 |
| Receipts / bill payments | 882 / 1,092 |
| Journal entries / lines | 4,341 / 9,688 |
| Bank transactions (to 2026-07-15) | 2,022 |
| GL cash / bank at cutover (Run #1) | 412,906.18 / 427,101.93 (documented values) |
| Clean books GL cash / bank | 427,768.68 / 442,234.43 (difference = timing items only) |
| Reconciliation discrepancies, clean books | 0 |
| Manifest checks, Run #1 | 115 / 115 |

### Changed from the plan, and why

| Change | Reason |
|---|---|
| Generators and evaluation live in `relay_scenarios` / `relay_evaluation`, not `relay/demo` | Structural anti-cheating boundary enforced by import-linter (D-15). |
| Manifest is TOML under `evaluation/`, not YAML under `fixtures/` | Physical separation of source data and truth; stdlib parser (D-16). |
| CLI is `relay-demo` / `relay-eval`, not `relay demo …` | A runtime `relay` CLI must not import generators. |
| Volumes: ~880 history-window invoices, ~9.7k GL lines, ~2.0k bank lines | SC-03 target; documented row counts are approximate. |
| Target chart has 69 accounts (≈90 documented) | Enough to express the mapping design, including unused template accounts; the count is not an invariant. |
| Generator design choices the spec left open: DS-06 moves the open 3,215.40 invoice plus the two earliest paid Q2 invoices; DS-01 moves B-21544 plus the two earliest paid bills from April; suspense entries use accrued liabilities and freight-in as counter accounts; the three outstanding checks are dated 06-29, 06-29 and 06-30 (weekend avoided, within the documented 06-27…06-30 range) | Bounded, deterministic, consistent with every documented fact. |
| No bank holidays modeled; no reconciling items at the opening date | Documented generator assumptions. |

### Known limitations and debt

- The reference oracle's R5 matching is by amount, sufficient for this data set. Relay's engine (M2) must match on richer evidence.
- R6 source totals reconstruct quarantined records by joining consecutive malformed lines. M2 must decide how Relay presents that reconstruction.
- `backend/tests/scenario` adds about 2 minutes to `make test`, mostly the per-injector isolation builds.
- The performance-scaling generator for the 250k-line target is M2 work (not yet built).

### Next

M2: deterministic engine (normalization, rules, reconciliations, entity candidates) run against the fixtures and compared with the golden manifest.
