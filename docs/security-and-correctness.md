# Relay — Security & Financial-Correctness Requirements

Status: **Planned requirements.** Each requirement has an ID; tests and code comments should reference it (e.g. `# FC-03`).

Related: [data-model.md](data-model.md) · [governance.md](governance.md) · [ai-safety.md](ai-safety.md) · [testing.md](testing.md)

---

## 1. Financial correctness

| ID | Requirement | Verification |
|---|---|---|
| FC-01 | Monetary values are `Decimal` in Python, `NUMERIC(20,4)` in Postgres, strings in JSON. No `float` in any financial code path. | Lint check forbidding `float(` and float literals in `validation`, `reconciliation`, `mapping`, `pipeline`, `core.money`; Pydantic models use `Decimal` with `strict`; property tests |
| FC-02 | Source amounts are never rounded. Quantization happens only for FX conversion (documented mode `ROUND_HALF_UP` to currency minor units, per line) and for display. | Unit tests; code review |
| FC-03 | Comparisons against tolerance use the exact difference. | Recon engine tests |
| FC-04 | Every amount has an unambiguous currency. Mixed-currency sums are impossible by type (`Money` sums assert same currency; functional sums use `functional_amount`). | Unit tests |
| FC-05 | Canonical ledger sign convention: debit positive, credit negative. Conversion from debit/credit columns is a declared transform; a line with both debit and credit non-zero is a parse failure. | Transform tests |
| FC-06 | Business dates are `DATE` without timezone; never converted through a timezone. System timestamps are UTC `TIMESTAMPTZ`. | Type checks in models; tests with `TZ` set to non-UTC in CI |
| FC-07 | Date parsing requires an explicit format in column mapping; profiling flags ambiguous values. No locale guessing at normalize time. | Transform tests |
| FC-08 | Imported source rows are immutable (DB trigger). Corrections are overlays. | Integration test |
| FC-09 | A pipeline run is a deterministic function of its fingerprint. | Scenario determinism test |
| FC-10 | Rules and reconciliations that error fail readiness (never silently pass). | Gate G4 tests |
| FC-11 | Reconciliation explainers may only explain amounts backed by matched records and never beyond the remaining difference. | Engine tests |
| FC-12 | Issue resolution for rule-backed issues requires verification by a current run. | Lifecycle tests; API rejects manual `resolved` |
| FC-13 | Source anomalies (real legacy misstatements) are dispositioned, not "fixed" by altering migration history, unless an approved override explicitly states why. | Demo manifests; CR kind tests |
| FC-14 | Readiness is evaluated only on a successful current run; sign-off is bound to the run fingerprint. | Gate tests; E2E-5 |
| FC-15 | Totals shown in the UI are computed server-side. The frontend performs no money arithmetic. | Lint rule / code review; component tests |
| FC-16 | Counts are reconciled alongside amounts (quarantined + parsed = physical data rows). | R6 tests |

---

## 2. Governance integrity

| ID | Requirement | Verification |
|---|---|---|
| GV-01 | Governed mutations happen only by applying an approved change request. | Service-layer design; route inventory test asserting mutating endpoints map to allowed operations |
| GV-02 | Requester ≠ approver; one requirement per user per CR. | Unit + integration + DB trigger |
| GV-03 | CRs based on changed state become stale and cannot be approved. | Integration |
| GV-04 | Approve and apply are atomic. | Integration failure-injection test |
| GV-05 | Every governed mutation writes an audit event in the same transaction. | Instrumented UoW test; rollback test |
| GV-06 | Audit events are append-only and hash-chained; verification detects tampering. | Integration + property tests |
| GV-07 | AI is never a requester, approver, or issue-state actor. | Schema (requested_by is a human user FK); tests |
| GV-08 | Optimistic concurrency on mutable resources (`If-Match`). | Integration |

---

## 3. Application security

### 3.1 File handling

| ID | Requirement |
|---|---|
| SEC-01 | Streaming upload with hard byte limit (`RELAY_MAX_UPLOAD_BYTES`), row/column/field limits; limit breaches return `413`/`422` with problem codes. |
| SEC-02 | Files stored under content hash (`blobs/ab/cd/<sha256>`); user-supplied filenames are never used in paths; displayed filenames are sanitized (control chars stripped, length-bounded). |
| SEC-03 | Only `text/csv`-like content accepted in MVP: extension allowlist **and** content sniff (reject binary/zip magic numbers, NUL bytes). |
| SEC-04 | Parsing never evaluates content (no formula evaluation, no `eval`, no pickle). |
| SEC-05 | CSV exports (post-MVP) neutralize formula injection (`=`, `+`, `-`, `@`, tab, CR prefixes). Raw row viewer renders as text. |
| SEC-06 | Temp files are created in a private directory and removed on success/failure. |
| SEC-07 | Blob storage directory not web-served; downloads (if any) go through authorized endpoints with `Content-Disposition: attachment` and `nosniff`. |

### 3.2 API & web

| ID | Requirement |
|---|---|
| SEC-10 | All endpoints require an authenticated actor; authorization via central `require()` guards; default deny. |
| SEC-11 | Dev identity mechanism is enabled only when `RELAY_ENV in {local, test}`; app refuses to start with it enabled otherwise. |
| SEC-12 | Strict Pydantic input models (`extra="forbid"`), bounded string lengths and list sizes. |
| SEC-13 | Parameterized SQL only (SQLAlchemy); no string-built SQL. |
| SEC-14 | Problem responses never include stack traces, SQL, or row values outside `local`. |
| SEC-15 | CORS restricted to the web origin; security headers (CSP without `unsafe-inline` for scripts, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`). |
| SEC-16 | User-originated and data-originated text rendered as text in React (no `dangerouslySetInnerHTML`). |
| SEC-17 | Rate limiting on upload and investigation endpoints (simple per-user token bucket in MVP). |

### 3.3 Data protection

| ID | Requirement |
|---|---|
| SEC-20 | Logs contain ids, counts and hashes — never row values, file contents, prompts or completions. |
| SEC-21 | Sensitive fields (tax ids, bank account numbers, emails) are classified in canonical schemas; redaction policy applied to AI tool outputs and profile samples. |
| SEC-22 | AI processing per migration requires `ai_enabled=true`, set only via approved `policy_change` (represents customer consent). |
| SEC-23 | Secrets only from environment; `.env` git-ignored; `.env.example` contains no real values. |
| SEC-24 | Demo data is entirely fictional; no real customer data in fixtures, ever. |
| SEC-25 | DB roles: app role has no UPDATE/DELETE on append-only tables; migrations run with a separate role. |

### 3.4 Supply chain

| ID | Requirement |
|---|---|
| SEC-30 | Locked dependencies (`uv.lock`, `pnpm-lock.yaml`); Renovate/Dependabot post-MVP. |
| SEC-31 | Docker images pinned by digest for base images; non-root runtime user. |
| SEC-32 | No downloading or executing remote scripts during build beyond package managers with lockfiles. |

---

## 4. Known limitations (MVP, stated honestly)

- Development identity is not authentication. Relay MVP must not be deployed with real data.
- Audit log is tamper-evident, not tamper-proof, against a DB superuser.
- Single-tenant database; no row-level security.
- Local blob storage without encryption at rest beyond the host's disk encryption.
- Header-level AR/AP only; line-level tax and inventory are not validated.
