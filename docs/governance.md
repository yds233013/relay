# Relay — Governance: Issues, Change Requests, Approvals, Audit, Readiness

Status: **Planned.**

Related: [data-model.md](data-model.md) · [validation-and-reconciliation.md](validation-and-reconciliation.md) · [ai-safety.md](ai-safety.md)

This document defines how state changes in Relay. The short version:

> Nothing that affects financial outcomes changes except by applying an approved change request. Every change writes an audit event in the same transaction. Issues close only when a rerun proves them gone, or when an authorized person records a disposition. Go-live is a set of gates evaluated on a specific run, signed by two people.

---

## 1. Issue lifecycle

### 1.1 From exceptions to issues (pipeline stage 8)

For each run:

1. Group run exceptions by `fingerprint`.
2. For each fingerprint:
   - No issue exists → create issue (`status=open`, `first_seen_run_id`, severity = max exception severity, `amount_at_risk` = Σ over distinct subject records), audit `issue.created` (actor `system`).
   - Issue exists → link occurrence, update `last_seen_run_id`, severity, amount. If the issue was `resolved` → **reopen** (`status=open`, audit `issue.reopened` with reason `regression_detected_in_run_N`).
3. For each open-ish issue (`open`, `in_progress`, `awaiting_verification`) whose fingerprint is **absent** in this run → `resolved`, `verified_absent_run_id = run`, audit `issue.verified_resolved`.
4. Create system `issue_links` (`same_root_cause` candidate) between issues sharing any subject natural key, or whose subjects share a document/entry key.

Only **current** runs (fingerprint = current fingerprint) mutate issues. Re-evaluating an old run never changes issues.

### 1.2 States

```
            ┌───────────── regression ─────────────┐
            ▼                                       │
  open ──► in_progress ──► awaiting_verification ──► resolved
   │            │                  ▲                   (only via absent-in-current-run)
   │            │                  │ CR applied
   │            └──── CR submitted ┘
   │
   ├──► dispositioned   (only via approved `disposition` CR)
   └──► (manual issues only) closed   (owner, with note; audited)
```

| Status | Entered by | Meaning |
|---|---|---|
| `open` | system / user | Needs attention |
| `in_progress` | owner | Being worked |
| `awaiting_verification` | system, when a linked CR is applied | Fix applied; next run will verify |
| `resolved` | **system only** | Fingerprint absent in a current run |
| `dispositioned` | **system**, when a `disposition` CR is applied | Accepted with documented decision; still visible; excluded from unresolved exposure |
| `closed` | owner | Manual issues only |

Users cannot set `resolved` directly. The API rejects it with `issue.resolution_requires_verification`.

`false_positive` is a disposition kind, not a status, so it requires an approval for `high`/`critical`.

### 1.3 Amount at risk

- Each exception carries an optional rule-defined `amount_at_risk` in functional currency.
- Issue amount = Σ `amount_at_risk` over distinct subject natural keys in the latest run (max per record if a rule emits several).
- Migration **unresolved exposure** = Σ over issues in (`open`, `in_progress`, `awaiting_verification`) of issue amount, deduplicated so a record appearing in multiple issues contributes its maximum once.
- Split by `nature` in the UI. Labelled "Amount at risk", with a tooltip explaining it is an attention metric.

---

## 2. Change requests

### 2.1 Kinds

| Kind | Payload | Applier effect |
|---|---|---|
| `column_mapping_set` | mapping set id (draft) | set → `approved`, previous → `superseded` |
| `account_mapping_set` | mapping set id (draft) | same |
| `record_override` | dataset type, natural key, field or quarantined row repair, expected current value, new value | insert `record_overrides` (`active`) |
| `entity_decision` | party type, decision, members, survivor, survivorship | insert `entity_decisions` |
| `disposition` | issue id, kind, amount, follow-up, owner | insert `dispositions`; issue → `dispositioned` |
| `policy_change` | JSON patch against current policy / conversion plan | insert `policy_versions` n+1 (or update migration conversion plan) |
| `gate_waiver` | gate id, run fingerprint, reason, expiry (optional) | insert waiver record referenced by gate evaluation |
| `readiness_signoff` | readiness evaluation id, run id, fingerprint | record sign-off bound to fingerprint |
| `revert` | target overlay id | overlay `status=reverted` |

