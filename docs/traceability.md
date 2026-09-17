# Relay — Requirement traceability

Every requirement ID in [security-and-correctness.md](security-and-correctness.md) maps to the
automated tests that check it, or to a stated limitation. Written in M9 from a file-by-file audit of
the repository; paths are relative to the repository root.

Status values:

| Status | Meaning |
|---|---|
| **Tested** | An automated test asserts the requirement's substance. |
| **Tested (partial)** | Tested, with a named part that is not. |
| **Enforced, not tested** | Code or configuration enforces it; no test would fail if that changed. |
| **Deviates** | Implemented differently from the written requirement; the difference is explained. |
| **Not implemented** | Stated as a limitation, with what would be needed. |

`make check` runs every test named here (CI additionally runs it with `TZ=Australia/Adelaide`).

---

## 1. Financial correctness

| ID | Status | Where |
|---|---|---|
| FC-01 | Tested | `backend/tests/unit/test_no_float_in_financial_code.py` (AST scan of the financial packages, with a non-vacuity check), `test_money.py`, `test_db_types.py`, `tests/integration/test_database.py` (PostgreSQL would round without the column guard) |
| FC-02 | Tested | `test_money_parsing_fx_sign.py` (rounding mode, per-line minor units, recorded rounding difference); construction raises rather than rounds (`test_money.py`) |
| FC-03 | Tested | `test_money.py`, `test_money_properties.py` (exact difference against tolerance), `test_engine_rules.py` (reconciliation statuses) |
| FC-04 | Tested | `test_money.py`, `test_money_properties.py` (mixed-currency sums raise), `test_currency.py` |
| FC-05 | Tested | `test_money_parsing_fx_sign.py`, `test_ingestion_and_mapping.py` (debit and credit in one line is a parse failure), `test_money_properties.py` |
| FC-06 | Tested | `test_dates_and_timestamps.py` (business dates do not move with the process timezone), `test_db_types.py`, `tests/integration/test_database.py`; CI runs the whole suite under `TZ=Australia/Adelaide` (`.github/workflows/ci.yml`) |
| FC-07 | Tested (partial) | Explicit formats and ambiguity detection: `test_dates_and_timestamps.py`, `test_ingestion_and_mapping.py`. Not tested: that `ColumnProfile.ambiguous_date_count` is populated end to end |
| FC-08 | Tested | `tests/integration/test_persistence.py` (UPDATE, DELETE and TRUNCATE refused on `source_rows`, `quarantined_rows`, `audit_events` by trigger), `test_issue_workflow.py` (append-only comments) |
| FC-09 | Tested | `tests/scenario/test_engine_brightwater.py` (same inputs, same results), `tests/integration/test_persistence.py` (a run is idempotent on its fingerprint, and fails if inputs change after the request) |
| FC-10 | Tested | `test_engine_rules.py` (a rule that raises is recorded as an errored stage, other evidence survives, G4 fails; a reconciliation that raises leaves the others intact), `tests/integration/test_persistence.py` (persisted as `errored` with its message, G4 fails) |
| FC-11 | Tested | `ReconLine` refuses to be built with an explained amount beyond, or against, its difference (`test_engine_rules.py`); the whole Brightwater scenario is built under that invariant |
| FC-12 | Tested | `tests/integration/test_issue_workflow.py` (the API refuses a manual `resolved`), `test_issue_sync_and_approvals.py` (resolution only by a run that no longer produces the fingerprint) |
| FC-13 | Tested | `test_issue_sync_and_approvals.py` (disposition approval policy), `tests/integration/test_issue_workflow.py` (the documented Brightwater dispositions), `tests/scenario/test_traps_and_manifest.py` |
| FC-14 | Tested | `tests/integration/test_readiness.py`, `tests/scenario/test_engine_brightwater.py` (a sign-off for another fingerprint does not count), E2E-5 |
| FC-15 | Tested | `web/src/lib/no-money-arithmetic.test.ts` (no arithmetic on money in the web source, with a non-vacuity check), server-side totals in `tests/integration/test_brightwater_persisted.py` |
| FC-16 | Tested | `test_engine_rules.py` (R6 counts quarantined rows), `tests/scenario/test_engine_brightwater.py` |

