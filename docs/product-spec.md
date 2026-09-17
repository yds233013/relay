# Relay — Product Specification

Status: **Planning. Nothing described here is implemented yet.**

Relay is an implementation and migration operations system for ERP deployments. It gives an implementation team one place to import legacy accounting data, map it onto a target structure, prove (deterministically) that nothing was lost or distorted, work the exceptions to closure with an auditable approval trail, and decide — on explicit evidence — whether a customer is safe to go live.

Relay is designed as the kind of internal system an AI-native ERP company would run its customer migrations on. It is not a chatbot and not a CSV importer.

---

## 1. The problem, stated precisely

Moving a company onto a new ERP means converting years of financial state that lives in a legacy ERP, spreadsheets, bank exports and billing tools into a new system of record. The failure modes that actually hurt customers are not "the CSV didn't parse". They are:

1. **Silent incompleteness** — an export filter drops inactive customers, an unprinted invoice, a deleted account. Everything parses; totals are quietly wrong.
2. **Silent distortion** — a mapping puts a contra-asset into Accounts Receivable. Totals are preserved, so a naive import check passes, but the AR subledger no longer ties to the GL.
3. **Pre-existing defects in the legacy books** — duplicate vendors, a double payment, EUR invoices keyed as USD. These are not migration bugs but must be surfaced and *dispositioned* before they are inherited.
4. **Unaccountable fixes** — someone edits a spreadsheet to make a number tie. Nobody can later say what changed, why, or who agreed.
5. **Unfalsifiable go-live decisions** — "looks good" in a status meeting, instead of a set of gates evaluated against a specific, reproducible data state.

Relay's job is to make each of these visible, attributable and closable.

---

## 2. Critical review of the original brief

The original brief was strong on capability breadth. The following weaknesses would have produced a less credible system; each has been changed in this spec.

