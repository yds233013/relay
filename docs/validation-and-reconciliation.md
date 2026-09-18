# Relay — Validation Rules, Reconciliation & Entity Resolution

Status: **Implemented in M2** (`backend/src/relay/engine/`). Implementation decisions and refinements: [decisions/0003-deterministic-engine.md](decisions/0003-deterministic-engine.md).

Related: [architecture.md](architecture.md) · [data-model.md](data-model.md) · [governance.md](governance.md) · [demo-scenario.md](demo-scenario.md)

---

## Part A — Validation rules engine

### A.1 Rule contract

```python
class Severity(StrEnum): CRITICAL, HIGH, MEDIUM, LOW
class Nature(StrEnum): MIGRATION_DEFECT, SOURCE_ANOMALY

@dataclass(frozen=True)
class RuleSpec:
    id: str                          # "GL.JE_BALANCED"
    version: int                     # bump on any behavior change
    title: str
    description: str                 # shown in UI and to the AI via get_rule_definition
    category: IssueCategory
    default_severity: Severity
    nature: Nature
    requires: frozenset[DatasetType] # missing → rule_run.status = not_applicable
    params_model: type[BaseModel]    # typed, defaults here, overridable via policy
    gates: frozenset[GateId]         # which readiness gates its open issues affect

class Rule(Protocol):
    spec: RuleSpec
    def evaluate(self, ctx: RuleContext, params: BaseModel) -> Iterable[ExceptionDraft]: ...

@dataclass(frozen=True)
class ExceptionDraft:
    subject_refs: tuple[RecordRef, ...]   # ≥ 1; natural keys drive the fingerprint
    discriminator: str = ""               # e.g. which field failed, for multiple exceptions per subject
    message: str                          # from a template; no free text from data without escaping
    expected: JsonValue | None = None
    observed: JsonValue | None = None
    amount_at_risk: Decimal | None = None # functional currency, ≥ 0
    severity_override: Severity | None = None  # only rule-internal escalation (e.g. by amount)
    details: BaseModel | None = None
```

- Rules are registered with `@rule(spec)` in `validation/rules/<area>.py`; the registry is imported explicitly (no filesystem discovery magic).
- `RuleContext` exposes read-only typed accessors over the `RunSnapshot`: `journal_entries()`, `lines_by_entry()`, `accounts(side)`, `parties(type)`, `clusters(type)`, `documents(type)`, `payments()`, `applications()`, `fx_rate(date, from, to)`, `conversion_plan`, `policy`. No DB, no clock, no randomness.
- Rules must be **pure and deterministic**: same snapshot and params ⇒ identical exceptions in identical order (engine sorts by fingerprint anyway).
- A rule that raises is recorded as `rule_run.status=errored` with the error, and the stage is listed on the engine result; the run still completes, but **gate G4** fails with that stage as evidence — errors never silently pass (FC-10).
- **Effective severity** = policy override (if any, via approved `policy_change`) else `severity_override` else `default_severity`.
- **Fingerprint** = `sha256(rule_id ‖ sorted(subject natural keys) ‖ discriminator)`. Amounts and run ids are excluded so that an exception whose amount changes remains the same issue.
- **Rule versioning**: bumping `version` changes the rule set hash → changes the fingerprint → existing runs become stale. Issue fingerprints do not include the version, so issues survive rule improvements.

### A.2 Severity semantics

| Severity | Meaning | Readiness effect |
|---|---|---|
| critical | Would load data that breaks double-entry integrity, references that cannot be resolved, or balances that are wrong | Blocks (G5) until a run no longer produces it: a disposition records a decision about a finding that stands, and never clears a critical (it is also not dispositionable as `accepted_risk`) |
| high | Material misstatement or incompleteness risk | Blocks (G5) unless dispositioned by controller |
| medium | Likely data-quality problem needing a decision | Counts toward exposure (G9) |
| low | Informational / hygiene | Visible only |

### A.3 MVP rule catalog

**Normalization (emitted by the normalize stage using the same exception contract)**