## 2. Governance integrity

| ID | Status | Where |
|---|---|---|
| GV-01 | Tested | `backend/tests/unit/test_route_inventory.py` (every non-GET route is a listed governed operation), plus the per-kind apply tests in `tests/integration/test_governance.py` |
| GV-02 | Tested | Domain (`test_issue_sync_and_approvals.py`), API (`tests/integration/test_governance.py`), database trigger (`tests/integration/test_persistence.py`) |
| GV-03 | Tested | `tests/integration/test_governance.py` (approving one change makes a competing change stale and unapprovable) |
| GV-04 | Tested | `tests/integration/test_governance.py` (a failure injected into the applier rolls back the approval, the policy version and the audit event; the change request is left reviewable) |
| GV-05 | Tested (partial) | `tests/integration/test_persistence.py` (a rolled-back change takes its audit event with it), and every governed flow asserts its events. Not tested: an instrumented check that *every* committing service method emits at least one event |
| GV-06 | Tested | `backend/tests/unit/test_audit_chain_properties.py` (generated chains: recomputation, and that editing any hashed field breaks that event and every link after it), `tests/integration/test_persistence.py` (tamper detection in PostgreSQL, gapless sequence), `make verify-audit` |
| GV-07 | Tested | `tests/integration/test_persistence.py` (the system actor cannot request a change), `tests/integration/test_ai.py` (AI sessions cannot write; findings become drafts owned by a person) |
| GV-08 | Deviates | Optimistic concurrency is a `version` integer in the request body with a 409 on conflict, not `If-Match`/`ETag`/412. Tested for change request drafts and issues (`tests/integration/test_governance.py`, `test_issue_workflow.py`). The deviation is recorded in [decisions/0010](decisions/0010-m9-hardening.md) |

## 3. Application security

### 3.1 File handling

| ID | Status | Where |
|---|---|---|
| SEC-01 | Tested (partial) | Byte limit (413), extension and content checks (415), row limit, column limit (`tests/integration/test_api.py`, `test_persistence.py`, `test_ingestion_and_mapping.py`). Partial: the row limit surfaces as a failed import with a problem code rather than a 4xx on upload, because parsing is asynchronous |
| SEC-02 | Tested | `tests/integration/test_persistence.py` (content-hash storage key; `../../etc/passwd\x00.csv` is stored as `passwd.csv`) |
| SEC-03 | Tested | `tests/integration/test_persistence.py` (zip magic bytes and `.xlsx` rejected), `test_api.py` (415), NUL bytes rejected at parse |
| SEC-04 | Tested | `backend/tests/unit/test_static_guards.py` (no `eval`, `exec`, `compile`, `__import__`, `pickle`, `marshal`, `shelve`, `subprocess` or `yaml` anywhere in `relay.*`) |
| SEC-05 | Not implemented | Relay has no CSV export (post-MVP in the requirement). The raw row viewer renders as text, which the `react/no-danger` lint rule keeps true |
| SEC-06 | Tested | `tests/integration/test_persistence.py` (the private spool directory is empty after size, binary and extension failures) |
| SEC-07 | Enforced, not tested | Blobs are not served: the API mounts no static files and has no download endpoint; the blob root is `chmod 700` inside the image. Nothing tests that they stay unreachable |

### 3.2 API and web

