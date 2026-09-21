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

---

## M5 — Mappings, change requests, approvals

Status: **Complete** (commit `feat: govern mappings and record corrections with approvals`). Decisions: [decisions/0006-governed-changes.md](decisions/0006-governed-changes.md).

### Built

- **Schema** (Alembic `0003_governance`): `account_mapping_sets`, `account_mappings`, `record_overrides`; change request kind `revert`; mapping set status `abandoned`.
- **Engine**: optional governed account mapping that replaces the mapping file's pairs (G-01); shared `subtype_conflict` test used by the rule and by the mapping signals.
- **Change request framework** (`relay.changes.kinds`, `relay.changes.service`): kinds `column_mapping_set`, `account_mapping_set`, `record_override` (canonical field or quarantined row repair), `policy_change`, `revert`; server-computed before, after, impact and required approvals; segregation of duties; staleness checks on review and a sweep after every application; withdraw; draft edits with optimistic versioning; every transition audited with before and after.
- **Pipeline**: active overrides and repairs become engine overlays; the approved account mapping set feeds runs and gate G3; override payloads are resolved from run evidence (`relay.pipeline.overrides`).
- **Mappings**: canonical field registry, deterministic column mapping suggestions and 50-row preview, account mapping suggestions with compatibility signals.
- **API** (`/api/v1`): column mapping sets, suggestion and preview; account mapping overview, sets and drafts; change requests (list, create, get with requirements, approvals, viewer eligibility, history and triggered runs; update, submit, approve, reject, withdraw); record overrides. Approving the last requirement applies the change and requests a run in the same transaction.
- **Web**: Mappings (account mapping with signals, suggestions and a proposal form; column mapping per dataset with suggestion, JSON editor, preview and proposal), Approvals queue, change request detail (per-kind before/after, requirements, approve and reject only when eligible, withdraw, history, runs), Overrides with revert, correction form in the record inspector (journal entry date and period), repair form on quarantine issues.
- **Seed**: account mapping set version 1 drafted by Maya from the mapping file and approved by Daniel and Priya.
- **Tooling**: `make demo-reset` recreates and reseeds the local database (E2E tests change demo state); `make test-e2e` passes the API URL to Playwright.

### Verified

