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

---

## M2 — Deterministic engine

Status: **Complete** (commit `feat: implement deterministic validation engine`). Decisions and the engine-vs-manifest mismatch log: [decisions/0003-deterministic-engine.md](decisions/0003-deterministic-engine.md).

### Built

- **Ingestion** `relay.ingestion.csv_reader`: raw rows with physical-line lineage; malformed physical lines grouped into quarantined records with content-derived keys; bounded multi-line quoted fields; operator repair parsing.
- **Column mapping** `relay.mapping.transforms`: allow-listed transform steps (trim, parse_decimal with an explicit amount format, parse_date/parse_period with explicit formats, value_map without guessing, regex_extract, currency, constant, debit/credit pairs). Invalid configuration fails before any row is read.
- **Approved column mapping set** for the LedgerPro, First Cascade and implementation files: `fixtures/demo/brightwater_config/column_mapping_set_v1.json`. This is configuration a customer implementation would author; it contains no answers.
- **Engine** `relay.engine`:
  - `inputs`: migration descriptor, file hashes, bank account links
  - `snapshot`: normalization with `NORM.*`, `COA.*`, `OVERRIDE.STALE`
  - `overlays`: record overrides, quarantine repairs, entity decisions, account mapping changes, dispositions, gate waivers, sign-offs
  - `entities`: candidate scoring v1 and decision clusters
  - `rules`: 32 registered rules (MAP, GL, AR/AP mirrored, AP duplicates, PAY, CUR, PARTY, DATA)
  - `reconciliation`: R1, R2, R3/R3b/R3o, R4/R4b/R4o, R5 (outstanding checks, deposits in transit, bank-only activity), R6 with provisional quarantine reconstruction, hints, drill-down
  - `readiness`: G1–G12 on one result, exposure de-duplication, waivers and sign-offs bound to the input fingerprint
  - `pipeline`: input and result fingerprints, severity overrides, de-duplication and stable ordering
- **Runtime CLI** `relay engine run` (`make engine-run`): human summary or a JSON report.
- **Evaluation** `relay_evaluation.brightwater.engine_compare`: resolves manifest selectors from the raw files with the independent reader and compares issues, reconciliation lines, R5, totals, candidates and traps exactly. `relay_evaluation.brightwater.resolution` encodes the documented resolutions (evaluation only).
- **Generator additions** (`relay_scenarios`): LedgerPro export filter options for the re-exports DS-04, DS-09 and DS-12 require; `relay_scenarios.volume`, a synthetic clean company ("Harborline Supply Co.") at any GL size; `relay-demo perf-engine` (`make engine-perf`).
- **Contracts**: layers `api > engine > ingestion | mapping > canonical > core`; the engine, ingestion, mapping and canonical packages may not import the API, database, configuration or clock modules, SQLAlchemy, psycopg, FastAPI or httpx. Verified to fail when violated.

### Verified

| Check | Result |
|---|---|
| Run #1 vs golden manifest (issues, severities, amounts, reconciliation lines, R5, totals, candidates, traps) | exact match (89 comparisons) |
| Comparison is not vacuous (dropped, extra, wrong-severity and wrong-amount issues; missing reconciliation) | each detected |
| Run #1 failing gates | G1, G3, G5, G6, G7, G8, G9, G10, G12 (= manifest) |
| DS-01 merge | reveals exactly the manifest's DS-02 issues |
| Documented resolutions (re-exports, overlays, dispositions) | G1–G11 pass, exposure 0.00, every reconciliation tied (R5 with explained items); G12 passes only with a sign-off bound to the same fingerprint |
| Committed fixtures vs in-memory generation | identical input and result fingerprints |
| Clean synthetic company | 0 findings, all reconciliations tied |
| Rule catalog | every registered rule has a positive case except `AP.DOCUMENT_TOTAL_CONSISTENT` (not expressible in the bills export; enforced list); near-miss cases for look-alike patterns |
| Backend tests (unit + scenario) | 591 passed |

### Measured

Brightwater Run #1 (fixtures, this machine): **1.0 s** for the full engine (read, normalize, rules, reconciliations, candidates); 9,669 staged GL lines; 65 findings (46 critical, 10 high, 7 medium, 2 low); 4 entity candidates.

Synthetic volume (`make engine-perf`), measured once on an **Apple M2, 8 cores, 16 GB, macOS 14.5, Python 3.12.10**, single process:

| GL lines | Entries | Invoices / bills | Payments | Parties | Source size | Engine wall time | Peak RSS (process) | Findings |
|---|---|---|---|---|---|---|---|---|
| 20,000 | 10,000 | 3,000 / 2,200 | 4,558 | 120 / 73 | 4.1 MB | 2.17 s | 127 MiB | 0 |
| 250,000 | 125,000 | 37,500 / 27,500 | 56,697 | 1,500 / 916 | 50.8 MB | **34.64 s** | 1,019 MiB | 0 |

