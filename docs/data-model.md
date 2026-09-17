# Relay — Data & Domain Model

Status: **Implemented in M3 with documented deviations** ([decisions/0004-persistence-and-pipeline.md](decisions/0004-persistence-and-pipeline.md)): one semi-typed `staged_records` table instead of per-type staged tables, policy versions under workspace, overlay tables deferred to M5–M7. Changes must update this document.

Related: [architecture.md](architecture.md) · [governance.md](governance.md) · [security-and-correctness.md](security-and-correctness.md)

---

## 1. Global conventions

| Concern | Rule |
|---|---|
| Primary keys | `id UUID` (UUIDv7, generated in application) |
| Monetary amounts | `NUMERIC(20,4)`; Python `Decimal`; never float. Column suffix `_amount`. Always paired with a currency column in the same row or an unambiguous parent. |
| Functional amounts | `functional_amount NUMERIC(20,4)` in the migration's functional currency |
| Sign convention | Canonical ledger amounts are **signed: debit positive, credit negative**. Documents (invoices, bills, payments) store positive document amounts with an explicit `direction`. |
| Currency | `CHAR(3)` ISO 4217, validated against a static table with minor units |
| FX rates | `NUMERIC(20,10)` |
| Business dates | `DATE` (no timezone). Suffix `_date`. |
| System timestamps | `TIMESTAMPTZ`, UTC. Suffix `_at`. |
| Fiscal period | `CHAR(7)` `YYYY-MM` for monthly calendars; derived, never trusted from source without a check |
| Enums | Postgres `TEXT` + `CHECK` constraint (easier migrations than native enums), mirrored as Python `StrEnum` |
| JSON | `JSONB`, always validated by a Pydantic model on write |
| Row versioning | Mutable tables have `version INT NOT NULL` for optimistic concurrency |
| Soft delete | None. Workflow objects change status; data rows are immutable. |
| Audit columns | `created_at`, `created_by` on all tables; `updated_at` on mutable tables. The audit log is the history, not these columns. |

---

## 2. Entity overview

```
Company 1─* Migration 1─* SourceSystem 1─* Dataset 1─* Import 1─* SourceRow
                │                             │           └─1 DatasetProfile
                │                             └─* ColumnMappingSet 1─* ColumnMapping
                ├─* AccountMappingSet 1─* AccountMapping
                ├─* RecordOverride ─┐
                ├─* EntityDecision ─┼─ each created by an approved ChangeRequest
                ├─* Disposition ────┤
                ├─* PolicyVersion ──┘
                ├─* PipelineRun 1─* Staged* (canonical records, lineage)
                │        ├─* RuleRun 1─* RuleException
                │        ├─* ReconciliationResult 1─* ReconciliationLine 1─* ReconcilingItem
                │        ├─* EntityCandidate
                │        └─1 ReadinessEvaluation 1─* GateResult
                ├─* Issue *─* RuleException (via IssueOccurrence)   ── Comment, IssueLink
                ├─* ChangeRequest 1─* Approval
                ├─* Investigation 1─* InvestigationStep, 1─* Finding
                └─* AuditEvent (append-only, hash-chained)
```

---

## 3. Identity

### `users`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| email | citext unique | |
| display_name | text | |
| role | text check in (`implementation_specialist`,`implementation_lead`,`customer_controller`,`admin`,`viewer`) | global in MVP |
| is_active | bool | |

Actors in audit and CRs reference `users.id`. System and AI actors are represented by `actor_type` fields, not fake users.

---

## 4. Workspace

### `companies`
`id, name, legal_name, country, functional_currency char(3), fiscal_year_start_month smallint (1–12), created_at, created_by`