| # | Weakness in the brief | Why it matters | Change made |
|---|---|---|---|
| 1 | **"Transformed/target data" is undefined.** There is no real target ERP to load into. | Reconciliation against an undefined target is meaningless; the demo would reconcile data to itself. | Relay defines a **Canonical Accounting Model** (the staged output of mapping + normalization) plus an imported **target chart of accounts**. "Target" means "what Relay would load". Relay does not claim to know DualEntry's internal schema. |
| 2 | **No independent control totals.** Reconciling extracted detail against transformed detail is circular: if an export drops an invoice, both sides agree. | This is the single most important gap. Completeness can only be proven against an independent report. | Relay imports **control reports** from the legacy system — trial balances by period, AR aging, AP aging, bank statement balances — and reconciles *detail against control* as well as *source against staged*. See §6. |
| 3 | **No conversion strategy.** Cutover date, opening balances, history window and open items are never mentioned. | Every real migration is defined by these. Period-level reconciliation is impossible without them. | Each migration has an explicit **conversion plan**: opening balance date, history window, cutover date, go-live date, and which datasets carry history vs. open items only. |
| 4 | **"Resolve" implies editing data.** | Editing imported data destroys the evidence trail and makes results non-reproducible. | Imported rows are **immutable**. Every correction is a versioned **overlay** (mapping version, record override, entity decision, disposition) approved through a change request. Staged data is **recomputed** from `raw inputs + approved overlays`. Any result can be regenerated. |
| 5 | **Validation failures, issues and AI findings are conflated.** | Without separation, reruns create duplicate issues, and AI prose can masquerade as validation. | Three distinct objects: **Exception** (deterministic, per pipeline run, per record), **Issue** (human workflow object with a stable fingerprint across runs), **Finding** (AI-generated hypothesis, attached to an issue, never changes issue state). |
| 6 | **Issue closure is unverified.** | An operator marking an issue "resolved" proves nothing. | An issue backed by a rule can only become `resolved` when a **subsequent pipeline run no longer produces its fingerprint**. Otherwise it must be *dispositioned* through an approved change request. Regressions reopen issues automatically. |
| 7 | **AI "confidence" as a number.** | LLM self-reported confidence is uncalibrated; presenting "87%" is misleading in a financial tool. | Suggestions carry a **basis** (`exact`, `synonym`, `rule`, `operator`, `ai_suggested`) and deterministic **supporting signals** (type compatibility, name similarity, balance sign). AI confidence is a coarse band (`low/medium/high`) and is labelled as model-reported. |
| 8 | **"AI detects duplicates."** | Non-reproducible and unauditable. | Entity-resolution candidates are generated **deterministically** (blocking + similarity features). AI may explain candidates. Merge decisions are non-destructive, reversible, approved overlays. |
| 9 | **Readiness "score".** | A weighted score invites gaming and hides the one thing that matters. | Readiness is a **set of named gates**, each pass/fail/waived with evidence, evaluated against a **specific pipeline run**. Sign-off is bound to that run's input fingerprint and becomes stale if inputs change. No percentage. |
| 10 | **"Monetary exposure" undefined.** | Summing invoice totals across overlapping issues double counts and inflates. | Each rule defines its **amount at risk** (e.g. JE imbalance = \|Dr − Cr\|, not JE total). Migration-level exposure deduplicates by record. It is labelled an attention metric, not a measured misstatement. |
| 11 | **Duplicate payment treated like a migration defect.** | A double payment is a real business loss. "Fixing" it in migration data would falsify history. | Issues have a **nature**: `migration_defect` (Relay must fix before load) vs. `source_anomaly` (legacy books are wrong; requires a documented disposition such as a post-go-live correcting entry). |
| 12 | **Approvals lack segregation of duties and staleness.** | An approval that the requester can grant, or that applies to data that has since changed, is theatre. | Requester ≠ approver; approvals are role-gated by a policy; a change request records the state fingerprint it was based on and becomes **stale** if that state changes before approval. The AI is never a requester. |
| 13 | **"Immutable-style" audit.** | Ambiguous; an application table anyone can `UPDATE` is not an audit log. | Audit events are append-only (DB trigger + no update path), written **in the same transaction** as the change, and hash-chained per migration for **tamper evidence**. We state honestly that this is tamper-evident, not tamper-proof against a DB superuser. |
| 14 | **Business dates vs. timestamps.** | "Timezone-aware timestamps" applied to invoice dates causes off-by-one-day period errors. | Business dates are `DATE` (no timezone). System events are `TIMESTAMPTZ` in UTC. Fiscal periods are derived from dates using the company fiscal calendar. |
| 15 | **Scope.** 12 capabilities, connectors, portfolio, AI, all production-grade. | Breadth would force shallowness everywhere. | A narrow MVP with one deep end-to-end story (§4). Connectors, XLSX, multi-entity, consolidation, and load-to-ERP are explicitly post-MVP. |
| 16 | **No identity model.** | Approvals and audit require actors. | MVP ships seeded users with roles and a clearly-labelled **development identity mechanism** (disabled outside local/test). Real SSO is post-MVP. |
| 17 | **No scale envelope.** | Architecture choices (in-memory rules vs. SQL pushdown, sync vs. async) depend on it. | MVP target: ≤ 250k GL lines and ≤ 50 MB per file per migration, full pipeline run < 60 s on a laptop. |

---

## 3. Users and roles

| Role | Who (in reality) | Can | Cannot |
|---|---|---|---|
| `implementation_specialist` | Relay operator doing the hands-on work | Import, draft mappings, run pipeline, own issues, request changes, launch AI investigations | Approve anything |
| `implementation_lead` | Senior operator accountable for the migration | Everything a specialist can + approve changes per policy | Approve own requests |
| `customer_controller` | The customer's controller/finance lead | Review evidence, approve accounting-material changes, dispositions, waivers, sign off readiness | Import or edit mappings |
| `admin` | Relay platform admin | Manage users, AI settings | Approve financial changes (by default) |
| `viewer` | Stakeholders | Read | Write |

In MVP, roles are global per user. Per-migration membership is post-MVP.

---

## 4. MVP definition

### 4.1 MVP goal

