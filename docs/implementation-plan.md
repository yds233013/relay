# Relay — Implementation Plan

Status: **M0 and M1 implemented.** Progress log and current status: [progress.md](progress.md).

Related: all docs in this folder.

---

## 1. Sequencing strategy

The order is driven by risk, not by UI visibility:

1. **Prove the accounting first.** The biggest risk is a demo whose accounting is naive. So the scenario generator, canonical model, rules and reconciliations are built and tested as pure Python *before* any database or UI.
2. **Then make it durable and governed.** Persistence, imports, runs, audit, change requests.
3. **Then make it usable.** UI slices land on top of working APIs, one workflow at a time.
4. **Then add AI**, as a consumer of read models that already exist and are tested.
5. **Then harden and rehearse the demo.**

Each milestone ends in a demoable, tested state and a short entry in `docs/progress.md` (created in M0) recording what was built, what changed from the plan, and why.

---

## 2. Milestones

### M0 — Repository foundation

**Scope**
- Monorepo layout (`backend/`, `web/`, `fixtures/`, `evals/`, `docs/`).
- Backend: `uv` project, Python 3.12, ruff (lint+format), mypy `--strict`, pytest, Hypothesis, import-linter (contracts from architecture §3.1 declared up front), structlog, pydantic-settings.
- `core/`: `money`, `dates`, `clock`, `hashing`, `ids`, `errors`, `config`, `logging` with full unit tests.
- Web: Next.js + TypeScript strict + Tailwind + ESLint + Prettier + Vitest (one development status page).
- Docker Compose: `db` (Postgres 16), `api` (health endpoint only), `web`.
- Alembic initialized with an empty baseline.
- `Makefile` with `setup`, `fmt`, `lint`, `typecheck`, `test`, `check`, `up`, `down`.
- GitHub Actions CI running lint, types, tests.
- `.env.example`, `.gitignore`, `docs/progress.md`.

**Acceptance criteria**
- `make check` passes on a clean clone; CI green.
- `docker compose up` serves `/health` and a placeholder web page.
- `core.money` passes FC-01…FC-05 unit and property tests.
- CLAUDE.md "Commands" section updated to list exactly the commands that now exist.

---

### M1 — Canonical model & Brightwater scenario generator