| ID | What | Sev | Nature | Amount at risk |
|---|---|---|---|---|
| `NORM.MALFORMED_ROW` | Quarantined physical row(s) in an import | critical | migration_defect | n/a (unknown) |
| `NORM.REQUIRED_FIELD_MISSING` | Required canonical field empty | high | migration_defect | record amount if known |
| `NORM.UNREADABLE_FILE` | The file cannot be read at all (not text, NUL bytes, no header) | critical | migration_defect | — |
| `NORM.PARSE_FAILURE` | Value fails declared transform (date/decimal/currency). **Critical** when a whole journal entry is discarded because its lines disagree on date, period or type: the ledger loses that activity | high (critical for a discarded entry) | migration_defect | entry debit total when an entry is lost |
| `NORM.AGING_SIGN_CONFLICT` | An aging row's sign contradicts its kind — a credit typed as a document, or a positive unapplied payment. The reconciliation takes the sign from the kind, so the row would otherwise be flipped silently | high | source_anomaly | — |
| `NORM.DUPLICATE_NATURAL_KEY` | Same natural key twice in an import | high | migration_defect | amount of duplicate |
| `OVERRIDE.STALE` | Override's `expected_current_value` no longer matches | high | migration_defect | — |

**Chart of accounts & mapping**

| ID | What | Sev | Nature |
|---|---|---|---|
| `COA.CODE_UNIQUE` | Duplicate account codes | critical | migration_defect |
| `COA.TYPE_VALID` | Unknown account type/subtype | high | migration_defect |
| `MAP.ACCOUNT_UNMAPPED` | Legacy account with activity or non-zero balance has no target | critical | migration_defect |
| `MAP.TARGET_ACCOUNT_EXISTS` | Mapping points to a code not in target CoA | critical | migration_defect |
| `MAP.TYPE_COMPATIBLE` | Legacy type ≠ target type (asset→expense) | high | migration_defect |
| `MAP.SUBTYPE_COMPATIBLE` | Control-account subtypes mixed (contra_asset→accounts_receivable, cash→non-cash). Control subtypes: cash, accounts receivable, accounts payable, contra-asset, accumulated depreciation. Suspense is not one ([0003](decisions/0003-deterministic-engine.md) E-09) | high | migration_defect |

**General ledger**

| ID | What | Sev | Amount at risk |
|---|---|---|---|
| `GL.JE_BALANCED` | Σ functional line amounts ≠ 0 per entry | critical | \|Σ\| |
| `GL.LINE_NONZERO` | Line amount is zero | low | — |
| `GL.ACCOUNT_EXISTS` | Line account not in legacy CoA | critical | \|Σ lines on missing account\| |
| `GL.DATE_IN_WINDOW` | Entry date outside `[history_start, cutover]` | critical | \|entry debit total\| |
| `GL.PERIOD_MATCHES_DATE` | Posting period ≠ fiscal period of entry date | medium (high if crosses fiscal year) | \|entry debit total\| |
| `GL.DUPLICATE_ENTRY` | Two **manual** entries with same date, same line signature (account, amount multiset), not a reversal pair. Module postings are covered by the document-level duplicate rules ([0003](decisions/0003-deterministic-engine.md) E-07) | high | \|debit total of duplicate\| |
| `GL.CONTROL_ACCOUNT_DIRECT_POST` | Manual (`source_module=manual`) lines to AR/AP control accounts without a party | medium | \|line\| |

**Control reports**

| ID | What | Sev | Amount at risk |
|---|---|---|---|
| `TB.PERIOD_COVERAGE` | A month end of `[history_start, cutover]` has no trial balance rows, so R1 and R2 never compare that period | high | — |

**AR / AP / payments** (AR shown; AP rules mirror with `bill`/vendor)

| ID | What | Sev | Nature |
|---|---|---|---|
| `AR.INVOICE_PARTY_EXISTS` | Invoice references unknown customer | critical | migration_defect |
| `AR.PAYMENT_PARTY_EXISTS` | Receipt references unknown customer | critical | migration_defect |
| `AR.APPLICATION_DOCUMENT_EXISTS` | Application references unknown invoice | critical | migration_defect |
| `AR.DOCUMENT_TOTAL_CONSISTENT` | `subtotal + tax ≠ total` | high | source_anomaly |
| `AR.OVERAPPLIED_DOCUMENT` | Σ applications > document total | high | source_anomaly |
| `AR.OPEN_AMOUNT_CONSISTENT` | `total − Σ applications (≤ cutover) ≠ open_amount_at_cutover` | high | migration_defect |
| `AP.DUPLICATE_BILL` | Same party cluster + normalized vendor reference, or same cluster + amount + date within N days | high | source_anomaly |
| `PAY.DUPLICATE_PAYMENT` | Two payments (either direction) in the same party cluster with the same functional amount that apply to the same document, or to documents flagged as duplicates by `AP.DUPLICATE_BILL` ([0003](decisions/0003-deterministic-engine.md) E-08) | high | source_anomaly |
| `PAY.UNAPPLIED_CASH` | Receipt with unapplied amount at cutover | low | source_anomaly |
| `AR.INVOICE_DATE_IN_WINDOW` | Invoice dated after the cutover: it is not part of the balances being migrated, and takes no part in the open items at cutover. Dates before the window are normal for carried-forward documents (SC-04) | high | migration_defect |
| `AR.PAYMENT_DATE_IN_WINDOW` | Receipt dated after the cutover | high | migration_defect |