| ID | Status | Where |
|---|---|---|
| SEC-10 | Tested | `backend/tests/unit/test_route_inventory.py` (every route authenticates unless it is one of the listed public ones), `tests/integration/test_api.py` (401 unauthenticated, 403 for a viewer) |
| SEC-11 | Tested | `test_config.py` (production refuses to start with the development identity), `tests/integration/test_api.py` (the header is ignored and `/dev/users` is absent under `RELAY_ENV=production`) |
| SEC-12 | Tested (partial) | `extra="forbid"` on every API and payload model (`test_governance_domain.py`). Partial: bounded lengths are enforced in services rather than on every schema field |
| SEC-13 | Tested | `backend/tests/unit/test_static_guards.py` (every `text(...)` takes a literal; no f-strings or concatenation), plus bound parameters throughout |
| SEC-14 | Tested | `backend/tests/unit/test_api.py` (no internal detail, submitted values, SQL or database URL in problem responses) |
| SEC-15 | Tested | Web: nonce-based CSP with no `unsafe-inline` (`web/src/proxy.ts`, `web/src/lib/csp.test.ts`, E2E `security-headers.spec.ts` asserts the served header and that the app runs under it). API: `default-src 'none'; frame-ancestors 'none'; base-uri 'none'` (`backend/tests/unit/test_api.py`). CORS is not configured because the browser never calls the API directly (see [decisions/0010](decisions/0010-m9-hardening.md)) |
| SEC-16 | Tested | `react/no-danger` as a lint error in `make lint`; `web/src/components/ai-finding.test.tsx` renders hostile model and imported text and asserts it is escaped |
| SEC-17 | Tested | Investigations: at most 20 per person per hour (`relay.investigations.service`). Uploads: at most `RELAY_MAX_UPLOADS_PER_HOUR` (default 60) per person, checked before any bytes are read (`tests/integration/test_persistence.py`). Counted from persisted rows rather than a token bucket; rejected uploads leave no row and so do not count |

### 3.3 Data protection

| ID | Status | Where |
|---|---|---|
| SEC-20 | Tested (partial) | `backend/tests/unit/test_api.py` (the request log carries no query values). Partial: no static guard prevents a future log call from taking row values, prompts or completions |
| SEC-21 | Tested (partial) | Redaction of AI tool outputs (`backend/tests/ai/test_providers_and_redaction.py`) and profiles that store shape, not values. Partial: sensitive fields are recognised by name and pattern, not classified in the canonical schemas |
| SEC-22 | Tested | `tests/integration/test_ai.py` (off by default; consent only through an approved `policy_change`) |
| SEC-23 | Tested | `backend/tests/unit/test_static_guards.py` (`.env` ignored, `.env.example` carries no values), `test_config.py` (the database URL is not in `repr` or `model_dump`), `tests/ai/test_providers_and_redaction.py` (the API key appears only in the request header) |
| SEC-24 | Tested | `tests/scenario/test_determinism_and_boundaries.py` (fixtures regenerate byte for byte from the generator and contain no answer-revealing text); all demo data is generated, never collected |
| SEC-25 | Not implemented | One database role owns and runs everything, so the application role could disable the append-only triggers (`tests/integration/test_persistence.py` does exactly that to prove tamper detection). Separate owner and application roles, with `UPDATE`/`DELETE` revoked on the append-only tables, need a Compose init script and a second credential; see [decisions/0010](decisions/0010-m9-hardening.md) |

### 3.4 Supply chain

| ID | Status | Where |
|---|---|---|
| SEC-30 | Tested | `backend/tests/unit/test_static_guards.py` (both lockfiles committed); `uv run --locked` and `npm ci` everywhere, including the images |
| SEC-31 | Tested | `backend/tests/unit/test_static_guards.py` (every pulled image pinned by digest, every image runs as a non-root user) |
| SEC-32 | Tested | `backend/tests/unit/test_static_guards.py` (no `curl`, `wget` or piped shell in the Dockerfiles). GitHub Actions are pinned by major tag rather than SHA |

---

## Limitations restated

- Development identity is not authentication; Relay must not be deployed with real data.
- The audit log is tamper-evident, not tamper-proof: with one database role (SEC-25) a determined
  operator can disable the triggers, and verification then reports the break.
- Single-tenant database, no row-level security; local blob storage without encryption at rest.
- Header-level AR/AP only: line-level tax and inventory are not validated.