### `migrations`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| company_id | fk | |
| name | text | |
| status | text | `planning`, `in_progress`, `signed_off`, `launched`, `archived` |
| functional_currency | char(3) | copied from company at creation; immutable after first run |
| opening_balance_date | date | balances as of this date are the starting point (e.g. 2025-12-31) |
| history_start_date | date | first day of transaction history (e.g. 2026-01-01) |
| cutover_date | date | last day of legacy transactions (e.g. 2026-06-30) |
| go_live_date | date | first day in new ERP (e.g. 2026-07-01) |
| bank_clearing_window_days | int | post-cutover bank activity imported for clearing (default 15) |
| lead_user_id | fk users | |
| ai_enabled | bool | customer consent for AI processing; default false |
| version | int | |

Check constraints: `opening_balance_date < history_start_date <= cutover_date < go_live_date`.
Conversion-plan fields change only through a `policy_change` change request.

### `source_systems`
`id, migration_id, name, kind (legacy_erp|spreadsheet|bank|billing|crm|other), description, created_*`

### `datasets`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| migration_id | fk | |
| source_system_id | fk | |
| dataset_type | text | see §4.1 |
| name | text | |
| is_required | bool | from migration template; drives gate G1 |
| active_import_id | fk imports nullable | |
| version | int | |

Unique: `(migration_id, source_system_id, dataset_type)`.

### 4.1 Dataset types (code registry, not a table)

`legacy_coa`, `target_coa`, `gl_detail`, `trial_balance`, `customers`, `vendors`, `invoices`, `bills`, `payments`, `ar_aging`, `ap_aging`, `bank_transactions`, `fx_rates`.

Each type declares in code: canonical target type, required canonical fields, natural-key fields, whether it is a **control** dataset, and header synonyms for deterministic column suggestions.

---

## 5. Ingestion