> An operator can open the fictional **Brightwater Provisions** migration, immediately see *why it cannot go live*, drill from each blocking reconciliation discrepancy to the exact source rows responsible, use an AI investigator that cites verifiable evidence, push fixes through a two-person approval flow, rerun the pipeline, and watch gates turn green — with every step reproducible and every change attributable in the audit log. The same flow works on a new migration built from uploaded CSVs, and every deterministic part works with no AI key configured.

### 4.2 In MVP

**Workspace**
- Companies, migrations, conversion plan (opening balance date, history window, cutover date, go-live date, functional currency, fiscal calendar).
- Source systems and datasets (typed by dataset type).
- Portfolio page listing migrations with readiness state and top blockers.

**Ingestion (CSV only)**
- Upload CSV per dataset; content-hash idempotency; import versions with supersession.
- Hardened parsing: size/row/field limits, encoding detection (UTF-8/UTF-8-BOM/Windows-1252), delimiter detection, malformed row quarantine with physical line numbers.
- Raw rows stored immutably as strings, exactly as read.

**Supported dataset types**

| Dataset type | Role | History or open items |
|---|---|---|
| `legacy_coa` | Legacy chart of accounts | Master |
| `target_coa` | Target chart of accounts | Master |
| `gl_detail` | Journal lines | History window |
| `trial_balance` | **Control**: TB by account by period (incl. opening) | Control |
| `customers`, `vendors` | Party masters | Master |
| `invoices`, `bills` | AR/AP documents (header level) | History + open at cutover |
| `payments` | Customer receipts and vendor payments with applications | History |
| `ar_aging`, `ap_aging` | **Control**: open items at cutover | Control |
| `bank_transactions` | Bank statement lines incl. post-cutover clearing window | Control + detail |
| `fx_rates` | Daily rates to functional currency | Reference |

**Profiling** — per import: row counts, null rates, distinct counts, inferred types, date ranges and ambiguous date formats, currency distribution, invalid identifiers, duplicate natural keys, numeric format anomalies (thousands separators, parentheses negatives, decimal comma), instruction-like text in free-text fields.

**Mapping**
- Column mapping sets per dataset (source column → canonical field + typed transform), versioned.
- Account mapping sets (legacy account → target account, many-to-one only), versioned.
- Deterministic suggestions (normalized header synonyms; account code/name matching with type compatibility).
- AI suggestions (optional) presented alongside deterministic signals.
- Approval via change request; approved version becomes active.

**Pipeline (recomputable)**
- Normalize → resolve entities → validate → reconcile → evaluate issues → evaluate readiness.
- Each run records an **input fingerprint** (active imports, mapping versions, overlays, policy, rule set version). Unchanged fingerprint ⇒ identical results.
- Staged canonical records with lineage back to source rows.

**Entity resolution** — customers and vendors: deterministic candidates with features; decisions (`same_entity`, `distinct`) as approved overlays keyed on source natural keys.

**Validation** — extensible rules engine; ~40 rules across structure, GL, CoA/mapping, AR, AP, payments, currency, parties, dates (catalog in [validation-and-reconciliation.md](validation-and-reconciliation.md)).

**Reconciliation** — six reconciliations with record-level drill-down and deterministic explainers:
R1 TB control vs GL detail · R2 legacy vs staged through mapping · R3 AR subledger vs GL control and AR aging · R4 AP equivalent · R5 cash vs bank with reconciling items · R6 activity counts/totals by period.

**Issues** — generated from exceptions with stable fingerprints; lifecycle with run-verified resolution, dispositions, ownership, comments, history, related-issue linking, amount at risk.

**Change requests & approvals** — kinds: column mapping set, account mapping set, record override, entity decision, disposition, policy change, gate waiver, readiness sign-off. Policy-driven approver requirements, SoD, staleness.

**Readiness** — 12 deterministic gates bound to a pipeline run; waivers for waivable gates; dual sign-off.

**Audit** — append-only, transactional, hash-chained; filterable log UI; chain verification endpoint.

**AI (optional, provider-abstracted)**
- Investigator agent over read-only tools, producing schema-validated findings with verified provenance.
- Mapping suggestions.
- Operator can promote a finding's suggested action to a *draft* change request.
- Works with Anthropic; a scripted provider for tests; a disabled mode that hides AI affordances.