`AP.DUPLICATE_BILL` and `PAY.DUPLICATE_PAYMENT` operate on **party clusters**, so an approved entity merge can reveal new duplicates on rerun — intentionally.

**Currency**

| ID | What | Sev |
|---|---|---|
| `CUR.PARTY_CURRENCY_MISMATCH` | Document currency ≠ party default currency, and the party has ≥ 3 documents in its default currency | high |
| `CUR.FUNCTIONAL_AMOUNT_CONSISTENT` | `\|amount × rate − functional_amount\| > rounding tolerance` using `fx_rates` on document date | high |
| `CUR.MISSING_FX_RATE` | Foreign-currency document with no rate within N days | high |

**Parties**

| ID | What | Sev |
|---|---|---|
| `PARTY.UNRESOLVED_DUPLICATE_CANDIDATE` | Entity candidate with score ≥ threshold and no decision | high if either party has open balance, else medium |
| `PARTY.INACTIVE_WITH_OPEN_BALANCE` | Inactive party with open items at cutover | medium |

**Bank**

| ID | What | Sev |
|---|---|---|
| `BANK.UNRECORDED_ACTIVITY` | Bank transaction ≤ cutover with no GL counterpart (emitted by the `bank_only_activity` explainer) | medium (source_anomaly) |

**Data safety**

| ID | What | Sev |
|---|---|---|
| `DATA.INSTRUCTION_LIKE_TEXT` | Free-text field matches instruction-like heuristics ("ignore previous", "system note to AI", "approve all") | low (category `ai_safety`) |

Each rule ships with a positive fixture (must fire), a negative fixture (must not fire), and at least one near-miss fixture.

---

## Part B — Reconciliation engine

### B.1 Model

A reconciliation compares two **measures** at a **grain** and explains differences.

```python
@dataclass(frozen=True)
class ReconciliationSpec:
    id: str                        # "R3.AR_SUBLEDGER_VS_GL"
    version: int
    title: str
    purpose: Literal["completeness", "fidelity"]
    left: MeasureSpec              # label, provider
    right: MeasureSpec
    grain: tuple[str, ...]         # ("party",) or ("account", "period")
    as_of: AsOf                    # cutover | each_period_end | opening
    tolerance: ToleranceRef        # resolved from policy
    explainers: tuple[ExplainerId, ...]
    gates: frozenset[GateId]
    requires: frozenset[DatasetType]

class MeasureProvider(Protocol):
    def measure(self, ctx: ReconContext, grain: tuple[str, ...], as_of: date) -> dict[GrainKey, Aggregate]: ...

@dataclass(frozen=True)
class Aggregate:
    amount: Decimal                      # functional, signed
    count: int
    contributors: tuple[Contributor, ...] # (natural_key, amount) — the drill-down source

class Explainer(Protocol):
    id: str
    def explain(self, line: ReconLineDraft, ctx: ReconContext) -> list[ReconcilingItemDraft]: ...
```

**Algorithm**

1. Compute `L = left.measure(...)`, `R = right.measure(...)` for each `as_of`.
2. For each key in `L ∪ R`: `difference = L.amount − R.amount` (missing side = 0, status `left_only`/`right_only`).
3. Run explainers in declared order on lines with `difference ≠ 0`. Each explainer may only explain amounts backed by specific records; `explained_amount` is the sum; explainers cannot explain more than the remaining difference.
4. `unexplained = difference − explained`. Line status: `tied` (difference = 0), `explained` (unexplained = 0), `within_tolerance` (\|unexplained\| ≤ tolerance), else `discrepancy`.
5. Result status: `tied`, `tied_with_explained_items`, or `discrepancy`.
6. Each `discrepancy` line emits an exception with rule id `RECON.<recon_id>`, subject = grain key refs, `amount_at_risk = |unexplained|`. These become issues through the normal path.