### `stored_files`
`id, sha256 char(64) unique, size_bytes bigint, media_type text, storage_key text, first_uploaded_at, first_uploaded_by`
The original filename is **not** stored here (it's per-import display metadata).

### `imports`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| dataset_id | fk | |
| stored_file_id | fk | |
| sequence | int | 1, 2, 3… per dataset |
| original_filename | text | sanitized, display only |
| status | text | `pending`, `parsing`, `parsed`, `failed`, `superseded` |
| encoding, delimiter | text | detected, recorded |
| header | jsonb | list of header strings as read |
| row_count, quarantined_count | int | |
| error | jsonb nullable | structured failure |
| started_at, completed_at | timestamptz | |
| created_by | fk | |

Unique: `(dataset_id, stored_file_id)` — the idempotency guarantee.

### `source_rows` (immutable)
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| import_id | fk | |
| row_number | int | 1-based data row index |
| line_start, line_end | int | physical lines in file (for multi-line quoted fields) |
| values | jsonb | `{header: raw string}` exactly as read; no trimming |
| row_hash | char(64) | sha256 of canonical values |

Unique: `(import_id, row_number)`. Trigger rejects `UPDATE`/`DELETE`.

### `quarantined_rows` (immutable)
`id, import_id, line_start, line_end, raw_text text (bounded), reason (field_count_mismatch|unterminated_quote|field_too_long|encoding_error), expected_fields int, actual_fields int`

### `dataset_profiles`
`id, import_id unique, profiler_version, profile jsonb (DatasetProfile), computed_at`

`DatasetProfile` (Pydantic): per column `{inferred_type, null_count, distinct_count, sample_values (redacted per policy), min/max for dates/numbers, date_format_candidates, ambiguous_date_count, numeric_format_flags, invalid_identifier_count, instruction_like_text_count}`; dataset-level `{row_count, duplicate_natural_keys, date_range, currency_distribution}`.

---

## 6. Mapping

### `column_mapping_sets`
`id, dataset_id, version int, status (draft|pending_approval|approved|superseded|rejected), based_on_import_id, change_request_id nullable, created_*, version_lock int`
Unique: `(dataset_id, version)`. At most one `approved` (active) per dataset (partial unique index).

### `column_mappings`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| mapping_set_id | fk | |
| target_field | text | canonical field name, validated against dataset type |
| source_columns | text[] | usually one |
| transform | jsonb | discriminated union, see below |
| basis | text | `exact`, `synonym`, `operator`, `ai_suggested` |
| rationale | text nullable | |

Transforms (MVP, closed set — no arbitrary expressions):
`copy`, `trim`, `upper`, `parse_decimal{decimal_separator, thousands_separator, parentheses_negative, strip_currency_symbols}`, `parse_date{format}` (explicit format required), `debit_credit_to_signed{debit_column, credit_column}`, `sign_flip`, `constant{value}`, `value_map{mapping, default}`, `concat{separator}`, `default_currency{currency}`.

### `account_mapping_sets`
`id, migration_id, version, status, change_request_id, created_*` — unique `(migration_id, version)`, one active.

### `account_mappings`
`id, mapping_set_id, legacy_account_code, target_account_code, basis (exact|name_match|operator|ai_suggested), rationale` — unique `(mapping_set_id, legacy_account_code)`. Many-to-one only (enforced by unique legacy code).

---

## 7. Overlays (created only by applying approved change requests)

### `record_overrides`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| migration_id | fk | |
| dataset_type | text | |
| natural_key | text | e.g. `je:JE-AP-20455` or `gl_line:JE-AP-20455:2` |
| target | text | `canonical_field` or `quarantined_row_repair` |
| field | text nullable | canonical field |
| expected_current_value | jsonb | value the override was written against; mismatch at run time → `OVERRIDE.STALE` exception, override not applied |
| new_value | jsonb | |
| reason | text | required |
| change_request_id | fk | |
| status | text | `active`, `reverted` |
| version | int | |

Overrides apply at canonical level (after column mapping), never to `source_rows`.

### `entity_decisions`
`id, migration_id, party_type (customer|vendor), decision (same_entity|distinct), member_natural_keys text[] (sorted), survivor_natural_key nullable, survivorship jsonb (field→source natural key), reason, change_request_id, status (active|reverted)`

### `dispositions`
`id, migration_id, issue_id, kind (carry_forward_adjustment|accepted_risk|false_positive|not_applicable), amount, currency, follow_up (text, e.g. "Post correcting JE in new ERP in July"), follow_up_owner_id, reason, change_request_id, status`

### `policy_versions`
`id, migration_id, version, policy jsonb (ReadinessPolicy + rule params + severity overrides + tolerances + approval policy), change_request_id, created_*` — unique `(migration_id, version)`.

---

## 8. Canonical Accounting Model & staged records

All staged tables share: `run_id fk`, `id uuid`, `natural_key text`, `source_row_ids uuid[]` (lineage), `overrides_applied uuid[]`. Unique `(run_id, natural_key)`.

| Table | Key fields |
|---|---|
| `stg_accounts` | `side (legacy|target)`, `code`, `name`, `account_type (asset|liability|equity|revenue|expense)`, `subtype` (e.g. `accounts_receivable`, `accounts_payable`, `cash`, `contra_asset`, `retained_earnings`, `suspense`), `normal_balance (debit|credit)`, `is_active` |
| `stg_parties` | `party_type`, `source_code`, `name`, `normalized_name`, `tax_id_last4`, `address_line1`, `city`, `region`, `postal_code`, `country`, `email_domain`, `default_currency`, `is_active`, `cluster_id` (from entity resolution), `notes_redacted` |
| `stg_journal_entries` | `entry_number`, `entry_date`, `posting_period`, `derived_period`, `source_module (gl|ar|ap|bank|manual)`, `memo`, `is_reversal_of` |
| `stg_journal_lines` | `entry_natural_key`, `line_number`, `legacy_account_code`, `target_account_code nullable`, `amount` (signed, txn currency), `currency`, `functional_amount` (signed), `party_natural_key nullable`, `document_natural_key nullable`, `memo` |
| `stg_balances` | control TB: `legacy_account_code`, `period`, `balance_type (opening|period_activity|closing)`, `functional_amount` (signed) |
| `stg_documents` | invoices & bills: `document_type (invoice|bill|credit_memo|vendor_credit)`, `document_number`, `party_natural_key`, `party_reference` (vendor's invoice no.), `document_date`, `due_date`, `currency`, `subtotal_amount`, `tax_amount`, `total_amount`, `fx_rate`, `functional_total_amount`, `status_at_cutover (open|paid|void)`, `open_amount_at_cutover` |
| `stg_payments` | `payment_number`, `direction (received|disbursed)`, `method (check|ach|wire|card)`, `reference` (check no.), `party_natural_key`, `payment_date`, `currency`, `amount`, `functional_amount`, `unapplied_amount`, `bank_account_code` |
| `stg_payment_applications` | `payment_natural_key`, `document_natural_key`, `applied_amount`, `applied_functional_amount` |
| `stg_aging_items` | control: `aging_type (ar|ap)`, `party_source_code`, `document_number`, `as_of_date`, `open_amount`, `currency`, `functional_open_amount` |
| `stg_bank_transactions` | `bank_account`, `posted_date`, `description`, `amount` (signed, + inflow), `reference`, `running_balance nullable`, `statement_ending_balance nullable` |
| `stg_fx_rates` | `rate_date`, `from_currency`, `to_currency`, `rate` |
| `stg_party_clusters` | `cluster_id`, `party_type`, `member_natural_keys`, `survivor_natural_key`, `decision_id nullable` |

### 8.1 Natural keys

Deterministic strings, defined in `canonical/natural_keys.py`:

| Record | Natural key |
|---|---|
| legacy account | `acct:legacy:{code}` |
| target account | `acct:target:{code}` |
| customer / vendor | `party:{customer|vendor}:{source_code}` |
| journal entry | `je:{entry_number}` |
| journal line | `jl:{entry_number}:{line_number}` |
| TB balance | `tb:{code}:{period}:{balance_type}` |
| invoice / bill | `doc:{invoice|bill}:{document_number}` |
| payment | `pay:{direction}:{payment_number}` |
| application | `app:{payment_number}:{document_number}` |
| aging item | `aging:{ar|ap}:{document_number}` |
| bank txn | `bank:{account}:{posted_date}:{sha256(desc|amount|reference|ordinal)[:12]}` |

Duplicate natural keys within an import produce `NORM.DUPLICATE_NATURAL_KEY` and are disambiguated with `#n` suffix so no data is dropped.

### 8.2 `RecordRef` (API/AI/evidence shape)

```json
{ "kind": "staged", "record_type": "document", "natural_key": "doc:invoice:INV-10877", "run_id": "…", "id": "…" }
{ "kind": "source_row", "import_id": "…", "row_number": 14322, "line_start": 14322, "line_end": 14323 }
{ "kind": "quarantined_row", "id": "…" }
```

---

## 9. Pipeline runs & results

### `pipeline_runs`
`id, migration_id, sequence int, fingerprint char(64), fingerprint_components jsonb, status (queued|running|succeeded|failed), error jsonb, triggered_by_user_id nullable, trigger (manual|change_request_applied|import_activated), change_request_id nullable, stage_timings jsonb, counts jsonb, started_at, finished_at, staged_records_pruned_at nullable`
Unique partial: `(migration_id, fingerprint) WHERE status='succeeded'`.

### `rule_runs`
`id, run_id, rule_id text, rule_version int, status (passed|failed|not_applicable|errored), exception_count, duration_ms, params jsonb`

### `rule_exceptions`
| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| run_id | fk | |
| rule_id, rule_version | | |
| fingerprint | char(64) | `sha256(rule_id + sorted subject natural keys + discriminator)`; **excludes amounts and run id** |
| severity | text | effective severity after policy overrides |
| nature | text | `migration_defect`, `source_anomaly` |
| subject_refs | jsonb | `RecordRef[]` |
| message | text | deterministic template output |
| expected | jsonb nullable | |
| observed | jsonb nullable | |
| amount_at_risk | numeric(20,4) nullable | functional currency, ≥ 0 |
| details | jsonb | rule-specific typed payload |

### `reconciliation_results`
`id, run_id, recon_id, recon_version, grain text[], status (tied|tied_with_explained_items|discrepancy|not_applicable|errored), left_label, right_label, left_total, right_total, difference, explained_total, unexplained_total, tolerance_amount, currency`

### `reconciliation_lines`
`id, result_id, grain_key jsonb (e.g. {"account":"1200","period":"2026-06"}), left_amount, right_amount, left_count, right_count, difference, explained_amount, unexplained_amount, status (tied|within_tolerance|explained|discrepancy|left_only|right_only)`

### `reconciling_items`
`id, line_id, explainer_id, classification (outstanding_check|deposit_in_transit|bank_only_activity|single_account_contribution|timing|rounding), amount, record_refs jsonb, message`

### `entity_candidates`
`id, run_id, party_type, left_natural_key, right_natural_key, score numeric(5,4), features jsonb (name_similarity, address_similarity, tax_id_match, email_domain_match, shared_document_references[], …), status (open|decided_same|decided_distinct), decision_id nullable`
Candidates with a matching decision are marked decided, not regenerated as open.

### `readiness_evaluations`
`id, run_id unique, policy_version, overall (ready|not_ready), evaluated_at`

### `gate_results`
`id, evaluation_id, gate_id, gate_version, status (pass|fail|waived|not_evaluated), blocking bool, observed jsonb, threshold jsonb, summary text, evidence_refs jsonb, waiver_change_request_id nullable`

---

## 10. Issues

### `issues`
| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| migration_id | fk | |
| key | text | human id `BWP-42` |
| fingerprint | char(64) nullable | null for manual issues; unique per migration |
| source | text | `rule`, `reconciliation`, `entity_resolution`, `manual` |
| rule_or_recon_id | text nullable | |
| category | text | `completeness`, `mapping`, `ledger_integrity`, `subledger`, `cash`, `master_data`, `currency`, `dates`, `ai_safety`, `other` |
| nature | text | `migration_defect`, `source_anomaly` |
| severity | text | `critical`, `high`, `medium`, `low` (max of current exceptions, or manual) |
| title | text | |
| status | text | see [governance.md](governance.md#issue-lifecycle) |
| owner_user_id | fk nullable | |
| amount_at_risk | numeric(20,4) | from latest run |
| first_seen_run_id, last_seen_run_id, verified_absent_run_id | fk nullable | |
| disposition_id | fk nullable | |
| gate_ids | text[] | gates this issue contributes to |
| version | int | |

### `issue_occurrences`
`issue_id, rule_exception_id, run_id` — links an issue to its exceptions in each run.

### `issue_links`
`id, from_issue_id, to_issue_id, link_type (same_root_cause|caused_by|blocks|duplicates), created_by_actor_type (system|user), reason` — system links are created when issues share a subject natural key.

### `issue_comments`
`id, issue_id, author_user_id, body text (markdown rendered as plain text + safe formatting), created_at` — immutable; edits create new comments.

---

## 11. Change requests & approvals

### `change_requests`
| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| migration_id | fk | |
| key | text | `CR-17` |
| kind | text | `column_mapping_set`, `account_mapping_set`, `record_override`, `entity_decision`, `disposition`, `policy_change`, `gate_waiver`, `readiness_signoff` |
| status | text | `draft`, `submitted`, `approved`, `rejected`, `withdrawn`, `applied`, `stale`, `failed_to_apply` |
| title | text | |
| justification | text | required on submit |
| payload | jsonb | typed per kind (Pydantic discriminated union) |
| before | jsonb | computed server-side at submit |
| after | jsonb | computed server-side at submit |
| impact | jsonb | e.g. `{amount_at_risk_delta, affected_records, affected_gates}` |
| evidence_refs | jsonb | `RecordRef[]`, issue ids, recon line ids, finding ids |
| related_issue_ids | uuid[] | |
| origin | text | `operator`, `ai_finding` |
| origin_finding_id | fk nullable | |
| requested_by | fk users | always a human |
| base_fingerprint | char(64) | fingerprint of the state `before` was computed from |
| base_entity_versions | jsonb | versions of the specific objects touched |
| required_approvals | jsonb | computed from policy at submit, e.g. `[{"role":"implementation_lead"},{"role":"customer_controller"}]` |
| submitted_at, decided_at, applied_at | timestamptz | |
| version | int | |

### `approvals`
`id, change_request_id, reviewer_user_id, reviewer_role_at_decision, decision (approve|reject), comment, satisfies_requirement_index int, decided_at`
Unique `(change_request_id, reviewer_user_id)`. Check (in service + DB trigger): `reviewer_user_id <> change_requests.requested_by`.

---

## 12. Audit

### `audit_events` (append-only)
| Column | Type | Notes |
|---|---|---|
| seq | bigserial pk | global order |
| id | uuid | |
| migration_id | uuid nullable | null for platform events |
| migration_seq | bigint | per-migration sequence (gapless within migration, assigned under advisory lock) |
| occurred_at | timestamptz | |
| actor_type | text | `user`, `system`, `ai` |
| actor_user_id | uuid nullable | for `ai`, the user who initiated the investigation |
| action | text | dotted: `import.activated`, `change_request.approved`, `issue.reopened`, … |
| entity_type, entity_id | text, uuid | |
| before, after | jsonb nullable | minimal diffs |
| reason | text nullable | |
| change_request_id | uuid nullable | |
| evidence_refs | jsonb nullable | |
| request_id | text | correlation |
| prev_hash | char(64) | hash of previous event in this migration's chain |
| hash | char(64) | `sha256(prev_hash ‖ canonical_json(event without hash))` |

Trigger rejects `UPDATE`, `DELETE`, `TRUNCATE`. The application DB role has `INSERT, SELECT` only on this table.

---

## 13. AI

### `investigations`
`id, migration_id, issue_id nullable, question text, status (queued|running|succeeded|failed|budget_exhausted), provider, model, prompt_version, run_id (the run it inspected), started_by, input_tokens, output_tokens, tool_call_count, started_at, finished_at, error jsonb`

### `investigation_steps`
`id, investigation_id, seq, type (model_message|tool_call|tool_result|final), tool_name nullable, arguments jsonb, result jsonb (bounded, redacted), result_sha256, truncated bool, latency_ms`

### `findings`
| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| investigation_id | fk | |
| issue_id | fk nullable | |
| hypothesis | text | ≤ 600 chars |
| evidence | jsonb | `[{claim, step_seqs[], record_refs[], quoted_values[]}]` |
| affected_record_refs | jsonb | |
| confidence | text | `low`, `medium`, `high` (model-reported) |
| suggested_action | jsonb | typed union, see ai-safety.md |
| requires_approval | bool | **computed by server policy**, not by the model |
| verification_status | text | `verified`, `partially_verified`, `failed` |
| verification_report | jsonb | per evidence item |
| review_status | text | `proposed`, `accepted`, `dismissed` |
| reviewed_by, reviewed_at, review_comment | | |

### `ai_suggestions`
`id, migration_id, kind (column_mapping|account_mapping|entity_explanation), subject jsonb, suggestion jsonb, supporting_signals jsonb (deterministic), provider, model, prompt_version, status (open|accepted|rejected), created_at`

---

## 14. Jobs

See [architecture.md §7](architecture.md#7-jobs).

---

## 15. Indexing notes (initial)

- `source_rows (import_id, row_number)`
- staged tables: `(run_id, natural_key)` unique; `(run_id, party_natural_key)`, `(run_id, target_account_code)`, `(run_id, legacy_account_code, posting_period)`
- `rule_exceptions (run_id, rule_id)`, `(run_id, fingerprint)`
- `issues (migration_id, status, severity)`, `(migration_id, fingerprint)` unique
- `audit_events (migration_id, migration_seq)` unique, `(migration_id, entity_type, entity_id)`, `(migration_id, occurred_at)`
- `jobs (status, run_after)` partial where status='queued'
