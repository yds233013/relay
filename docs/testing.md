# Relay — Testing Strategy

Status: **Planned.** No test infrastructure exists yet.

Related: [security-and-correctness.md](security-and-correctness.md) · [demo-scenario.md](demo-scenario.md) · [ai-safety.md](ai-safety.md)

---

## 1. Principles

1. **The scenario is the spec.** The Brightwater golden manifests are the highest-value tests: exact expected issues, no more, no fewer.
2. **Pure core, cheap tests.** Rules, reconciliations, entity scoring, issue lifecycle decisions and gate evaluation are pure functions tested without a database.
3. **Real Postgres for integration.** No SQLite substitutes: constraints, triggers, `NUMERIC`, `SKIP LOCKED` and `READ ONLY` transactions are part of correctness.
4. **Determinism.** Injected `Clock`, seeded generators, UUIDv7 from an injectable source in tests, stable sort orders, no network (sockets blocked in pytest), no reliance on dict/set iteration order for output.
5. **A test for every invariant listed in [security-and-correctness.md](security-and-correctness.md).**

---

## 2. Layers

### 2.1 Backend unit tests (`backend/tests/unit`, no DB)

| Area | What is tested |
|---|---|
| `core.money` | Parsing `1,234.56`, `(1,234.56)`, `-`, `$1,234.56`, `1.234,56` only with declared decimal comma; rejection of floats and ambiguous formats; minor units per currency; quantization rounding mode |
| `core.dates` | Explicit formats; ambiguous date detection; fiscal period derivation for non-calendar fiscal years; leap days |
| `core.hashing` | Canonical JSON stability (key order, Decimal formatting, date formatting) |
| Ingestion reader | Encodings (UTF-8, BOM, cp1252), delimiters, quoted newlines, unterminated quotes, field-count mismatch quarantine with correct physical line spans, limits |
| Column transforms | Each transform, including error paths |
| Each rule | positive, negative, near-miss fixtures; fingerprint stability when amounts change; determinism (run twice, compare) |
| Reconciliation engine | tie, explained, tolerance, left_only/right_only, explainer cannot over-explain, drill-down set diff |
| Entity resolution | normalization tables; scoring on DS-01/DS-06/TN-03 fixtures |
| Issue lifecycle domain | create, update, verify-resolve, reopen on regression, dispositioned untouched, stale-run no-op |
| Approval policy | requirements by kind/amount/field; SoD; one requirement per user; policy change cannot lower its own requirements |
| Readiness gates | each gate pass/fail/waived/not_evaluated; sign-off bound to fingerprint |
| AI verification | valid finding; fabricated record ref; fabricated number; citing a non-result step; suggested action referencing a non-existent account |

### 2.2 Property-based tests (Hypothesis)

- Any generated set of balanced journal entries → `GL.JE_BALANCED` emits nothing; perturbing one line by δ ≠ 0 → exactly one exception with amount δ.
- For any many-to-one account mapping, Σ legacy balances = Σ target balances (R2 fidelity invariant).
- Reconciling a measure against itself → all lines `tied`.
- Money parse/format round-trip for generated decimals.
- Fingerprint is invariant to input row order.
- Hash chain verification detects any single-field mutation of any event.

### 2.3 Scenario tests (`backend/tests/scenario`, no DB for the pure path, DB for the full path)

- **Generator integrity**: generated legacy books are internally consistent *before* defects are injected (TB balances; aging = open items; bank − GL = seeded components).
- **Run #1 manifest**: pipeline over generated files produces exactly the manifest's issues, severities, amounts at risk and reconciliation discrepancies.
- **Resolution sequence**: applying each scripted resolution in order produces the expected manifest after each run (including DS-02 appearing only after DS-01 merge) and ends READY after sign-off.
- **Traps**: TN-01…TN-05 produce no issues.
- **Determinism**: generator output byte-identical across two runs with the same seed; pipeline fingerprint and outputs identical across two runs.

### 2.4 Integration tests (`backend/tests/integration`, Postgres)