Every applier is a function `apply(cr, uow) -> AppliedEffect` that runs inside the approval transaction, writes its own audit events, and enqueues a pipeline run when the fingerprint changes.

### 2.2 States

```
draft ──submit──► submitted ──(all requirements met)──► approved ──apply──► applied
  │                 │   │                                     └──(apply error)──► failed_to_apply
  │                 │   └──reject (any reviewer)──► rejected
  │                 └──base changed──► stale ──(requester refreshes → new draft)──►
  └──withdraw──► withdrawn  (also from submitted)
```

- **Submit**: server computes `before`, `after`, `impact`, `required_approvals` (from policy), records `base_fingerprint` and `base_entity_versions`. Justification required.
- **Staleness**: on every approve attempt and whenever a CR is applied, submitted CRs whose `base_entity_versions` no longer match become `stale` (audited). A stale CR cannot be approved; approvals already given are void.
- **Approve**: allowed if the reviewer ≠ requester, has not already approved this CR, has a role that satisfies an unmet requirement, and the CR is not stale. When all requirements are satisfied, the CR is approved and applied **in the same transaction**.
- **Reject**: any eligible reviewer; comment required.
- Approval and application are atomic: there is never an approved-but-unapplied CR except `failed_to_apply`, which is a bug surfaced as a critical system issue.

### 2.3 Default approval policy (per migration, changeable via `policy_change`)

| Kind | Required approvals |
|---|---|
| `column_mapping_set` | 1 × `implementation_lead` |
| `account_mapping_set` | 1 × `implementation_lead` **and** 1 × `customer_controller` |
| `record_override` | 1 × `implementation_lead`; **plus** 1 × `customer_controller` if \|impact\| ≥ 10,000.00 functional or the field is a date/period/account/amount |
| `entity_decision` | 1 × `implementation_lead` |
| `disposition` (`accepted_risk`, `carry_forward_adjustment`, `false_positive` on high/critical) | 1 × `customer_controller` |
| `disposition` (low/medium `false_positive`, `not_applicable`) | 1 × `implementation_lead` |
| `policy_change` | 1 × `implementation_lead` **and** 1 × `customer_controller` |
| `gate_waiver` | 1 × `implementation_lead` **and** 1 × `customer_controller` |
| `readiness_signoff` | 1 × `implementation_lead` **and** 1 × `customer_controller` |
| `revert` | same as the reverted kind |

Rules that are not configurable:
- Requester can never approve their own CR.
- One user satisfies at most one requirement per CR.
- A `policy_change` cannot reduce its own approval requirements in the same CR.
- AI is never a requester or reviewer. `origin=ai_finding` CRs are requested by the human who drafted them.

---

## 3. Audit log

### 3.1 Guarantees

| Guarantee | Mechanism |
|---|---|
| Every governed mutation is logged | Services call `audit.record(...)` inside the unit of work; a test asserts that each service method that commits emits ≥ 1 event (instrumented UoW). |
| No logged-but-not-applied or applied-but-not-logged | Same transaction. Rollback test in integration suite. |
| Append-only | No update/delete code path; DB trigger rejects UPDATE/DELETE/TRUNCATE; app role lacks those privileges. |
| Tamper-evident | Per-migration hash chain; `GET /audit-events/verify` and `relay verify-audit` recompute and report the first broken link. |
| Ordered | `migration_seq` assigned under a per-migration advisory lock. |
| Honest limits | A DB superuser can rewrite the table and chain. Documented; post-MVP option: periodic anchoring of chain heads to external storage. |

### 3.2 Answering the audit questions

| Question | Field(s) |
|---|---|
| Who changed what? | `actor_type`, `actor_user_id`, `action`, `entity_type`, `entity_id` |
| When? | `occurred_at` (+ `migration_seq` for order) |
| Why? | `reason` (CR justification / comment) |
| Based on what evidence? | `evidence_refs`, and the linked CR's `evidence_refs` and `origin_finding_id` |
| Previous value? | `before` |
| Was approval required? | `change_request_id` present; CR `required_approvals` |
| Who approved? | `change_request.approved` events + `approvals` rows |

### 3.3 Action taxonomy (initial)