All arithmetic is exact `Decimal`. Tolerance compares exact unexplained difference against a policy amount; nothing is rounded before comparison.

### B.2 Drill-down

`GET /reconciliation-lines/{id}/drilldown` returns:

```json
{
  "grain_key": {"party": "party:customer:C-0233"},
  "left":  {"label": "GL 1200 (target)", "amount": "…", "contributors": [RecordRef + amount …]},
  "right": {"label": "Open AR items",   "amount": "…", "contributors": [...]},
  "matched_by_document": [{"document": "doc:invoice:…", "left": "…", "right": "…", "difference": "0.00"}],
  "left_only":  [{"ref": "jl:JE-AR-10877:1", "amount": "9340.00", "document": "doc:invoice:INV-10877"}],
  "right_only": [],
  "amount_mismatches": [],
  "reconciling_items": [...],
  "related_issues": [...],
  "limits": "Right side is detail; left side is ledger lines. Matched on document_natural_key where present."
}
```

- Where both sides carry a common natural key (document, payment), contributors are **matched** and the set difference is shown.
- Where one side is an aggregate report (TB, bank ending balance), drill-down narrows to the grain key and shows the detail side's contributors, sorted by likelihood heuristics (lines in failing entries first, then largest amounts), and states that record-level matching is not possible.
- Each contributor opens the record inspector with source file and line.

### B.3 MVP reconciliations

| ID | Purpose | Left | Right | Grain | As of | Default tolerance | Explainers |
|---|---|---|---|---|---|---|---|
| **R1.TB_VS_GL_DETAIL** | completeness | Control TB closing balance (legacy account) | Opening TB + Σ GL detail lines (legacy account) | account × period | each period end in window | 0.00 | — |
| **R2.LEGACY_VS_STAGED** | fidelity | Control TB closing balance rolled up via account mapping (+ `unmapped` bucket) | Staged balances by target account | target account × period | each period end | 0.00 | `unmapped_source_account` |
| **R3.AR_SUBLEDGER** | fidelity + completeness | Staged GL balance of target accounts with subtype `accounts_receivable` | Staged open AR items (open invoices − unapplied credits) | party (+ `unassigned`) and total | cutover | 0.00 | `single_account_contribution` |
| **R3b.AR_AGING_VS_ITEMS** | completeness | Control AR aging | Staged open AR items | document (+ total) | cutover | 0.00 | — |
| **R4.AP_SUBLEDGER** / **R4b.AP_AGING_VS_ITEMS** | as R3 for AP | | | | | | |

**Sign convention (all reconciliations).** Both measures are in the canonical signed convention: debit positive, credit negative. `difference = left − right`. For AP (R4, R4b), the GL balance of `accounts_payable` accounts and the open AP items are both credit-negative. A GL AP balance missing a 1,184.62 credit, against open items that net to zero, therefore gives a difference of `+1184.62`.

**R3/R4 party grain with opening balances (SC-04).** For party *p*: `left(p)` = opening aging balance of *p* + H1 GL activity on mapped AR (R3) or AP (R4) accounts carrying party *p*, dated on or before cutover. `left(unassigned)` = opening TB balance of the mapped accounts − Σ opening aging + H1 activity with no party. The left total equals the GL balance at cutover. `right(p)` = open items at cutover (open documents − unapplied credits). Companion completeness checks **R3o/R4o** compare the opening aging total with the opening TB balance of legacy AR/AP-subtype accounts.

**R2 inherits R1 differences.** R2's right side is built from staged GL detail bucketed by derived period, the same basis as R1's right side, and both left sides come from the control TB. So every R1 discrepancy on a mapped legacy account also appears in R2 on its target account, for the same periods and with the same sign. R2 additionally detects mapping-level problems such as the `unmapped` bucket. This follows from the definitions; nothing is special-cased (SC-02).
| **R5.CASH_VS_BANK** | completeness | Staged GL cash account balance | Bank statement ending balance at cutover | bank account | cutover | 0.00 unexplained | `outstanding_checks`, `deposits_in_transit`, `bank_only_activity` |
| **R6.ACTIVITY_TOTALS** | completeness | Source GL rows, counted from the file through the approved column mapping: every data row, plus quarantined records reconstructed provisionally, plus rows an approved repair restored. A row whose amount will not parse still counts in its period; a row that names no period is reported in the result's note | Staged journal lines | posting period as exported: count, Σ debits, Σ credits | each period | exact counts, 0.00 | — |