**Scope**
- `canonical/`: dataclasses for all canonical record types, natural keys, `RecordRef`.
- `demo/` generator: builds a *clean* internally consistent set of Brightwater books (CoA, opening TB, six months of GL, customers, vendors, invoices, bills, payments, agings, bank with clearing window, FX rates), then applies defect injectors DS-01…DS-13 and trap builders TN-01…TN-05, then writes LedgerPro/bank-style CSVs with realistic formatting quirks.
- Golden manifest v1 (Run #1 expectations) authored by hand from [demo-scenario.md](demo-scenario.md).
- `relay demo generate --seed 20260630 --out fixtures/demo/brightwater`.

**Acceptance criteria**
- Clean books invariants tested: TB balances every period; Σ GL detail + opening = TB; AR/AP agings = open documents; bank − GL cash at cutover = only the seeded components.
- Each defect injector has a test asserting exactly its planted delta (all **fixed** amounts reproduced).
- Output byte-identical across runs with same seed.
- Generated CSVs committed under `fixtures/demo/brightwater/` with a checksum file.

---

### M2 — Deterministic engine (pure Python, CLI)

**Scope**
- CSV reader with quarantine (in-memory), column mapping transforms, account mapping application.
- Normalize stage → `RunSnapshot`.
- Validation engine + full MVP rule catalog.
- Reconciliation engine + R1–R6 + explainers + drill-down computation.
- Entity resolution candidates + decision application.
- Issue-lifecycle and readiness **domain** functions (no persistence).
- Input fingerprint computation.
- `relay engine run --fixtures fixtures/demo/brightwater --config fixtures/demo/brightwater/config/initial.yaml` printing gates, recon summaries and exceptions.

**Acceptance criteria**
- Scenario test: Run #1 exceptions and recon discrepancies **exactly equal** manifest v1.
- Resolution-sequence test through scripted overlays (as YAML config) reaches: manifest v2 after DS-01 merge (DS-02 appears), and all-gates-pass-except-G12 at the end.
- TN-01…TN-05 produce nothing.
- Full engine run on Brightwater < 10 s on a laptop; synthetic 250k-line GL < 60 s.
- Every rule has positive/negative/near-miss fixtures; import-linter confirms domain modules import only `core`/`canonical`.

**This milestone is the project's credibility checkpoint. Do not proceed if the manifest test cannot be made to pass honestly.**

---

### M3 — Persistence, ingestion, runs, audit

**Scope**
- Alembic migrations for identity, workspace, ingestion, mapping, overlays, pipeline results, issues, audit, jobs (per [data-model.md](data-model.md)); triggers for append-only tables.
- `BlobStore` (local), streaming upload with limits and sniffing, idempotent imports, supersession.
- Jobs table + worker (`relay worker`) with `SKIP LOCKED`, heartbeats, advisory lock per migration.
- Profilers.
- Pipeline orchestrator persisting staged records (COPY), exceptions, recon results, issues, readiness evaluations.
- Audit writer with hash chain; `relay verify-audit`.
- Seeded users; dev identity; `current_actor`.
- Read APIs: workspace, datasets, imports, rows, quarantine, profile, runs, rules/exceptions, reconciliations/lines/drilldown, records, issues, readiness, audit.
- `relay demo seed` loads Brightwater into the DB at the "day 9" state (imports + approved mappings via recorded CRs + Run #1).

**Acceptance criteria**
- Integration tests from [testing.md §2.4](testing.md#24-integration-tests-backendtestsintegration) for imports, append-only, audit atomicity, jobs, pipeline idempotency, dev identity guard.
- Persisted Run #1 matches manifest v1 (same scenario assertions, via DB).
- `GET /reconciliation-lines/{id}/drilldown` for R3 C-0233 returns `INV-10877` as `left_only` with lineage to GL export line number.
- Audit chain verifies after seeding.
- OpenAPI generated and committed.

---

### M4 — Web shell and evidence views (first visible demo)

**Scope**
- App shell, dev user switcher, portfolio, migration nav.
- Overview (readiness banner, blockers, exposure, stages, activity).
- Data (datasets, imports, profile, row viewer, quarantine).
- Runs (list, fingerprint components, diff).
- Validation (rule list, exception table).
- Reconciliation (results, lines, drill-down).
- Record inspector panel.
- Issues (list, detail read-only).
- Readiness (gates with evidence).
- Audit log (filterable).
- Shared components: `Money`, `BusinessDate`, `StatusChip`, `RecordRef`, virtualized `DataTable`.

**Acceptance criteria**
- E2E-1 passes.
- No money arithmetic in `web/` (lint rule/grep check in CI).
- Every summary number on Overview links to its evidence.
- Lighthouse accessibility ≥ 90 on Overview and Reconciliation.

---

### M5 — Mappings, change requests, approvals

**Scope**
- Column mapping sets: draft, edit, deterministic suggestions, preview.
- Account mapping sets: draft, edit, deterministic suggestions with compatibility signals.
- Change request framework: kinds, payload union, before/after/impact computation, approval policy, SoD, staleness, atomic approve+apply, auto-enqueue run.
- Kinds implemented here: `column_mapping_set`, `account_mapping_set`, `record_override`, `policy_change`, `revert`.
- UI: Mappings pages, Approvals queue, CR detail with before/after diff and evidence, approve/reject.

**Acceptance criteria**
- E2E-2 passes (including API-level SoD rejection).
- DS-03, DS-05, DS-08, DS-11 resolvable end-to-end through UI; reruns verify and resolve issues.
- Staleness integration test passes.
- Every CR transition visible in audit with before/after.

---

### M6 — Issues workflow, entity resolution, dispositions, re-imports

**Scope**
- Issue ownership, workflow transitions, comments, history, links, amount-at-risk dedup.
- Entities page: candidates, features, decisions via `entity_decision` CR.
- `disposition` CRs; `dispositioned` state; exposure exclusion.
- Re-import flow with activation and supersession in UI.
- New-migration flow: create migration, source systems, datasets, upload, map, run (E2E-8).

**Acceptance criteria**
- E2E-3, E2E-4, E2E-8 pass.
- DS-01, DS-02, DS-04, DS-06, DS-07, DS-09, DS-10, DS-12, DS-13 resolvable through UI.
- Regression test: reverting an applied override reopens its issue on rerun.

---

### M7 — Readiness gates, waivers, sign-off

**Scope**
- Full G1–G12 evaluation surfaced with evidence.
- `gate_waiver` and `readiness_signoff` CRs; sign-off invalidation; waiver lapse.
- Migration status transitions (`signed_off`).
- `relay demo fast-forward --to=before-signoff`.

**Acceptance criteria**
- E2E-5 passes.
- Final scenario manifest: READY after sign-off; invalidated after any fingerprint change.
- Waiver tests: non-waivable gates reject waivers; waiver lapses when scoped amounts change.

---

### M8 — AI investigation layer

**Scope**
- Provider protocol; `disabled`, `scripted`, `anthropic` providers (consult current vendor SDK docs at implementation time).
- Tool registry and MVP tools over existing read models; `READ ONLY` tool sessions; redaction.
- Investigator loop with budgets and transcript persistence.
- Finding schema, provenance verification, server-computed `requires_approval`.
- Draft-CR-from-finding flow.
- Mapping suggestion tasks.
- Per-migration AI enablement via `policy_change`.
- UI: Investigate panel on issue detail and overview, step transcript viewer, findings with verification badges.
- Eval harness E1–E6 (scripted in CI; live manual).

**Acceptance criteria**
- AI tests in [testing.md §2.6](testing.md#26-ai-tests-backendtestsai) pass; import-linter forbids `ai` → services/models.
- Attempted write inside a tool raises in Postgres (integration test).
- E2E-7 (no-AI mode) passes.
- Live eval run recorded: E1–E5 root cause hit, 0 fabricated references across all cases, E4 injection compliance 0.
- A `failed` finding cannot be promoted (API test).

---

### M9 — Hardening & demo rehearsal

**Scope**
- Security review against [security-and-correctness.md](security-and-correctness.md); fix findings.
- Performance check on synthetic 250k-line migration; add indexes as measured.
- Two additional lightweight seeded migrations for the portfolio (one launched, one early-stage).
- E2E-6 and full E2E suite green.
- README demo guide with screenshots; recorded walkthrough; `docs/progress.md` retrospective including what was cut and why.

**Acceptance criteria**
- `make test-all` green from clean clone via Docker Compose.
- Walkthrough in [demo-scenario.md §7](demo-scenario.md#7-demo-walkthrough-target-10-minutes) completes in ≤ 10 minutes, twice in a row, with no manual DB edits.
- Every requirement ID in security-and-correctness.md maps to a test or a documented limitation.

---

## 3. Cut lines (if time runs short)

In order of what to drop first, without harming the core story:

1. Portfolio extra migrations (M9) — show one migration.
2. Mapping AI suggestions (M8) — keep the investigator.
3. Waiver lapse logic (M7) — keep waivers, make them fingerprint-bound only.
4. R4/R4b AP reconciliations — AR demonstrates the pattern (keep AP duplicate rules).
5. Column mapping editor UI (M5) — ship mappings as approved configs; keep account mapping UI.

Never cut: golden manifest tests, change request SoD/staleness, audit atomicity, provenance verification, no-AI mode.

---

## 4. Recommended first step

Approve this plan, then build **M0 and M1 together** in that order: repository foundation with `core.money`/`core.dates` fully tested, then the clean-books generator with its invariant tests, then defect injectors and the golden manifest. Stop at the end of M1 for review of the generated data before building the engine.
