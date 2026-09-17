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

Status: **In progress.** Decisions: [decisions/0010-m9-hardening.md](decisions/0010-m9-hardening.md).
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

### Remaining

Two extra seeded migrations for the portfolio, the full E2E suite on a rebuilt stack, README demo
guide, rehearsed walkthrough timing, and the retrospective.