The plan's target (< 60 s at 250k lines) is met on this machine. A cProfile run at 100,000 lines showed normalization at about 85% of engine time (money validation and per-cell transforms), with rules and reconciliations the remainder. Scaling from 20k to 250k lines is slightly worse than linear. Numbers from other machines will differ; nothing was extrapolated.

### Changed from the plan, and why

| Change | Reason |
|---|---|
| Overlays and the mapping set are JSON (`--mapping-set`, `--overlays`), not YAML | Standard library parser; the same shapes will be persisted in M3. |
| Findings for reconciliation lines are `RECON.<id>` exceptions | One lifecycle for every blocking signal; see 0003 E-03. |
| `GL.DUPLICATE_ENTRY` limited to manual entries; `PAY.DUPLICATE_PAYMENT` covers both directions; suspense is not a control subtype | 0003 E-07, E-08, E-09; the validation document was updated. |
| Waivers do not carry across fingerprints yet; cross-run issue lifecycle not built | Needs persistence (M3) and waiver scopes (M7); 0003 E-11, E-12. |
| Generator: C-0412 has only the DS-09 records; export filters added | Generator bug found by the manifest comparison (0003 M-01). Current Run #1 counts: 1,034 invoices, 1,331 bills, 879 receipts, 1,092 bill payments, 4,336 journal entries (9,678 lines), 2,019 bank lines. |

### Known limitations and debt

- The DS-06 below-strong candidate pairs score 0.6013 against a 0.60 threshold. The expected issue set is sensitive to entity weight changes.
- `COA.TYPE_VALID` cannot be reached through the v1 mapping set (value maps reject unknown detail types first, as `NORM.PARSE_FAILURE`). `AP.DOCUMENT_TOTAL_CONSISTENT` cannot be reached through the LedgerPro bills export.
- `regex_extract` patterns come from approved mapping configuration and are not protected against pathological backtracking; review before accepting mapping sets from untrusted users (M5).
- Unresolved exposure is an attention metric that counts related findings on different subjects separately (for example R1 and R2 lines for the same defect).
- The engine holds the whole migration in memory (about 1 GB at 250k lines). Persistence in M3 will stream staging to PostgreSQL.

### Next

M3: persistence of imports, runs, findings and issues; jobs; audit hash chain; read APIs.

---

## M3 — Persistence, ingestion, runs, audit

Status: **Complete** (commit `feat: add migration persistence and pipeline`). Decisions: [decisions/0004-persistence-and-pipeline.md](decisions/0004-persistence-and-pipeline.md).

### Built

- **Schema** (Alembic `0002_persistence`, 29 tables): identity, workspace (companies, migrations with conversion plans, source systems, datasets, policy versions), imports (stored files, imports, append-only source and quarantined rows, profiles), column mapping sets, change requests and approvals, pipeline results (runs, rule runs, exceptions, reconciliation results, lines and items, entity candidates, readiness evaluations, gate results, staged records), issues and occurrences, hash-chained audit events, jobs. Triggers: append-only (UPDATE, DELETE, TRUNCATE) on source rows, quarantined rows and audit events; segregation of duties on approvals.
- **Services**: audit writer and chain verification; content-addressed blob store; uploads (size limit, extension and content sniffing, file name sanitizing, idempotency, supersession, audited activation); parse job with profiling; column mapping drafts; change request core with the `column_mapping_set` applier; pipeline request (idempotent on fingerprint) and execution (engine over verified import bytes, `COPY` persistence, issue synchronization, readiness); PostgreSQL job queue with `SKIP LOCKED`; `relay worker`.
- **Read models and API** (28 paths, dev identity only in local/test): me, dev users, migrations, datasets, readiness, issues, audit events and verification, entity candidates, imports (upload, rows, quarantine, profile), pipeline runs and fingerprint, rule runs, exceptions, reconciliations, lines, drill-down (R1/R2 by account, R3/R4 by document with lineage, R5 reconciling items, R6 quarantine), records with source rows, rule catalog. OpenAPI committed at `web/src/lib/api/openapi.json` with a drift test.
- **Commands**: `relay worker`, `relay verify-audit`, `relay-demo seed`; `make worker`, `make demo-seed` (inside Compose), `make demo-seed-host`, `make verify-audit`, `make openapi`. Compose runs a `worker` service with a heartbeat healthcheck, sharing a blob volume with the API.
- **Evaluation**: `relay_evaluation.brightwater.persisted` rebuilds a comparable result from database rows only.

### Verified