**Demo** — deterministic generator for Brightwater Provisions with 13 seeded defects and 5 false-positive traps, a golden manifest of expected issues, and a scripted walkthrough.

### 4.3 Explicitly post-MVP

| Deferred | Reason |
|---|---|
| Live connectors (NetSuite, QuickBooks Online, Xero, Stripe, Plaid) | The connector interface is designed in MVP; implementations are integration work that adds no correctness insight. |
| XLSX/JSON ingestion | CSV proves the ingestion architecture; XLSX adds macro/formula safety work. |
| Multi-entity, intercompany, consolidation | Large accounting surface; would dilute depth. |
| FX revaluation, multi-book, dimensions (class/department/location) | Canonical model reserves fields; engines don't use them. |
| One-to-many account mapping (splits by dimension/rule) | Requires allocation rules and their own reconciliation. |
| Invoice/bill line items, inventory, fixed assets, payroll | Header-level subledgers are sufficient for AR/AP tie-outs. |
| Loading into a target ERP / export packages | Relay's MVP value is proving readiness, not the load. |
| Real authentication (OIDC/SSO), per-migration membership, row-level security | Dev identity is isolated behind one dependency. |
| Rule authoring UI / rule DSL | Rules are code in MVP (testable, reviewable). |
| SQL pushdown rules, partitioned staging, S3 storage | Needed beyond the scale envelope. |
| Notifications, Slack, SLAs, cross-migration analytics, learning mappings across migrations | Operational polish. |
| AI remediation drafting beyond "promote to draft", AI auto-triage | Kept deliberately narrow until evals justify more. |

---

## 5. Core workflow

```
Plan → Import → Profile → Map → Run pipeline ──────────────────────────────┐
                             (normalize → resolve → validate → reconcile)   │
                                                                             ▼
                    Launch ◄── Sign-off ◄── Readiness gates ◄── Issues ◄── Exceptions
                                                  ▲               │
                                                  │               ▼
                                          Rerun ◄─┴── Change requests (approved overlays)
                                                          ▲
                                                          │
                                              Investigate (deterministic drill-down + AI findings)
```

The loop that matters is **Issue → Investigate → Change request → Approve → Rerun → Verified**. Everything in the UI should shorten that loop.

---

## 6. Reconciliation philosophy (why Relay is credible)

Relay reconciles along two axes:

- **Completeness (detail vs. control):** does the extracted detail add up to what the legacy system itself reports? GL detail vs. TB; open invoices vs. AR aging; cash GL vs. bank statement. This catches dropped rows, export filters and corrupted files.
- **Fidelity (source vs. staged):** after mapping, normalization and overlays, do balances, counts and subledgers still tie? Legacy TB rolled up through the account mapping vs. staged balances; staged AR subledger vs. staged AR control account. This catches mapping errors and transformation bugs.

A discrepancy is never just a number. Every reconciliation result can be drilled down: *result → contributing records on each side → set difference by natural key → source row with file and line number → related exceptions and issues.* Where one side is an aggregate report (a TB line), drill-down narrows to account × period and shows the candidate detail on the other side, and says so.

