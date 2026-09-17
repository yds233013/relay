# 0003 — Deterministic engine (M2): design decisions and manifest comparison log

Status: **Accepted** (autonomous decisions under the project's Tier 1/Tier 2 policy, 2026-09-17).

This record covers the pure engine in `backend/src/relay/{ingestion,mapping,engine}`: what it decides, where the implementation refines the planning documents, and every mismatch found when the engine was first compared with the golden manifest.

---

## 1. Shape of the engine

| Stage | Module | Output |
|---|---|---|
| Read | `relay.ingestion.csv_reader` | Raw rows with physical-line lineage; malformed physical lines grouped into quarantined records |
| Map | `relay.mapping.transforms` | Declarative, allow-listed transform steps per column; nothing is guessed (no locale, no implicit date or amount format) |
| Normalize | `relay.engine.snapshot` | `RunSnapshot` of canonical records, overlays applied, `NORM.*`/`COA.*`/`OVERRIDE.STALE` findings |
| Entities | `relay.engine.entities` | Scored duplicate candidates (no merge at any score); clusters only from `same_entity` decisions |
| Rules | `relay.engine.rules` | Registered, versioned rules; each rule declares the datasets it needs and is skipped (reported) when one is missing |
| Reconcile | `relay.engine.reconciliation` | R1, R2, R3/R3b/R3o, R4/R4b/R4o, R5, R6 with explainers and hints; one `RECON.<id>` finding per discrepancy line |
| Readiness | `relay.engine.readiness` | Gates G1–G12 for one result plus caller-supplied governance facts |
| Pipeline | `relay.engine.pipeline` | Input fingerprint, result fingerprint, de-duplicated and ordered findings |

Purity is enforced by import-linter: `relay.engine`, `relay.ingestion`, `relay.mapping` and `relay.canonical` may not import the API, database modules, configuration, the clock, SQLAlchemy, psycopg, FastAPI or httpx.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| E-01 | **Input fingerprint** = file hashes, mapping set, conversion plan, overlay identity (overrides, repairs, entity decisions, mapping changes, dispositions), policy, and engine/rule/reconciliation versions. **Gate waivers and sign-offs are excluded.** | They are bound *to* a fingerprint, so including them would make a sign-off invalidate itself. Matches architecture §4.1, which does not list them. |
| E-02 | A **finding's identity** is `(rule_id, sorted subjects, discriminator)`; amounts and severities are not part of it. | Amount changes must update an issue, not create a new one. |
| E-03 | Reconciliation findings are `RECON.<recon id>` with subject `recon:<id>:<grain>`. R1–R5 lines are **critical**; R6 lines are **high**. | A ledger/subledger/cash break blocks go-live; R6 always co-occurs with the critical quarantine finding that explains it. |
| E-04 | **Hints never explain.** `single_account_contribution` (R3/R4) and `unmapped_source_account` (R2) attach evidence items but leave `explained` unchanged, so no line passes because of a hint. | validation-and-reconciliation.md B.4. |
| E-05 | **R5 matching**: reference-bearing ledger movements are matched first; candidates must have the same amount and a posted date in `[entry − 3, entry + 10]` days; ties break on reference match, then date distance, then natural key. Unmatched ledger movements that clear after cutover within the plan's clearing window are timing items; unmatched bank lines are `bank_only_activity` and emit `BANK.UNRECORDED_ACTIVITY`. | Timing explanations require a matched record (B.4). |
| E-06 | **R6** compares source rows (including quarantined records, reconstructed provisionally by joining their physical lines and applying the approved column mapping) with staged lines by **posting period as exported**. Records that cannot be reconstructed are counted and noted on the result. Approved posting-period overrides do not create R6 differences. | R6 is a completeness check of what was read, not of how it was later corrected. The reconstruction is never used as staged data. |
| E-07 | `GL.DUPLICATE_ENTRY` applies to **manual** entries only. | Module postings mirror subledger documents; duplicates there are detected by `AP.DUPLICATE_BILL`/`PAY.DUPLICATE_PAYMENT`, which have party and reference context. Applying the ledger-level rule to module postings would flag legitimate equal receipts on the same day (the TN-05 pattern) with no way to tell them apart. |
| E-08 | `PAY.DUPLICATE_PAYMENT` evaluates **both** directions. Two payments in the same party cluster with the same functional amount are duplicates when they apply to the same document, or to documents flagged by `AP.DUPLICATE_BILL` as the same obligation. | The documented rule names disbursements; a customer paying one invoice twice is the same defect on the other side. Equal payments applied to different, non-duplicate documents stay silent (TN-05). |
| E-09 | `MAP.SUBTYPE_COMPATIBLE` treats cash, receivables, payables, contra-assets and accumulated depreciation as control subtypes. **Suspense is not a control subtype.** | See mismatch M-02 below. |
| E-10 | **Unresolved exposure** sums `amount_at_risk` over open findings; findings connected through a shared subject record count once, at their maximum. | governance.md §1.3 ("a record appearing in multiple issues contributes its maximum once"), made transitive so the result does not depend on iteration order. |
| E-11 | **Gate waivers** apply only to waivable gates (G6–G9) and only to the run whose input fingerprint they name. Carrying a waiver across fingerprints by scope (governance §4.3) is deferred to M7. | Conservative: a waiver never outlives the evidence it was granted on. |
| E-12 | The engine computes each finding's status **within one run** (`open` or `dispositioned`). The cross-run lifecycle (created, verified resolved, reopened) needs persistence and is M3. | Keeps the engine pure. |
| E-13 | The CSV reader lets a quoted field span at most **20** physical lines. A quote still open after that quarantines only its first line. | Without a bound, one stray quote swallowed the rest of the file into a single quarantined record, with quadratic re-parsing. Found while refactoring; covered by a test. |
| E-14 | Aging items are staged in functional currency; the document currency is kept as an attribute. | LedgerPro agings report open balances in USD only. |
| E-15 | Amount formats and their compiled patterns are cached per format. | Measured: re-parsing the format for every cell was a visible share of normalization time. Behaviour is unchanged. |

## 3. Engine vs. golden manifest: mismatch log

The manifest was authored before the engine existed. The first full comparison ran after all general rules and reconciliations were implemented. Each mismatch was investigated before anything changed.

### M-01 — DS-09: extra orphan documents for the closed customer → **generator bug**

| | |
|---|---|
| Observed | The engine reported `AR.INVOICE_PARTY_EXISTS` for 4 invoices and `AR.PAYMENT_PARTY_EXISTS` for 4 receipts of `C-0412`. The manifest expects exactly `INV-10301` and `PMT-31877`, and states that the issue set is exact. |
| Evidence | The M1 generator gave Cedar & Salt Bistro a December carried-forward invoice (`INV-9938`) and two January invoices (2,215.60 and 1,948.25) with their receipts. The engine's findings for those records were correct for the data. |
| Specification | demo-scenario.md DS-09 is titled "Orphan invoice and payment", plants exactly `INV-10301` and `PMT-31877`, and lists exactly those two issues. The manifest agrees. Only the generator disagreed. |
| Classification | Generator bug: the generator created orphan records that the specification does not plant. |
| Change | The generator now gives C-0412 only the DS-09 invoice and its receipt. Fixtures were regenerated; all 115 manifest fact checks still pass. **The golden manifest did not change.** |

### M-02 — `MAP.SUBTYPE_COMPATIBLE` fired on the documented DS-12 resolution → **engine bug**

| | |
|---|---|
| Observed | During the resolution-sequence test, mapping legacy `6999` to target `1999 Suspense` (the documented DS-12 resolution) raised a high `MAP.SUBTYPE_COMPATIBLE`, which would block G5 in the documented final state. Run #1 was unaffected. |
| Evidence | The first implementation included `suspense` in the control-subtype set. LedgerPro has no suspense detail type, so the legacy account is staged as `other_current_asset`. |
| Specification | The rule is documented as "control-account subtypes mixed (contra_asset → accounts_receivable, cash → non-cash)". It does not name suspense. demo-scenario.md DS-12 prescribes 6999 → 1999 and §6.2 requires G1–G11 to pass afterwards. |
| Classification | Engine bug: the rule was broader than documented, and the documented resolution contradicts that breadth. |
| Change | Suspense removed from the control-subtype set (E-09). Unit tests cover both directions: inventory → receivables fires; inventory → suspense does not. **The golden manifest did not change.** |

### Not a mismatch, recorded for transparency

- **DS-06 candidate scores.** demo-scenario.md gives illustrative scores (≈0.93, ≈0.71, ≈0.68). The engine scores 1.0000, 0.6013 and 0.6013. The manifest asserts only strength (`strong` / `below_strong`), which matches. The two `below_strong` pairs are **0.0013 above the 0.60 candidate threshold**: a small weight change could drop them below the threshold and change the expected issue set. Treat entity weights as versioned behaviour.
- **Green Valley shared tax id.** Before the engine first ran, the generator was changed so that `C-0107` and `C-0198` share a tax id. The generator's own consistency checks already declared them the same legal entity, and DS-06 describes one billing entity plus a store. This is a data-design correction made before any engine output existed; no manifest value depends on it.

## 4. Verification

- Run #1: the engine output equals the manifest's issues (rule, subjects, severity, amount at risk), reconciliation discrepancy set, R5 components, totals, candidates and trap expectations (`tests/scenario/test_engine_brightwater.py`). Mutation tests show the comparison fails when an issue is dropped, added, or changed in severity or amount, or when a reconciliation is removed.
- Resolution sequence: merging DS-01 reveals exactly the manifest's DS-02 issues. Re-exported files plus the documented overlays and dispositions reach G1–G11 passing. G12 passes only with a sign-off bound to the same fingerprint.
- Rules on an unrelated synthetic company: clean books give zero findings. Every registered rule has a positive case, except `AP.DOCUMENT_TOTAL_CONSISTENT`, which the bills export cannot express (no subtotal or tax columns); a test enforces this list. Near-miss cases cover the look-alike patterns.