| Check | Result |
|---|---|
| Persisted Run #1 (database rows only) vs golden manifest | 89 / 89 |
| Persisted failing gates | G1, G3, G5, G6, G7, G8, G9, G10, G12 (= manifest) |
| R3 `C-0233` drill-down | `INV-10877` `left_only`, lineage to the GL export row `JE-AR-10877` |
| Audit chains after seeding | valid (migration and platform); tampering detected at the exact sequence |
| Append-only triggers, self-approval trigger, SKIP LOCKED, idempotent uploads and runs, inputs-changed failure, upload limits, path traversal, production refusal of dev identity | integration tests pass |
| Compose stack (db, migrate, api, worker, web) | `make up` healthy, `make smoke` OK, `make demo-seed` inside Compose; API readiness, R3 drill-down, record lineage and audit verification checked over HTTP and with `relay verify-audit` in the worker container |
| `make check` | passed: 631 backend unit and scenario tests, 59 integration tests, 22 web tests, 4 import contracts, 115/115 manifest facts |

### Measured

Day-9 Brightwater seed on the development machine (Apple M2, local Compose PostgreSQL): about 6 s end to end. Pipeline run: load 0.08 s, engine 1.07 s, persistence 1.5 s (24,472 staged records, 65 findings, 1,704 reconciliation lines), issues 0.37 s, total 3.1 s. Before switching to `COPY`, persistence took 10.1 s.

### Changed from the plan, and why

See decisions P-01 to P-18. The most visible: one semi-typed staged records table; uploads as request bodies; account mapping remains an imported dataset until M5; no overlay tables until their change request kinds exist; the demo seed is `relay-demo seed` (demo tooling may not live in the runtime CLI, D-15).

### Known limitations and debt

- Upload bodies are buffered in memory (bounded by the upload limit) before spooling.
- Long pipeline runs do not heartbeat (P-18).
- Readiness is not re-evaluated when governance state changes between runs (P-14).
- Run retention and pruning (architecture §4.4) are not implemented.
- Local development databases seeded more than once contain one migration per seed (the seed does not deduplicate migrations).

### Next

M4: web shell and evidence views over this API.

---

## M4 — Web shell and evidence views

Status: **Complete** (commit `feat: build Relay evidence workspace`). Decisions: [decisions/0005-web-evidence-workspace.md](decisions/0005-web-evidence-workspace.md).

### Built

- **Shell**: development user switcher (HTTP-only cookie set by a Server Function), portfolio, migration navigation, skip link, error boundary.
- **Views**:
  - Overview: readiness banner, blockers with evidence links, amount at risk, my queue, pipeline stages, recent activity
  - Data: datasets, imports, row viewer anchored to a row, quarantine with raw text, profile
  - Runs: list, fingerprint, counts and stage timings, diff between runs
  - Validation: rule runs and findings
  - Reconciliation: results, lines with status filter, drill-down by basis (documents with source lineage, accounts with date/period disagreements, reconciling items, quarantined rows)
  - Record inspector: source row in file column order with line numbers, canonical record, related issues
  - Issues: filters and ordering by amount; read-only detail with subjects, latest finding and lineage
  - Readiness: gates with typed evidence links
  - Audit log: filters, before/after, chain verification
- **Shared components**: `Money` (server strings, parentheses for negatives, currency always shown), `BusinessDate`, `Timestamp` (local time with UTC on hover), `StatusChip` (icon and text), `RecordRef`, `SourceLocation`, `DataTable`, `EvidenceLink`, filter forms.
- **API additions** for the UI (decision W-05), generated TypeScript types (W-06).
- **Tests**: Playwright E2E-1 with axe accessibility checks (`make test-e2e`, also in CI after the smoke test); web unit tests for formatting, URLs, API type drift and the no-money-arithmetic guard; backend integration tests for overview evidence links and run diff.

### Verified

| Check | Result |
|---|---|
| E2E-1 against the Compose stack with seeded Brightwater | passed. Overview shows NOT READY with 9 of 12 gates failing (G1, G3, G5–G10, G12); `R3:party=C-0233` leads to `INV-10877` left only, then to the record inspector with the GL source row `JE-AR-10877` and its line number |
| axe (WCAG 2 A/AA, serious or critical) on Overview, drill-down, record inspector, Reconciliation | 0 violations |
| Lighthouse 13.1.0 accessibility, local headless Chrome, final build | Overview 100, Reconciliation 100, no failing audits |
| No money arithmetic in `web/` | guarded by a test |
| `make smoke` against the rebuilt stack | OK (status page moved to `/status`) |

### Known limitations and debt

- The CI E2E step relies on Chrome being preinstalled on the GitHub Ubuntu runner; it has not run in CI yet.
- Entities, Mappings, Approvals and Settings views are not built (M5–M7 scope).
- Issue detail is read-only; ownership and workflow transitions arrive with M6.
- Dates on the portfolio's "days to go-live" use the server's UTC date. The Brightwater go-live date (2026-07-01) is in the past relative to the development machine's clock, so the value is negative.

### Next

M5: mappings, change requests and approvals in the UI and API.