Deterministic **explainers** classify known reconciling items (outstanding checks, deposits in transit, difference equal to a single mapped account's contribution). Only the *unexplained* remainder fails a gate, and explained items remain visible.

---

## 7. Key product concepts (glossary)

| Term | Definition |
|---|---|
| **Migration** | One customer's move to the new ERP, with a conversion plan. |
| **Dataset** | A typed slot (e.g. `invoices` from source system X) that has import versions; exactly one active import. |
| **Import** | One uploaded file for a dataset. Immutable. Identical file re-upload is a no-op. |
| **Canonical record** | A normalized, typed record in Relay's Canonical Accounting Model, produced by a pipeline run, with lineage. |
| **Natural key** | Stable business identity of a record across runs (`invoice:INV-10877`, `je:JE-2026-0412`). |
| **Pipeline run** | Deterministic computation of staged records, exceptions, reconciliations and readiness from an input fingerprint. |
| **Overlay** | An approved, versioned modification input to the pipeline: mapping version, record override, entity decision, disposition, policy. |
| **Exception** | A rule or reconciliation failure in a specific run. |
| **Issue** | A workflow object grouping exceptions with the same fingerprint across runs. |
| **Finding** | A structured AI hypothesis with cited evidence, attached to an issue or investigation. |
| **Change request (CR)** | A proposed overlay or decision with evidence, awaiting approvals. |
| **Disposition** | An approved decision to accept or carry forward an issue rather than fix it in migration data. |
| **Gate** | A deterministic readiness criterion evaluated on a run. |
| **Amount at risk** | Rule-defined monetary attention metric, deduplicated by record. |

---

## 8. UX specification

Relay is an operations tool. Density, evidence and next actions beat whitespace and chat.

### 8.1 Navigation

- **Portfolio** (global): migrations with readiness state, failing gate count, amount at risk, go-live date, days to go-live, owner.
- **Within a migration:**
  - **Overview** — "What is blocking this customer from going live?"
  - **Data** — source systems, datasets, imports, profiles, row viewer
  - **Mappings** — column mappings per dataset; account mapping
  - **Runs** — pipeline runs, fingerprints, what changed between runs
  - **Validation** — rules with exception counts; exception tables
  - **Reconciliation** — the six reconciliations; drill-down
  - **Entities** — duplicate candidates and decisions
  - **Issues** — queue with filters (owner, severity, nature, gate)
  - **Approvals** — change requests awaiting me / by me / all
  - **Readiness** — gates, evidence, waivers, sign-off
  - **Audit Log**
  - **Settings** — conversion plan, policy (tolerances, thresholds), AI enablement for this migration
- **Record inspector** — a global side panel opened from any record reference: canonical values, source row raw values with file/line, lineage, overlays applied, related exceptions/issues.

Changed from the brief: "Migration" is not a tab but the workspace; **Runs**, **Entities** and **Readiness** are first-class because they carry evidence the brief assumed would live elsewhere.

### 8.2 Migration Overview (the most important screen)

Top to bottom:

1. **Readiness banner** — `NOT READY · 9 of 12 gates failing · evaluated on Run #14 (current)`, or `RESULTS STALE — inputs changed since Run #14 · Rerun`.
2. **Blockers** — each failing gate with the specific cause in one line and a link to evidence:
   *"R3 AR subledger does not tie: GL 1200 differs from open items by (29,060.00) USD · 2 issues · owner Maya Chen"*.
3. **Amount at risk** — unresolved, by nature (`migration_defect` / `source_anomaly`), with the top 5 issues.
4. **My queue** — issues I own, approvals waiting on me.
5. **Pipeline stages** — Import → Profile → Map → Normalize → Validate → Reconcile with status and counts per stage.
6. **Recent activity** — last audit events.

### 8.3 UX rules

- Every number that summarizes records is clickable to those records.
- Money: always with currency; right-aligned; tabular numerals; negative values in parentheses; server-provided strings, never recomputed in the browser.
- Status is never color alone (text + icon).
- Business dates shown as dates (no timezone); system times in viewer timezone with UTC on hover.
- AI content is visibly distinct, labelled "AI finding", shows provenance-verification status, and has no controls that change financial state — only "Accept finding", "Dismiss", and "Draft change request".
- Stale results are shown as stale everywhere, not only on the overview.

---

## 9. Non-goals

- Relay is not a general-purpose ETL or data warehouse.
- Relay does not post journal entries into any live accounting system.
- Relay does not decide accounting treatment; it surfaces evidence and records human decisions.
- Relay does not produce a "readiness percentage".

---

## 10. Success criteria for the portfolio

A reviewer from an accounting-software company should, within ten minutes of the demo, be able to say:

1. The reconciliations are the right ones and actually catch what they claim to.
2. I could reproduce any result and see exactly who changed what, when, and on what evidence.
3. The AI helped investigate, and could not have silently changed anything.
4. The go-live decision is explicit and falsifiable.
5. The code quality (types, tests, migrations, error handling) is what I'd accept in production.