| Check | Result |
|---|---|
| E2E-2 in Playwright against the Compose stack | passed: Maya proposes 1205 → 1210 on the Mappings page; no approve button for her and the API returns 403; Daniel's approval leaves it submitted; Priya's applies it and requests a run; `R3:party=unassigned` is gone from the blockers while `R3:party=C-0233` remains; the mapping issue is resolved |
| DS-05, DS-08, DS-11 through the UI (Playwright) | passed: two entry-date corrections from the record inspector and one row repair from the quarantine issue, each approved by lead and controller; after the rerun all three issues are resolved; three overrides active |
| axe on Mappings and change request pages | 0 serious or critical violations |
| API integration (`tests/integration/test_governance.py`, 11 tests) | SoD (requester and lead's own change), E2E-2 at the API, competing account mapping changes (the loser becomes stale and cannot be approved; its set is abandoned), DS-08 and DS-11 overrides, DS-05 repair, revert reopens the DS-11 issue, policy change creates a policy version and changes the fingerprint, every change request transition audited with before and after |
| Persisted run after the API corrections vs the pure engine with the documented resolutions (`relay_evaluation.brightwater.resolution`) | equal rule counts, finding subjects and reconciliation differences |
| Brightwater Run #1 persisted with the governed mapping version 1 | still matches the golden manifest (89/89) |
| Column mapping suggestions vs Brightwater version 1 mapping | 112 of 126 fields use the same source column; 73 identical specifications (G-09) |

### Changed from the plan, and why

- The account mapping file remains a dataset; version 1 of the governed set is drafted from it (G-01).
- G11 no longer counts stale change requests (G-06). *Reverted in M6 (0007 I-12): it contradicted governance.md.*
- Approval policy is fixed in code rather than stored in the policy document (G-04).
- The column mapping editor is a JSON text area, not a field-by-field form (G-12).

### Known limitations and debt

- Legacy accounts present only in the GL are not listed on the Mappings page (DS-12 is M6 scope).
- Overrides cover journal entry dates and periods only.
- E2E tests need a fresh seed (`make demo-reset`) to run twice.
- No bulk approvals.

### Next

M6: issue workflow, entity decisions, dispositions, re-imports and the new-migration flow.

---

## M6 — Issues workflow, entity resolution, dispositions, re-imports

Status: **Complete** (commit `feat: add issue workflow, entity decisions and dispositions`). Decisions: [decisions/0007-issue-workflow-and-decisions.md](decisions/0007-issue-workflow-and-decisions.md).

### Built

- **Schema** (Alembic `0004_issue_workflow`): `entity_decisions`, `dispositions`, `issue_links`, `issue_comments` (append-only trigger).
- **Issues**: owner and status workflow with version checks, manual issues, comments, history, system `same_root_cause` links, `awaiting_verification` and `verification_failed`.
- **Change request kinds** `entity_decision` and `disposition` (one or more issues); `revert` for every overlay; active entity decisions and dispositions feed runs.
- **API**: `PATCH /issues/{id}`, `POST /migrations/{id}/issues`, issue comments, links and history, `rule` and `owner` issue filters, entity decisions, entity candidate detail with staged parties, dispositions, `POST /migrations`, source systems, datasets.
- **Web**: issue workflow, comments, links and history on the issue page; disposition proposal for one or several issues; Entities list and side-by-side candidate decision page; Overrides page with entity decisions and dispositions and revert for each; dataset page with import history and upload; run request buttons; New migration and Setup pages; manual issues.
- **Fixtures**: `fixtures/demo/brightwater_reexport/` (unfiltered exports for DS-04, DS-09, DS-12).

### Verified

| Check | Result |
|---|---|
| Playwright on a freshly seeded stack | E2E-1, E2E-2, DS-05/08/11, **E2E-3** (identical upload changes nothing; three corrected exports become active imports; the rerun has no R3b discrepancy and the orphan payment issue is resolved), **E2E-4** (merge V-1042/V-1187 through the Entities page → rerun → `AP.DUPLICATE_BILL` open → carry-forward disposition by the controller only → dispositioned, exposure lower), **DS-06 and DS-10** (distinct store decision; one disposition for six bank fees), **E2E-8** (new migration, upload, suggested mapping, lead approval, run, `NORM.DUPLICATE_NATURAL_KEY` issue) |
| API story (`test_issue_workflow.py`, 10 tests) | workflow rules and version conflicts; comments immutable in the database; manual issues; system links; re-imports; DS-01 merge reveals DS-02; DS-06; mapping, overrides, repair and dispositions for DS-03, DS-05, DS-07, DS-08, DS-10, DS-11, DS-12, DS-13; **the final persisted run equals the pure engine with the documented resolutions** (rule counts, finding subjects, reconciliation differences) and only G12 (sign-off) fails, with exposure 0.00; reverting a disposition reopens its issue |
| API E2E-8 (`test_new_migration.py`) | passes, including 422 for an invalid issue key prefix |
| Staleness and G11 | a stale request keeps G11 failing until withdrawn (governance.md) |
| Concurrency | an approval racing a running pipeline no longer deadlocks (regression test reproduced the deadlock before the fix); database sessions commit before the response is sent |
| `make check` | 652 unit and scenario tests, 84 integration tests, 37 web tests, 115/115 manifest checks, 22 fixture files match generation |

### Known limitations and debt

See 0007. Readiness is not re-evaluated between runs; no survivorship per field; transitive entity contradictions are not detected; owner selection uses the development user directory.

### Next

M7: readiness gates, waivers and sign-off.

---

## M7 — Readiness gates, waivers, sign-off

Status: **Complete** (commit `feat: add readiness waivers and sign-off`). Decisions: [decisions/0008-readiness-waivers-signoff.md](decisions/0008-readiness-waivers-signoff.md).

### Built

- **Engine**: gate scopes for waivable gates; scope-bound waivers that lapse; gate set version 2.
- **Schema** (Alembic `0005_readiness`): `gate_waivers`, `readiness_signoffs`, repeated readiness evaluations per run with a trigger, gate scopes, the `evaluate_readiness` job kind.
- **Change request kinds** `gate_waiver` and `readiness_signoff`, resolved from the current run; revert for waivers; sign-off invalidation; waiver lapse; migration status `signed_off`.
- **Pipeline**: readiness re-evaluation job; shared change request orchestration (`relay.pipeline.approvals`) used by the API, the seed and the fast-forward tool.
- **Demo**: `relay-demo fast-forward --to before-signoff`, `make demo-fast-forward`.
- **API/Web**: readiness with scopes, waivers, sign-offs, migration status and evaluation details; Readiness page with waiver proposals and sign-off request; policy endpoint and Settings page.

### Verified

| Check | Result |
|---|---|
| Playwright on a freshly seeded stack | 9 of 9, including **E2E-5**: fast-forward (skipping steps earlier specs already applied) → sign-off by lead and controller → READY, migration signed off → policy change through Settings → new run → sign-off invalidated, not ready |
| API (`test_readiness.py`, 5 tests) | fast-forward reaches "only G12 fails", exposure 0.00, and is idempotent; sign-off refused while another change is pending; sign-off makes the migration ready on the same run (evaluation sequence > 1); reverting two dispositions invalidates the sign-off (audited) and fails G8; waivers refused for gates that are not failing; G8 waiver applies; dispositioning one waived item lapses the waiver (audited) |
| Engine scenario test | a scope-bound waiver survives the DS-01 merge (new fingerprint, same ledger scope) and lapses after the DS-08 correction (waived R1 amounts change); non-waivable gates never waive |
| `make check` | 654 unit and scenario tests, 89 integration tests (230 s, including readiness re-evaluation jobs), 37 web tests, 115/115 manifest checks |

### Known limitations and debt

See 0008: no waiver expiry; readiness re-evaluation reruns the engine; approvals wait for a running pipeline.

### Next

M8: the AI investigation layer.

---

## M8 — AI investigation layer

Status: **Complete except the live eval run** (commit `feat: add AI investigation layer`). Decisions: [decisions/0009-ai-investigation-layer.md](decisions/0009-ai-investigation-layer.md).

### Built

- **Providers** (`relay.ai.providers`): `disabled` (default), `scripted` (replays authored transcripts; can reference earlier tool results), `anthropic` (Messages API over the standard library, key only in the header, retries on 429/5xx). Settings `RELAY_AI_PROVIDER`, `RELAY_AI_MODEL`, `ANTHROPIC_API_KEY`, `RELAY_AI_SCRIPTS_DIR`, budgets.
- **Tools** (`relay.ai.tools`): 15 read-only tools over read models, scoped to the investigation's migration and pinned run, with redaction, truncation and untrusted-data wrapping, plus the terminal `submit_findings`.
- **Investigator loop** with tool-call, wall-clock, token and result-size budgets; argument errors returned to the model; one reminder to submit.
- **Findings**: closed schema of suggested actions, provenance verification (verified / partially verified / failed), server-computed `requires_approval` and `draftable`.
- **Persistence and governance** (`relay.investigations`, Alembic `0006_investigations`): investigations, steps, findings; `SET TRANSACTION READ ONLY` tool sessions; consent through `policy_change` `ai_enabled`; `run_investigation` jobs; review (accept/dismiss); operator-owned draft change requests with `origin_finding_id`.
- **API**: `GET /ai/status`, investigations (start, list, detail), finding accept/dismiss/draft-change-request.
- **Web**: Investigate panel on the overview and issue detail (only when AI is available), investigation page with the AI label, verification badges, per-evidence checks, review, draft buttons and a plain-text transcript (`components/ai-finding.tsx`).
- **Evals** (`relay_evaluation.ai`): E1–E6 with scripted transcripts and scoring (root cause, fabricated references, injection violations) plus a hallucinating negative control; `relay-eval ai`, `make eval-ai-scripted`, `make eval-ai` (manual, live).

### Verified

| Check | Result |
|---|---|
| Playwright on a freshly rebuilt and seeded stack (`RELAY_AI_PROVIDER` unset, so disabled) | 10 of 10, including **E2E-7**: no Investigate panel or AI label on the overview and issue detail, `/ai/status` unavailable, starting an investigation refused (409); every other flow passes in the same mode |
| AI unit tests (`tests/ai`, 12) | Anthropic request shape with the key only in the header; retries on 429 and failure on 4xx; disabled and scripted providers; redaction; loop numbering, argument errors returned to the model, tool-call and wall-clock budgets, one reminder then failure, provider errors; verification of cited references and normalized numbers; fabricated references and missing steps caught; injection scoring |
| Promotion policy (`tests/unit/test_finding_promotion.py`, 6) | verified and partially verified change suggestions are draftable; failed, dismissed, no-change and `request_reimport` findings are not |
| API/DB (`tests/integration/test_ai.py`, 6) | AI off by default; a write inside a tool session raises in PostgreSQL; all 15 tools answer in a read-only session and only in scope; consent is an approved policy change that requests no run; scripted E1–E5 root cause 5/5, 0 fabricated references, 0 injection violations, and the hallucinating control fails verification; a verified finding drafts an operator-owned change request (viewer 403) and is then no longer draftable; a **failed finding cannot be accepted or drafted (409)** and no change request references it |
| Web unit (`components/ai-finding.test.tsx`, 3) | hostile model and data text rendered escaped; verification states in words, with failed evidence problems; no buttons, forms or links inside AI components |
| Manual, scripted provider against a scratch database with production web build | issue BWP-41 → Investigate → job → findings with badges and transcript → draft CR "Map 1205 to 1210" with provenance in its history; `request_reimport` finding has no draft button; failed control finding collapsed with no Accept/Draft and dismissible |
| `make eval-ai` without a key | refuses: "ANTHROPIC_API_KEY is not set; a live eval was not run." |
| `make check` | 673 unit and scenario tests, 95 integration tests (235 s), 40 web tests, 115/115 manifest checks, 6 import contracts kept |
| `make verify-audit` after E2E | all chains valid |

Found during verification: `test_database.py`'s migration round trip shared the test database with `test_ai.py`, whose drafted change requests (correctly) block the 0006 downgrade. The round-trip and readiness-probe tests now use a dedicated empty database; the guard is unchanged.

### Not done

- **Live eval run**: no provider key was available, so the acceptance item "live eval run recorded" is not met. `make eval-ai` refuses without a key (checked). See `evals/results/README.md`.
- Mapping suggestion tasks (ai-safety.md §5): cut per implementation plan cut line 2.

### Known limitations and debt

See 0009: `sent_fields` is not a field-level inventory; the scripted provider reports no tokens; investigations are not marked stale when newer runs exist. In `next dev`, a form submitted before hydration is rejected (`Origin: null` under `Referrer-Policy: no-referrer`); production builds are unaffected.

### Next

M9: hardening and demo rehearsal.

---

## M9 — Hardening and demo rehearsal

Status: **Complete.** Decisions: [decisions/0010-m9-hardening.md](decisions/0010-m9-hardening.md).
Requirement traceability: [traceability.md](traceability.md).

### Built so far

- **Security review** of every requirement ID against the code, written up in `docs/traceability.md`.
  Fixes: nonce-based CSP on the web and a deny-everything CSP on the API (SEC-15), per-person upload
  rate limiting (SEC-17), a 512-column CSV header limit (SEC-01), bound parameters in the AI
  read-only session's statement timeout (SEC-13), a route inventory test for default deny and
  governed mutations (SEC-10, GV-01), static guards for SEC-04/13/23/30/31/32, an audit-chain
  property test (GV-06), an applier failure-injection test (GV-04), a draft concurrency test (GV-08)
  and CI running the whole suite under `TZ=Australia/Adelaide` (FC-06).
- **Engine correctness**: a rule or reconciliation that raises is recorded as an errored stage and
  fails G4 instead of destroying the run (FC-10, Alembic `0007_errored_stages`); a reconciliation
  line refuses to explain more than its difference (FC-11).
- **Performance**: `make pipeline-perf` measures the persisted pipeline end to end; gate evidence
  now resolves only the lines it names.
- **E2E-6** (audit trail) and a CSP end-to-end check.

### Measured (this machine: Apple M2, 8 cores, 16 GB, macOS 14.5, Python 3.12.10, Compose PostgreSQL 16)

One run of `make pipeline-perf` on a synthetic clean 250,000-line migration (620,890 staged records,
50.8 MB of source files), loaded through the same services as the demo seed:

| Phase | Measured |
|---|---|
| Seed (users, 16 uploads, parse jobs, approved mappings, first run) | 168.9 s |
| Import parsing | 22.1 s total, slowest file 12.0 s |
| Run #1 | load 0.2 s, engine 53.3 s, persist 74.7 s, issues 0.01 s (total 128.2 s) |
| Governed policy change and its rerun | 146.9 s (engine 64.7 s, persist 80.3 s) |
| Readiness re-evaluation (reruns the engine) | 47.8 s |
| Peak RSS (whole process, including generation) | 1,520 MiB |

Read endpoints at that size, in process, median of 5 (before → after the evidence fix):

| Endpoint | Median |
|---|---|
| Overview | 0.80 s → about 0.12 s |
| Readiness | 5.83 s → about 0.09 s |
| Issues, datasets, reconciliations, rule runs, run diff, audit page, chain verification | 7–24 ms |
| Reconciliation lines (first page of 100), drill-down, record inspector | 17–101 ms |
| Source rows (pages of 200) | 13–25 ms |

The after figures were measured on a 60,000-line migration with the same tool and profiler; the
before figures are from the 250,000-line run. A clean synthetic migration produces no findings, so
issue-heavy reads are not represented.

### Verified

| Check | Result |
|---|---|
| `make check` | 1,008 unit and scenario tests, 99 integration tests, 43 web tests, 115/115 manifest checks |
| Whole suite under `TZ=Australia/Adelaide` | 892 unit, 99 integration, 115/115 manifest |
| E2E-6 and the CSP check against the running stack | pass |
| `make test-all` (checks, stack build, smoke, reseed, end-to-end suite) | passed in 10 min 19 s |
| Walkthrough rehearsal: `make demo-reset` then the full end-to-end suite, twice in a row, no manual database edits | 2 min 53 s and 3 min 4 s, 12 of 12 specs both times |

The rehearsal times the *mechanics* of the walkthrough — the same steps the demo takes, driven by
Playwright. A person narrating it was not timed, and no claim is made about that.

- **Portfolio**: `make demo-portfolio` (`relay-demo seed-portfolio`) adds two more fictional
  migrations through the same services — Harborline Supply Co. (clean books, every gate passing,
  signed off by the lead and the controller) and Northwind Timber Co. (files uploaded and profiled,
  nothing mapped or run). The synthetic generator takes a company name, and the seed can stop after
  imports.
- **README** rewritten as a demo-led guide with screenshots of the real seeded state
  (`docs/images/`), and `make test-all` (checks, stack, smoke, reseed, end-to-end suite).

### Status

M9 is complete. Requirement traceability, the retrospective below, and the acceptance commands
(`make test-all`, the twice-run rehearsal) are all in place. What was deliberately not built is
listed in `docs/traceability.md` and decision 0010.

---

## Review passes (after M9)

Six independent passes over the finished system, each from a different point of view. Findings and
what was done about them: [review-findings.md](review-findings.md).

| Pass | Result |
|---|---|
| 1 — accounting correctness | **Seven genuine defects**, all fixed with tests and none changing the golden manifest: R6 could not detect a lost source row; open items "at cutover" included later-dated documents; three FX conversions rounded the wrong way; a dispositioned critical passed G5; R2 lost the opening balance on a sparse trial balance; an aging row whose sign contradicted its kind was flipped silently; losing a whole journal entry was reported as `high` with no amount. Added `TB.PERIOD_COVERAGE` and four date-window rules |
| 2 — adversarial | **One defect**: amounts and dates written in non-ASCII digits parsed (mixed scripts included). Sixteen attacks held and became regressions (`test_adversarial.py`) |
| 3 — anti-cheating | Runtime clean. The boundary scan itself was too narrow: it now covers the migrations and the web app across every product file type, which immediately found two demo amounts in a web test |
| 4 — code quality | Dead drill-down duplicating the live one, three other dead functions, an N+1 behind the portfolio (444 ms → 184 ms), a full scan for a primary-key lookup, duplicated `links_for`, divergent ordering, a failed job losing its traceback, and a sleep-based test that could pass vacuously |
| 5 — UX | Runs superseded rather than failed (Alembic `0008`), owner on the issues list, issue titles that read as English, formatted gate amounts; and a queueing limitation found under load, recorded with two candidate fixes |
| 6 — documentation | README verified from a **fresh clone** with only the documented commands; the shared Compose project name documented; four documents still said "Planned", architecture and data-model had drifted from the schema, and the rule catalog and action taxonomy were out of date — all corrected |

Commits: `856978c` (passes 1–2), `5971bda` (passes 3–4), `41b9d85` (pass 5), `3e28b49` (pass 6).
Verification after each: `make check` green (1,034 unit and scenario, 115 integration, 43 web,
115/115 manifest checks) and, for passes 5 and 6, 12 of 12 Playwright specs on a freshly seeded
stack.

---

## Second company — the generalization test

Brightwater's manifest proves the engine agrees with a specification on Brightwater. It cannot prove
the engine did not *learn* Brightwater. So a second fictional company was built and the same runtime
engine, unchanged, was pointed at it: **Kestrel Instruments Ltd**, a precision instrument workshop
exporting from Tallyworks 9 — semicolon-delimited UTF-8 with a byte-order mark, `DD.MM.YYYY` dates,
`1.234,56` amounts, one signed GL amount column, EUR functional with USD suppliers, a July fiscal
year, rows ordered by account and documents descending by number, six planted defects and three
benign look-alikes. Nothing is shared with Brightwater: not a party, an account, an amount, a date,
a file name or a defect. Its expectations (`evaluation/kestrel/expected.toml`) were hand-authored
from the defect definitions and the reconciliation specification before the engine ever ran.

### Built

- `relay_scenarios/kestrel/`: clean books (`books.py`), the legacy export format (`exports.py`), the
  six defects (`defects.py`), and the scenario assembly with its migration descriptor and checksums.
- `fixtures/demo/kestrel/` (17 source files) and `fixtures/demo/kestrel_config/` (the approved
  column mapping set for them — 16 datasets, semicolon, `utf-8-sig`).
- `evaluation/kestrel/expected.toml` and `relay_evaluation/kestrel/verify.py`: 31 expectations.
- `relay-demo generate-kestrel` / `check-kestrel`, `relay-eval verify-kestrel`, three `make` targets,
  and `tests/scenario/test_kestrel.py`. `make check` runs the fixture check and the verifier.

### What it found

Six disagreements on the first run, each classified before anything changed
([0011](decisions/0011-second-company-generalization.md)): **three manifest bugs** (a consequence of
the mapping defect the manifest had missed, a second rule that fires on the same account, and a
severity I guessed instead of reading from the catalog — all corrected against the specification and
annotated in place) and **three engine bugs**, all fixed generally:

- R5 could explain *more* than the cash difference, because ledger movements the statement never
  shows were not modelled at all — only the bank-only side was. FC-11 refused the line, correctly.
  New `ledger_only_movement` items with a `BANK.UNMATCHED_LEDGER_MOVEMENT` finding; G8 blocks on
  both sides.
- R6 tied while a quarantined row was unaccounted for: a row that names no period belonged to no
  line and vanished from the control. It is now reported on a `period = "unreadable"` line.
- `parse_period` accepted only `MM/YYYY` and `YYYY-MM`; it now also accepts `MM.YYYY` and `YYYY/MM`.

One existing unit test (`test_payment_that_never_clears`) encoded the R5 bug. It was rewritten from
§B.4 rather than deleted: the payment is now identified as a named item with its own finding, and
G8 still fails — identifying a difference is not excusing it.

### Verified

- `make check` green on this machine after the change: 1,041 unit and scenario tests, 115 integration
  tests against real PostgreSQL, 43 web tests, 115 of 115 Brightwater manifest checks, 31 of 31
  Kestrel expectations, 22 Brightwater and 18 Kestrel fixture files byte-identical to a fresh
  generation.
- 31 of 31 Kestrel expectations, on the unchanged runtime engine: clean books produce no finding, no
  reconciliation discrepancy and no errored stage; all six defects are caught by general rules and
  controls; no finding beyond the manifest; the benign look-alikes stay silent.
- Brightwater's golden manifest still passes 115 of 115 after the three engine changes. It has never
  been edited to match output.
- Kestrel's identifiers joined the anti-cheating scan: `relay.*`, the migrations and the web app
  contain none of them.
- 12 of 12 Playwright specs on a rebuilt, freshly reseeded stack: the three engine changes did not
  disturb the Brightwater walkthrough, its governed changes or its sign-off.

---

## Product-quality pass (after the second company)

The system was validated but the interface still read like an engineering console: an `sr-only` page
title on the most important screen, blockers rendered as bulleted link dumps, no visual hierarchy
between a gate failing and a timestamp, and no shared design layer — every page styled itself with
utility classes.

This pass changes presentation and documentation only. No accounting behaviour, no golden truth, no
engine change. Plan, in priority order:

1. **A real design layer.** Tokens in `globals.css`; shared primitives (page header with
   breadcrumbs, section, metric card, callout, table, filter bar, buttons, empty state, definition
   list, diff table, provenance badge) so pages compose instead of restyling.
2. **App shell.** Migration identity and cutover context in the sidebar, grouped navigation with an
   active state, so the workflow is legible from the chrome alone.
3. **Overview.** The screen a reviewer sees first: identity → readiness → exposure (defect vs
   anomaly) → structured blockers (gate, observed, impact, top evidence, count, path to inspect) →
   operator queue → pipeline → activity.
4. **Reconciliation.** Say what each control compares in plain English; make "explained" visibly
   different from "accepted" (R5 ties and still fails G8).
5. **Provenance.** Label SOURCE vs CANONICAL vs DERIVED so a transformed value can never be mistaken
   for customer evidence.
6. **Governance.** Make the separation of detection / judgement / approval / execution visible, and
   fix the two known defects (`rejectd`, raw issue UUIDs).
7. **GV-05.** Observational instrumentation proving governed mutations are audited, with the
   governed set and every exemption written down.
8. **Documentation.** Correct the SEC-25 overstatement in governance.md, rewrite the README opening,
   add an architecture diagram and `docs/demo-guide.md`.

### Built

- **A design layer** (`web/src/app/globals.css`, `web/src/components/ui.tsx`): tokens for surfaces,
  ink, accent and semantic states, and the primitives every page now composes — page header with
  breadcrumbs, section, panel, metric card, callout, empty state, metadata list, buttons. Two
  product-specific primitives carry real meaning: `ProvenanceBadge` (Source / Canonical / Engine
  result) and `GateStrip` (all twelve gates at a glance).
- **A shell that explains the workflow**: grouped navigation with an active state, and the company,
  cutover, go-live and functional currency in the chrome.
- **A rebuilt overview**: identity → readiness → exposure split by nature → structured blockers with
  a direct action per gate → operator queue → pipeline → activity.
- **Reconciliation explained in prose**, including the R5 callout that identified is not excused.
- **Provenance made explicit** on the record inspector and the import viewer.
- **Governance framed as a feature**: what a change request has and has not done yet, who must
  approve, why you cannot approve your own, and what a waiver or sign-off is bound to.
- **GV-05 instrumentation** (`relay.audit.instrumentation`), see below.

### Fixed

| Defect | Was | Now |
|---|---|---|
| Rejected approvals | rendered `rejectd` (the page appended "d" to the raw decision value) | an explicit approved/rejected chip |
| Related issues on a record | raw UUIDs | issue key, severity and status — the router already loaded the issues and threw them away |
| "Which run am I reading?" | reconciliation and validation never said | a run marker in the header of both, with current/stale |
| Money arithmetic in the browser | — | the FC-15 guard caught two new violations during this pass (`Number(...)`, `Math.abs`); both rewritten |

### Deliberately not changed

- No accounting behaviour, no rule, reconciliation or gate logic, no golden truth. Brightwater still
  passes 115/115 and Kestrel 31/31.
- No new product scope: no page was added beyond what already existed, and nothing was hidden.
- SEC-25 (separate database roles) stays unimplemented; only the documentation that overstated it
  was corrected.

### GV-05 instrumentation

`backend/src/relay/audit/instrumentation.py` classifies all 41 mapped tables (25 governed, 16
operational, each exemption with its reason in the code) and registers SQLAlchemy listeners that
fail any transaction which mutated a governed table without inserting an `audit_events` row. An
autouse fixture in `tests/integration/conftest.py` installs it for the whole integration suite, so
its 121 tests are the evidence. It observes only: it never writes, never creates an event, takes no
lock, and nothing installs it in a production path.

The claim is narrow, and the docstring says so: *a transaction that mutated governed state also
wrote an event* — not that the event describes the right row, actor or action, which each flow's own
assertions cover. It watches the ORM unit of work, so raw `COPY` writes (`core.db.copy_rows`) are
invisible; every table written that way is classified exempt anyway.

Two things the first run surfaced, both recorded rather than papered over:

- `test_database_rejects_self_approval` builds a change request and an approval by hand to exercise
  the segregation-of-duties trigger — no service, so no event. It now calls
  `instrumentation.bypass_check` with a comment; the test itself is unchanged.
- `investigations` is exempt, not governed: the worker flips an investigation to `running` in its
  own transaction without an event (`investigation.requested` and `investigation.finished` bracket
  it). Adding an event would have been a behaviour change, so the exemption states the reason.

`tests/unit/test_audit_classification.py` fails if a future table is neither governed nor exempt;
`tests/integration/test_audit_instrumentation.py` proves the check can fail (unaudited insert,
update, and ORM bulk update) and that exempt job-queue writes pass.

---

## Productization pass

The system was correct and the interface had been cleaned up, but Relay still asked its user to
think like its author: gates, reconciliation ids, rule ids, and a list of sixty-five findings that
nobody had turned into a day's work. This pass changed what the product *is about* without changing
what it computes.

### What changed

- **A work queue, server-side** (`relay.pipeline.work_queue`, `GET /migrations/{id}/work-queue`).
  Findings become decisions: what happened, why it matters, how much money, what only a person can
  decide, and where to act. On Brightwater, 65 findings become 20 decisions.
- **The strongest decision is composed, not scripted.** When a reconciliation attributes a
  difference to exactly one legacy account (the engine's `single_account_contribution` explainer)
  and that account's mapping is one the compatibility check doubts, the two become a single item
  carrying the difference. The module names no company, account or amount; the second company
  produces the same shape of item from its own defect (a −6,500.00 contribution attributed to its
  own mis-mapped account).
- **An automation summary** counted from what the run stored — records normalized, controls run,
  reconciliations performed, findings raised — so the product shows what it did rather than
  implying a human typed it in.
- **An implementation command center**, an overview built around "can this customer go live?", a
  lifecycle derived from run data, readiness restated as six operator questions (G1–G12 kept
  underneath), governed change presented as proposed → approved → applied → re-verified, and
  investigation in plain language with the exported row beside Relay's normalized reading.

### What did not change

The engine, the rules, the reconciliations, the gates, the golden truth. Brightwater still passes
115/115 and Kestrel 31/31. No runtime code branches on scenario knowledge — the anti-cheating scan
caught a Brightwater customer code in a docstring of the new module during this pass, which is
exactly what it is for.

### Honest limits of the new work queue

- It groups by cause, not by root cause: two items can share an underlying defect (a mapping problem
  also raises its own finding, which is suppressed, but a knock-on reconciliation difference in a
  different control is still listed separately).
- Its ordering is blocking-first, then amount, then count. An item with no amount sorts below small
  amounts even when it needs more thought.
- "Blocks go-live" is computed by intersecting an item's evidence with failing gates' evidence, so
  items whose evidence a gate does not record (approvals, unreadable rows) show no gate even when
  they matter.

---

## Deployment preparation

Configuration only, on request: nothing was deployed and nothing was published. Added
`docker-compose.prod.yml` (an overlay on the development stack, not a replacement),
`.env.production.example`, `make prod-config`, and `docs/deployment.md`.

What the overlay changes: `RELAY_ENV=production`; database, user and password required with no
defaults; the database and API no longer published to the host; the `./fixtures/ai-scripts` bind
mount dropped so no repository path is needed at runtime; restart policies, memory and CPU limits,
JSON log rotation, and a worker stop grace period. It uses the Compose `!reset` and `!override`
merge tags, so it needs Compose 2.24+ (validated on 2.35.1). `!override` on `environment:` is
load-bearing: a merged map would carry `RELAY_AI_SCRIPTS_DIR` into a deployment and point the AI
provider at demo transcripts.

Verified by bringing the overlay up in an isolated Compose project (`relay-prodcheck`, separate
volumes and ports, torn down with `down -v` afterwards; the demo stack was untouched):

- All five services healthy from an empty database; `migrate` exited 0 and `alembic current`
  reported `0008_superseded_runs (head)`.
- `/health` and `/health/ready` answered 200; the web tier's `/status` answered 200.
- `GET /api/v1/migrations` answered **401 with no identity and 401 with `X-Relay-User`** — SEC-11
  holding in production. This is the headline: the stack runs correctly and serves nobody, because
  real authentication does not exist. Recorded in `docs/deployment.md` §1 rather than softened.
- The startup guards refuse a `local_dev_only` password, an empty password, `dev_identity_enabled`,
  and `log_format=console` under `RELAY_ENV=production`.
- The rendered configuration was asserted service by service: 27 checks covering production env,
  no leaked scripts dir, no fixtures bind mount, only the web port published and only on loopback,
  restart policies and log rotation on every service.

Two defects were found by verifying claims that had been written down as if true:

- **`make prod-config` rendered with the development password.** This Makefile exports
  `RELAY_DB_PASSWORD ?= relay_local_dev_only`, and the process environment beats `--env-file`, so a
  `.env.production` with a blank password validated cleanly. The target now runs `docker compose`
  under `env -u` for the exported `RELAY_*` variables; a blank password fails loudly again.
- **`.env.production.example` was git-ignored.** The `.env.*` rule caught it and `!.env.example` did
  not bring it back, so the template could never have been committed. `.gitignore` now also has
  `!.env.*.example`; verified with `git add --dry-run` that the template is addable and that
  `.env.production` still is not.

One product defect found and **not** fixed (out of the configuration-only scope, recorded in
`docs/deployment.md` §9): `Settings` refuses `ai_provider=anthropic` when `ANTHROPIC_API_KEY` is
absent, but an empty value parses as `SecretStr('')`, which is not `None`, so the guard passes. Both
compose files set `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`, so in any Compose deployment the
variable is always present and the fail-fast check never fires. Harmless while the provider is
`disabled` (the default). The fix belongs in `relay.core.config`.

Not done, and still blocking a real deployment: authentication (post-MVP by design; the seam is
`current_actor()` in `relay/api/deps.py`) and SEC-25 (the application still connects as a role with
full DML rights, so append-only is enforced in application code and by the hash chains rather than
by database grants).

---

## Public demo mode

A third deployment mode so the product can be shown over a link without an account and without
anyone being able to damage the shared copy. Nothing was deployed.

**`RELAY_ENV=demo`**, a value beside `local`/`test` and `production` rather than a flag, so the
three cannot be confused. In demo: the identity header is **ignored** and every caller resolves to
one seeded `demo_visitor`; `relay.api.demo_policy` refuses mutations before routing; the paid AI
provider is rejected by configuration; `/api/v1/openapi.json`, `/api/v1/docs` and
`/api/v1/dev/users` are 404; a real database password and json logs are required exactly as in
production.

**Two independent controls, neither of which is a hidden button.** `demo_policy` is raw ASGI
middleware outside the router: deny by default, with a one-entry allowlist (`POST
.../investigations`). Separately the visitor holds only `READ` and a new `REQUEST_INVESTIGATION`
permission — split out of `MANAGE_ISSUES`, which every role that could investigate before still
holds, so nobody's access changed. Twenty of the API's twenty-one non-GET routes are refused.

**Investigate stays clickable**, because a demo of an AI-native product that cannot run the AI is a
screenshot. It is bounded by reuse (same finding, same run → the existing investigation is returned,
nothing queued), by the shared 20-per-hour limit, and by the fact that an investigation writes only
its own records. Verified: after one, readiness was still 12 gates / 9 failing and exposure still
217,212.85. Cost is **structurally** zero — `Settings` refuses `ai_provider=anthropic` under
`env=demo`, so no key is read and no path to a model exists; a run reports 0 tokens.

Alembic `0009_demo_visitor_role` widens the `users.role` check constraint; the downgrade deletes any
demo visitor first, since leaving one would violate the narrower constraint it restores.

Verified against a real stack (`make demo-up`: fresh database → migrate → seed → `relay-demo
public-demo` → serve, in its own compose project with its own volumes):

- eleven read endpoints answered 200 with no identity at all;
- nine attempted mutations — create migration, change request, pipeline run, mapping set, issue,
  issue patch, approve, withdraw, upload — all `403 demo.read_only`;
- `X-Relay-User: <lead>` resolved to `demo.visitor@relay.example` / `demo_visitor`, and approving
  with that header was still refused;
- schema, docs and the seeded-user list all 404;
- clicking Investigate produced a real investigation (4 tool calls, verified finding, **0 tokens**),
  and a second click returned the same investigation rather than queuing another.

Tests: `tests/unit/test_demo_mode.py` enumerates routes **from the app** and asserts every mutating
one outside the allowlist is refused, so a route added later is refused until someone deliberately
allows it; plus provider refusal, schema/docs closure, and that local and production are unchanged.
`tests/integration/test_demo_mode.py` covers the database-backed half: anonymous reads, header
impersonation, an unprepared demo refusing rather than improvising an actor, and least privilege.

The web tier runs with `RELAY_PUBLIC_DEMO=1`: no sign-in redirect, no user switcher (a control that
looked like signing in would claim an access check that does not exist), a "Public demo · portfolio
prototype · fictional data · view-only" badge, and every action the API would refuse replaced by a
short note saying what it does in a real deployment. `SubmitButton` is the safety net — in demo it
renders a note unless explicitly marked `allowedInDemo` — and the form bodies around the fifteen
most visible actions are hidden so nothing reads as broken.

Also fixed here: an empty `ANTHROPIC_API_KEY` parsed as `SecretStr("")` and defeated its own
fail-fast guard, which mattered because both compose files pass the variable unconditionally. Blank
and whitespace-only values are now absent, with tests.

Not done and still true: SEC-25 (separate database roles) remains unimplemented and documented as
such, and there is no network-level rate limit — a reverse proxy in front is expected to provide
one. The demo is not production and holds no real data.

---

## Presentation pass (web only)

A presentation-layer pass over the whole web tier. Nothing about the engine, the pipeline, the work
queue composition, the AI layer, governance, readiness, the demo policy, the schema, the fixtures or
the golden manifests changed; `make check` passes with the same numbers as before it.

The problem it fixed: Relay rendered a white page carrying near-white cards with one-pixel borders
and no shadow anywhere, so every surface collapsed into every other one, and the type lived almost
entirely in `text-xs`/`text-sm` with nothing above — a product with a single number that matters had
no way to say which one it was. The direction was "audit-grade console, properly lit": keep the
information architecture, change surface, elevation, scale and rhythm.

- **Tokens** (`web/src/app/globals.css`): the workspace is sunken (`--app`) and content is raised
  white, inverting the old arrangement; `--radius-card` (8px) and `--radius-control` (6px) replace
  the flat 4px everywhere; `--shadow-card` and `--shadow-raised` are the only two lifts in the
  product; `.figure-hero` is the one type size reserved for the number a screen is about.
- **Primitives** (`ui.tsx`): `MetricCard` became `MetricTile` — white surface, ink figure, tone on
  the label and the emphasis ring rather than on the number, so a screen whose verdict, blocking
  work and headline figure were all red keeps some hierarchy to spend. `Panel` gained `emphasis`.
- **Status** (`status-chip.tsx`): outlined pills became tinted fills in four semantic families, and
  critical is now rationed to blocked go-live and controls that did not tie. Kind chips on work
  items are neutral: a category is not a severity.
- **Tables** (`table.tsx`, new): one treatment — sunken header, hairline rows, hover, right-aligned
  tabular numerals, row tints only where a table mixes states. `TABLE_SCROLL` is `relative
  overflow-x-auto`, which is load-bearing: overflow only clips an absolutely positioned descendant
  when the scroller is its containing block, and without it the `sr-only` label in a last column
  landed hundreds of pixels past a phone viewport and scrolled the whole page sideways.
- **Shell**: the sidebar stays (fourteen destinations in five groups is better information
  architecture than a flat bar) with a filled active pill instead of a developer-tool rail, a white
  chrome bar, a 1440px content cap, and a quiet application-level prototype disclosure in the
  footer. Below `lg` the rail becomes one scrollable row of pills per group — same markup, same
  `nav`, no JavaScript and nothing behind a toggle.
- **Investigation** became a two-pane case file: process on the left (the deterministic finding it
  started from, then every tool call with the server's own `latency_ms`), assessment on the right
  (inference, verified evidence, recommended action, open questions, human decision). Deterministic
  result, investigator inference, verified evidence and human decision each carry their own label
  and surface, because conflating them is how an assistant becomes untrustworthy.
- **`splitTitle`** (`lib/format.ts`) lifts the sentence out of a finding title whose tail is exactly
  its own `subjects` field, so a list of sixty-five findings reads as sixty-five sentences rather
  than sixty-five record keys. It matches the payload structurally and never guesses what an
  identifier looks like.

Verified: `make check` (1,096 unit and scenario, 135 integration, 46 web, 115/115 manifest checks);
axe `wcag2a`+`wcag2aa` over twenty pages at 1440 and 390 with zero serious or critical violations —
two of which this pass introduced and fixed (a `<p>` between `dt` and `dd` in `MetricTile`, and
scroll containers that were not keyboard focusable); and no horizontal page overflow at 1440, 1280,
1024, 768 or 390 on eight representative pages. Screenshots in `docs/images/` were recaptured from
the running public demo at 1440×900.

---

## Public deployment preparation (configuration and documentation only)

Everything needed to put the public demo on the internet as an HTTPS URL, and nothing that changes
what Relay does. The diff touches `deploy/`, `docker-compose.public.yml`, `.env.public.example`,
the Makefile and `docs/`; no file under `backend/`, `web/`, `fixtures/` or `evaluation/` moved, and
`make check` returns the same numbers it did before.

**The topology** is one VM running Docker Compose: Caddy is the only service with a published port
(80 and 443), and the web tier, the API, the worker and PostgreSQL sit on the private compose
network with none. The rendered configuration has exactly one `ports:` block, on `caddy` — checked,
not asserted. One machine is the right shape because Relay's blob store is a POSIX directory the
API and the worker must both see; splitting them means writing an object-storage adapter, which is
real work for a demo serving one fictional company.

**The edge** is stock `caddy:2-alpine` with no plugin: automatic HTTPS and renewal over ACME
HTTP-01, the 80 → 443 redirect Caddy installs itself, host validation, HSTS, a 1 MB body cap, and
compression. `make public-config` runs `caddy validate` against the official image, which is what
makes "stock only" a check rather than a claim — it caught two `header_up` directives Caddy already
sets, and they were removed. The other security headers are deliberately *not* set at the edge:
`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and the nonce CSP come from the
application, and two sources for one header is how they drift apart.

**Rate limiting is not in stock Caddy**, and a custom `xcaddy` build for a portfolio demo would
have to be rebuilt and re-verified on every Caddy release. What protects the demo instead is
already in the application and was re-confirmed here: the deny-by-default policy refuses every
mutation but one before any body is read; that one — starting an investigation — returns the
existing investigation for the same issue and run rather than queueing another, so the whole
internet can create at most one per finding, under a global cap of 20 per hour. What would have to
be configured externally, and when, is written down rather than guessed at.

**Two operational scripts** replace the old "delete the volumes and rebuild" reflex.
`deploy/public-demo-reset.sh` drops and recreates the database, empties the blob volume and
re-seeds through the same services a fresh install uses — 77 s measured, 64 s of which the site
answers 502, with the images never rebuilt and Caddy never stopped, so no certificate is re-issued
and no Let's Encrypt rate limit is spent. `deploy/public-backup.sh` writes a database dump and then
a blob archive, in that order and only that order: blobs are content-addressed and the database
holds the references, so dumping first leaves harmless orphans while the reverse leaves dangling
references. `deploy/verify-demo-state.sh` is the canonical-state check both of them end with.

**Verified locally against the real topology**, with Caddy signing its own certificate because a
laptop has no public DNS (the production Caddyfile is otherwise byte-identical and was validated
separately): HTTP → HTTPS 308; HTTPS 200 through the edge with each security header present exactly
once; an unknown Host answered with an empty 200 and never proxied; an unknown SNI failing the
handshake; no `/api/` path reachable through the edge at all; 22 of 22 demo capabilities behaving
as designed when probed *from inside the private network*, which is the case that matters because
the API being unpublished must not be the only boundary; a full investigation started through the
edge finishing with 0 tokens on the `demo` provider; the canonical accounting state unchanged by
it; database, blobs and certificates all surviving a restart; and the reset returning to zero
investigations and the canonical numbers.

Measured for sizing: 308 MiB idle for the whole stack, 614 MiB peak during a reset, ~1.45 GB of
images and ~120 MB of volumes. The recommendation is 2 vCPU / 4 GB / 40 GB — the extra memory is
for `next build`, which is the only step that wants it.

Not done, deliberately: nothing is deployed, no cloud resource exists, no remote is configured, no
LICENSE is chosen, and the commit author email is unchanged. Those are decisions for the person
whose repository it is.

---

## Retrospective

Written at the end of M9, covering the whole build.

### Shape of the result

| | Lines (committed, generated files excluded) |
|---|---|
| Runtime backend (`relay`) | 23,066 |
| Demo and evaluation packages | 10,170 |
| Backend tests | 8,634 |
| Alembic migrations | 1,979 |
| Web application | 6,685 (plus 16,167 generated from the OpenAPI schema) |
| End-to-end tests | 967 |
| Documentation | 4,211 |

1,041 unit and scenario tests, 115 integration tests against real PostgreSQL, 43 web tests, 12
end-to-end specs, 115 golden-manifest checks for Brightwater and 31 expectations for the second
company, 11 decision records.

### What was cut, and why

- **AI mapping suggestions** (ai-safety.md §5, plan cut line 2). The investigator was the part that
  needed proving; column mapping already had deterministic suggestions from M5, and account mapping
  has deterministic signals. Cutting it removed no workflow.
- **Separate database roles** (SEC-25). Real defence in depth, but it needs a second credential, a
  Compose init script and grants maintained as migrations add tables. Recorded as a limitation
  rather than half-built, with the consequence stated: the audit log is tamper-evident, not
  tamper-proof.
- **Waiver expiry dates** (M7). Scope-bound lapsing covers the risk that a waiver silently outlives
  the facts it was granted for; a date would have been a second, weaker mechanism.
- **A CSV export** (SEC-05). Nothing in the demo needs one, and adding it would have meant adding
  formula-injection neutralisation to test.
- **An instrumented audit test** (GV-05) that proves *every* committing service method writes an
  event. Each flow asserted its own events instead. This was the gap I would close first — and it is
  the one the product-quality pass closed (see "GV-05 instrumentation" above).

### What cost the most time, and what it taught

- **A yield dependency that committed after the response** (M6). FastAPI's default meant a client
  could read a 201 for a transaction that had not committed. The fix was one keyword; finding it
  took a day of a flaky test. Now `SessionDep` is `scope="function"` with a test that fails if that
  changes.
- **A deadlock between approvals and the worker** (M6): one path took the audit lock then the
  pipeline lock, the other the reverse. Reproducing it in a test before fixing it was worth more
  than the fix.
- **Sign-off bound to the wrong fingerprint** (M7). Relay's run fingerprint and the engine's input
  fingerprint are different values for good reasons, and G12 compared them silently. The lesson was
  to make the translation explicit and test it, not to make the two the same.
- **Measuring instead of guessing** (M9). The readiness endpoint took 5.8 seconds on a 250,000-line
  migration because gate evidence loaded every reconciliation line once per gate. No test would ever
  have caught it; a single profile did.
- **Writing the golden manifest by hand first** (M1) is the decision the whole project rests on.
  Two mismatches came out of the first full comparison: one was a generator bug (it planted records
  the specification does not describe) and one was an engine bug (a rule broader than its
  documentation). The manifest itself has never changed to match output — which is the only reason
  those two investigations meant anything (decisions/0003 §3).

### What I would do differently

- **Gate evidence should be structured references, not strings.** Today a reconciliation line is
  named `R3:{'party': 'C-0233'}` and parsed back with a regular expression. It works, but it is the
  weakest seam in the codebase.
- **`load_configuration` should load its datasets in one query.** It issues about 90 for a
  sixteen-dataset migration, which is most of what the overview and readiness reads still cost.
- **Pipeline persistence is the throughput ceiling** (75 seconds for 620,000 staged records), not
  the engine (53 seconds). If this had to scale past a quarter of a million lines, that is where the
  work is: partitioned inserts, or keeping the staged set out of the transaction.
- **The AI layer should have been split from the start.** `relay.ai` may only import read models, so
  persistence had to move to `relay.investigations` mid-milestone. The rule was right; I found its
  consequences late.

### What is not true of this project

- It has never been deployed, and the development identity is not authentication.
- No live model run is recorded: the investigator's evals pass only with scripted transcripts, so
  nothing here demonstrates a model's real accuracy on this data.
- Every figure, company and person in the demo is invented. No customer data was used at any point.