- Alembic: upgrade from empty to head; downgrade one step and re-upgrade on empty DB.
- Imports: identical re-upload is idempotent; new file supersedes; activation audited; limits enforced with correct problem codes; filename path traversal attempts inert.
- Append-only: UPDATE/DELETE on `source_rows` and `audit_events` raise.
- Audit atomicity: force a failure after the domain write → neither domain change nor audit event persists.
- Change requests: full state machine via API; SoD violation → `403 approval.segregation_of_duties`; staleness when base changes; approve-and-apply atomic.
- Concurrency: `If-Match` mismatch → 412; two workers competing for one job → exactly one runs it; concurrent pipeline runs for one migration serialize.
- Pipeline idempotency: same fingerprint → same run returned.
- AI tools: executed in `READ ONLY` transaction (attempted write raises); tool cannot access another migration's records.
- Authorization: each role against each mutating endpoint (table-driven).
- Dev identity refused when `RELAY_ENV=production`.

### 2.5 Contract tests

- OpenAPI schema generated in CI and diffed against committed `web/src/lib/api/openapi.json`; drift fails the build.
- Frontend `tsc` over the generated client.
- Error responses validated against the problem+json schema.

### 2.6 AI tests (`backend/tests/ai`)

- Scripted provider transcripts drive the investigator loop: tool arg validation errors returned to model, budget exhaustion, timeout, malformed final output.
- Eval harness cases E1–E6 (see [ai-safety.md §7](ai-safety.md#7-evaluation)) run with scripted transcripts in CI.
- Live-model evals: manual only, never in CI, results committed with model id and prompt version.

### 2.7 Frontend unit tests (Vitest + Testing Library)

- Money/date formatting from strings, parentheses negatives, currency display.
- Status chips render text, not color only.
- AI finding component: plain-text rendering (no HTML injection), verification badge states, no approve control present.
- Stale-results banner behavior.

### 2.8 End-to-end (Playwright, against Docker Compose with seeded demo)

| Flow | Asserts |
|---|---|
| E2E-1 Blockers to evidence | Overview shows NOT READY with expected failing gates; drill R3 → C-0233 → INV-10877 source row with line number |
| E2E-2 Mapping fix with SoD | Maya drafts and submits account mapping change; Maya has no approve button (and API rejects); Daniel + Priya approve; rerun completes; R3 unassigned difference cleared |
| E2E-3 Idempotent re-import | Upload same file twice → one import; upload corrected invoices → R3b ties |
| E2E-4 Merge reveals duplicate payment | Entity merge → rerun → new DS-02 issue → disposition → exposure decreases |
| E2E-5 Sign-off invalidation | Fast-forward to ready → sign-off → READY → change policy → STALE / sign-off invalidated |
| E2E-6 Audit trail | Audit log shows before/after and approvers for E2E-2; chain verification passes |
| E2E-7 No-AI mode | With AI disabled, all flows above pass and AI controls are absent |
| E2E-8 New migration from CSV | Create migration, upload a small CSV set, map columns, run pipeline, see issues |

---

## 3. Commands (planned — none exist yet)

| Command | Purpose |
|---|---|
| `make test` | backend unit + scenario (pure) + frontend unit |
| `make test-integration` | backend integration against compose Postgres |
| `make test-e2e` | Playwright against compose stack with seeded demo |
| `make test-all` | everything above |
| `make eval-ai` | live-model evals (requires API key; manual) |

---

## 4. CI (planned, GitHub Actions)

1. Lint & format check: `ruff check`, `ruff format --check`, `eslint`, `prettier --check`
2. Types: `mypy --strict` (backend), `tsc --noEmit` (web)
3. Import contracts: `lint-imports`
4. Unit + property + scenario tests
5. Integration tests (Postgres service container)
6. OpenAPI drift check
7. E2E on main and on PRs labelled `e2e` (full compose)

Coverage is reported but not gated globally; the rules, reconciliation, changes, audit, readiness and AI verification modules target ≥ 90% branch coverage because they carry the correctness claims.

---

## 5. Definition of done for any change

- Tests added/updated at the lowest layer that can catch the bug.
- All CI steps above pass locally (`make check`, planned).
- If behavior of a rule, reconciliation or gate changed: its version bumped, docs updated, scenario manifests updated **with an explanation in the commit message** of why the expected set changed.