```
migration.created | migration.conversion_plan_changed | migration.status_changed
source_system.created | dataset.created
import.uploaded | import.duplicate_upload_ignored | import.parsed | import.failed | import.activated | import.superseded
mapping_set.draft_created | mapping_set.draft_updated | mapping_set.approved | mapping_set.superseded
pipeline_run.requested | pipeline_run.succeeded | pipeline_run.failed | pipeline_run.staged_records_pruned
issue.created | issue.assigned | issue.status_changed | issue.reopened | issue.verified_resolved | issue.dispositioned | issue.commented
change_request.drafted | .submitted | .approval_recorded | .approved | .rejected | .withdrawn | .stale | .applied | .failed_to_apply
override.activated | override.reverted | entity_decision.activated | entity_decision.reverted
policy.version_created | gate.waived | readiness.evaluated | readiness.signed_off | readiness.signoff_invalidated
investigation.started | investigation.completed | investigation.failed
finding.created | finding.accepted | finding.dismissed | finding.drafted_change_request
ai.suggestion_created | ai.suggestion_accepted | ai.suggestion_rejected
user.dev_identity_assumed   (local/test only)
```

`before`/`after` hold minimal, typed diffs — not full row dumps — and never raw source row values beyond the specific field changed.

---

## 4. Launch readiness

### 4.1 Evaluation model

- One `readiness_evaluation` per successful pipeline run, computed from that run and the governance state at the time.
- Readiness displayed for a migration = evaluation of the **current** run. If no current run exists, the migration shows `STALE` and is not ready by definition.
- `overall = ready` iff every **blocking** gate is `pass` or `waived`.
- Each gate returns: `status`, `observed`, `threshold`, one-line `summary`, and `evidence_refs` (issues, recon lines, CRs, datasets).

### 4.2 Gates (MVP)

| Gate | Passes when | Blocking | Waivable |
|---|---|---|---|
| **G1 Required datasets** | Every `is_required` dataset has an active import with status `parsed` and 0 quarantined rows unresolved (quarantine issues resolved/dispositioned) | yes | no |
| **G2 Column mappings approved** | Every dataset with an active import has an approved column mapping set covering all required canonical fields | yes | no |
| **G3 Account mapping complete** | Approved account mapping set; 0 `MAP.ACCOUNT_UNMAPPED` / `MAP.TARGET_ACCOUNT_EXISTS` exceptions | yes | no |
| **G4 Results current** | Evaluated run's fingerprint = current fingerprint and run succeeded with no `errored` rules/recons | yes | no |
| **G5 No blocking exceptions** | 0 issues of severity `critical` not resolved; 0 `high` not resolved or dispositioned | yes | no |
| **G6 Ledger ties** | R1 and R2 have 0 `discrepancy` lines for all periods in window | yes | yes (controller + lead; per period, with reason) |
| **G7 Subledgers tie** | R3, R3b, R4, R4b have 0 `discrepancy` lines at cutover | yes | yes |
| **G8 Cash reconciled** | R5 unexplained difference ≤ tolerance; all `BANK.UNRECORDED_ACTIVITY` issues resolved or dispositioned | yes | yes |
| **G9 Exposure below threshold** | Unresolved exposure ≤ `policy.max_unresolved_exposure` (default 1,000.00) | yes | yes |
| **G10 Entities decided** | 0 open entity candidates with score ≥ strong threshold | yes | no |
| **G11 No pending changes** | 0 change requests in `submitted` or `stale` | yes | no |
| **G12 Signed off** | An applied `readiness_signoff` CR whose fingerprint = evaluated run fingerprint | yes | no |

G12 is evaluated after G1–G11: a sign-off CR cannot be submitted unless G1–G11 pass (or are waived) on the current run. Any later fingerprint change invalidates the sign-off (audited `readiness.signoff_invalidated`).

### 4.3 Waivers

- Only for gates marked waivable.
- Bound to the gate and the run fingerprint at approval; a new fingerprint requires re-evaluating whether the waiver still applies — waivers carry a `scope` (e.g. `{"recon":"R1","period":"2026-03"}`) and remain valid across fingerprints only if the waived lines' unexplained amounts are unchanged. Otherwise they lapse (audited).
- Displayed on the gate with reason, approvers and scope. Waived ≠ passing in the UI.

### 4.4 What the overview shows

For each failing blocking gate: gate name, one-line summary with the governing number, owner of the largest contributing issue, and a link straight to evidence. Order: G4 (stale) first, then gates by unresolved amount descending.