**Period basis.** R1 compares the control TB (which the legacy system reports by *posting period*) against detail bucketed by **derived period from entry date**, because the target ERP derives period from date (decision D-09). Posting-period/date disagreements therefore surface as R1 discrepancies in two adjacent periods that net to zero cumulatively, plus a `GL.PERIOD_MATCHES_DATE` exception. This is deliberate: it shows exactly how comparatives will differ after migration.

### B.4 Explainers (deterministic)

| Explainer | Explains | Evidence requirement |
|---|---|---|
| `outstanding_checks` | GL disbursements dated ≤ cutover that are not in bank ≤ cutover but clear in the post-cutover window | Matched bank txn after cutover (amount + reference/check no.) |
| `deposits_in_transit` | GL receipts ≤ cutover posted by bank within window after cutover | Matched bank txn |
| `bank_only_activity` | Bank txns ≤ cutover with no GL match (fees, interest) | Explained for *reconciliation* but **also emits** `BANK.UNRECORDED_ACTIVITY` (medium, source_anomaly) needing disposition |
| `ledger_only_movement` | GL cash movements ≤ cutover with no bank match, before or after the cutover (so not a timing item) | Explained for *reconciliation* but **also emits** `BANK.UNMATCHED_LEDGER_MOVEMENT` (high, migration_defect), which blocks G8 |
| `single_account_contribution` | Difference exactly equals the balance contributed by one mapped legacy account | Hint only: explained_amount stays 0; attaches a `reconciling_item` with classification `single_account_contribution` so the evidence is visible. It **does not** make a line pass. |
| `unmapped_source_account` | R2 unmapped bucket | Lists legacy accounts; does not make a line pass |

**What "explained" means here.** A reconciling item may reduce `unexplained` only when it names the
records it is about, and the identified items must together account for the difference and no more —
`ReconLine` refuses to be built otherwise (FC-11). Identifying a difference is not the same as
excusing it: an item that indicates an error (`bank_only_activity`, `ledger_only_movement`) must also
emit a finding that keeps the gate failing until someone resolves or dispositions it. An item that
merely *suggests* where to look (`single_account_contribution`, `unmapped_source_account`) is a hint:
it never reduces `unexplained` and never makes a line pass.

Both error-indicating classifications are needed for the arithmetic to hold: bank activity the ledger
never recorded and ledger movements the bank never saw push the difference in opposite directions,
and listing only one side can exceed the difference it is meant to explain.

---

## Part C — Entity resolution

### C.1 Candidate generation (deterministic)

1. **Normalize**: casefold, Unicode NFKC, strip punctuation, collapse whitespace, canonicalize legal suffixes (`l.l.c.`, `llc`, `inc.`, `incorporated`, `co`, `co-op`, `cooperative` → tokens), strip location markers into a separate `location_token` (`#2`, `store 2`).
2. **Addresses**: normalize directionals (`N.W.` → `nw`), street types (`Avenue` → `ave`), unit designators (`Suite`/`Ste` → `ste`).
3. **Blocking** (pairs only within a block): same first 4 chars of normalized name; same `tax_id_last4`; same postal code + street number; same email domain (non-free-mail).
4. **Features**: Jaro-Winkler on normalized name, token-set ratio, address similarity, tax id last4 equality, email domain equality, **location_token conflict** (negative), shared `party_reference` values on documents (e.g. same vendor invoice number under both parties), state/country mismatch (negative).
5. **Score**: a documented, hand-weighted linear model clipped to [0, 1] (weights in code, versioned). No ML training in MVP.
6. Candidates with score ≥ `policy.entity_candidate_threshold` (default 0.60) are persisted. Score ≥ 0.85 is labelled "strong".

### C.2 Decisions

- `same_entity` (members, survivor, survivorship per field) or `distinct` (pair or set).
- Created only by approved `entity_decision` change requests.
- Keyed on source natural keys → stable across runs and import versions.
- Non-destructive: staged parties keep source records; `cluster_id` groups them. Documents keep original party keys and gain a `cluster_id` for rule evaluation and subledger grouping.
- Reverting a decision is another change request.
- No auto-merge at any score.

AI's role: explain a candidate using its features and linked documents; never generate candidates and never decide.
