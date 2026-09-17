# Relay — independent review passes

After M9, the system was reviewed again in six passes, each from a different point of view. This
document records what was looked at, what was found, and what was done about it. Findings that were
fixed name the test that now covers them; findings that were not fixed say why.

---

## Pass 1 — accounting correctness

Audited the engine against the specifications as a controller would: double-entry invariants, AR and
AP open items, cash, control reports, opening balances and carried-forward documents, FX, rounding,
dates and periods, mappings, and cutover semantics. Seven genuine defects, all fixed with tests. The
golden manifest did not change, and 115 of 115 manifest checks still pass — every fix was either
unreachable in the demo data or produced identical results on it.

### D1 — R6 could not detect a lost source row

`r6_activity_totals` seeded its "source rows" side from the staged side (`source = dict(staged)`)
and then added quarantined rows. R6 is the only row-count completeness control, and it was
tautological except for quarantine: a row dropped by a parse failure, a missing required field, or
an entry whose lines disagree on their header vanished from **both** sides, and the control tied.

The source side is now counted from the files themselves through the approved column mapping —
every data row, plus quarantined records reconstructed provisionally, plus rows an approved repair
restored. A row whose amount will not parse still counts in its period (so the count difference
shows); a row that names no period is reported in the result's note. `RECONCILIATION_VERSION` 1 → 2.

### D2 — "Open items at cutover" included documents dated after the cutover

`_open_items` filtered on nothing but a non-zero open amount, so a document or an unapplied payment
dated after the cutover entered the measure that R3 and R4 compare against the cutover aging — while
the rules around it (`PAY.UNAPPLIED_CASH`, `AR.OPEN_AMOUNT_CONSISTENT`) did filter by cutover. The
measure now takes only documents and payments dated on or before the cutover.

Nothing reported the excluded record, so four new rules were added:
`AR.INVOICE_DATE_IN_WINDOW`, `AP.BILL_DATE_IN_WINDOW`, `AR.PAYMENT_DATE_IN_WINDOW` and
`AP.PAYMENT_DATE_IN_WINDOW` (high). Dates *before* the window stay normal: a carried-forward
document is exported because it is still open (SC-04).

### D3 — Three FX conversions rounded the wrong way

`(amount * fx_rate).quantize(Decimal("0.01"))` appeared in the subledger reconciliation, in payment
application staging and in the persisted drill-down. `Decimal.quantize` without a context uses
Python's default banker's rounding, and the hardcoded two places are wrong for any currency with
different minor units — while FC-02 says the only rounding is `convert()`, half away from zero, to
the target currency's minor units. All three now go through one helper, `core.money.to_functional`,
which returns a functional amount unchanged and otherwise converts through `convert()`.

### D4 — A dispositioned critical finding passed G5

`issue_statuses` marks any dispositioned fingerprint as non-open, and G5 then dropped criticals
exactly like highs — so `false_positive` or `carry_forward_adjustment` on a critical cleared the
go-live blocker. governance.md §4.2 is explicit: G5 needs "0 issues of severity critical **not
resolved**; 0 high not resolved **or dispositioned**", and G5 is not waivable. A critical is now
cleared only by a run that no longer produces it. No documented Brightwater disposition targets a
critical, so the demo's documented resolution is unchanged.

### D5 — R2 lost the opening balance when the trial balance was sparse

R1 carries each account's opening balance into every period; R2 derived the same carry from the
trial balance rows that happened to exist. With a real export that suppresses zero rows — or an
account that stops appearing — the carry silently disappeared, and §B.3's guarantee that every R1
discrepancy appears in R2 on the target account, same period, same amount, broke. Measured on the
demo data with 1010's January row removed: R1 reported −752,538.69 and R2 −2,538.69, exactly the
750,000.00 opening balance apart. R2 now carries the opening balance for every mapped account and
period, as R1 does.

### D7 — An aging row whose sign contradicted its kind was silently flipped

Aging amounts were stored as `abs(value)`, with the sign taken from the row's kind. A credit memo
printed under "Invoice" — ordinary in an aging report — became a positive receivable, so the error
was twice the amount, on both sides, with nothing raised. `NORM.AGING_SIGN_CONFLICT` (high) now
reports the disagreement.

### D8 — Losing a whole journal entry was reported as `high` with no amount

When an entry's lines disagreed on date, period or type, the entire entry was discarded with one
high finding and no amount at risk — while a single quarantined row is critical. Dropping an entry
changes the balances, so it is now critical and carries the entry's debit total. With D1 fixed, the
same rows also show as an R6 count difference.

### Also added

`TB.PERIOD_COVERAGE` (high): R1 and R2 take their period ends from the trial balance itself, so a
month missing from the control export was never reconciled at all rather than reported. The rule
checks every month end of the history window.

### Checked and found correct

Double-entry invariants (a line with both debit and credit non-zero cannot pass); R3/R4/R3o/R4o
signs and totals against every signed figure in the manifest; opening balances and carried-forward
documents counted exactly once; R5 cash reconciliation components; explainers that cannot
over-explain (the M9 invariant); tolerance arithmetic on exact decimals; business dates and periods;
the duplicate and look-alike traps; the mapping rules; and determinism of finding order and
de-duplication.

### Recorded, not changed

`unresolved_exposure` collapses findings connected through shared subjects into one maximum per
connected component, which can understate G9 relative to governance.md §1.3 (a record contributes
its maximum once, summed over issues). Changing it would move a number the golden manifest asserts,
so it is written down here rather than altered on my own judgement.

---

## Pass 2 — adversarial evaluation

Attempts to break Relay on purpose. New regressions live in
`backend/tests/integration/test_adversarial.py` (16 tests).

### Genuine defect found and fixed

**Amounts and dates written in non-ASCII digits were accepted.** `\d` in a Python regular
expression matches every Unicode decimal digit, so `１２３` (full-width), `٣٤٥` (Arabic-Indic) and
`१२३` (Devanagari) parsed as numbers, including mixed within one value: `1２3.4５` parsed as
`123.45`, and `٢٠٢٦-٠٣-٣١` parsed as 2026-03-31.

Nothing in the demo data exercises this (the fixtures are cp1252), and no value was wrong — but an
accounting import whose stated rule is "nothing is guessed: every choice is explicit" must not
silently accept digits that a person reading the same file may read differently, and mixed-script
numerals are a standard homoglyph vector. `relay.core.money` and `relay.core.dates` now accept ASCII
digits only (`[0-9]`), with tests over all three digit systems and over a single substituted digit
inside an otherwise ASCII amount.

### Attacks that Relay already withstood (now regressions)

| Attack | Result |
|---|---|
| A change request adopting another migration's mapping set | Refused: every payload id is checked against the change request's own migration |
| A disposition reaching an issue in another migration | Refused |
| Submitting, withdrawing or approving the same change request twice | Refused; the change request keeps its status |
| Requesting the same run five times | One run, because the request is idempotent on the fingerprint |
| Amounts beyond `NUMERIC(20,4)`, with too many decimals, or `NaN`/`Infinity` | Refused in Python before PostgreSQL sees them; the largest exact value round-trips |
| `CAST('1e30' AS NUMERIC(20,4))` | PostgreSQL refuses rather than rounding |
| A job whose worker died mid-run | Not claimable while the lease holds, then requeued by `requeue_stale` and claimed by another worker |
| An unknown job kind inserted directly | Refused by the CHECK constraint |
| An override for a record that does not exist, or a change request for a migration that does not exist | Refused |
| A CSV field longer than the limit | The row is quarantined (`field_too_long`), never truncated into a staged record |

Already covered before this pass, re-verified: duplicate and modified uploads (`test_persistence.py`),
stale approvals (`test_governance.py`), malicious instruction-like document text
(`DATA.INSTRUCTION_LIKE_TEXT`, the AI injection eval), malformed CSVs, duplicate jobs, and the
false-positive traps in the Brightwater scenario (`tests/scenario/test_traps_and_manifest.py`).

---

## Pass 3 — anti-cheating audit

Searched the whole product — `backend/src/relay`, `backend/migrations` and `web/src` — for scenario
identifiers (`DS-`, `TN-`), Brightwater record ids and party names, the known defect amounts, imports
of the generator or evaluation packages, reads of `evaluation/` or `fixtures/`, and branching on file
names, dataset names or company names. Also re-examined every tunable in `engine/policy.py` and the
entity-resolution weights for values that only make sense for the demo.

**Result: the runtime is clean.** Every scenario-dependent value arrives as data (`migration.json`,
the approved mapping set, the policy version); dataset types and column-header synonyms are generic
ERP vocabulary; the zero reconciliation tolerances cannot be tuned to make a demo pass, only to make
it stricter; and no score auto-merges anything — a candidate is a proposal a person decides.

Two capability limits are honest narrowness rather than cheating, and are stated here because a
reader should not mistake them for generality: the profiler recognises three date shapes
(`MM/DD/YYYY`, `YYYY-MM-DD`, `MM/YYYY`), and amount suggestions assume `,` grouping with `(…)`
negatives. Anything else produces "choose the format" rather than a guess, and the operator maps it
by hand — which is what the governed mapping workflow is for.

### What the guard tests missed, and now cover

The boundary scan read `backend/src/relay/**/*.py` only. It now scans the runtime package, the
Alembic migrations **and** `web/src`, across every product file type (`.py`, `.ts`, `.tsx`, `.json`,
`.sql`, `.toml`, `.yaml`), with a companion test asserting the scan actually reaches all three roots
so it cannot quietly become vacuous. The generated OpenAPI schema and client types are excluded by
name: they describe endpoints, never data.

Extending it immediately found two Brightwater amounts (`-1184.62`, `-29060.00`) used as formatting
examples in `web/src/lib/format.test.ts` — harmless, but exactly the kind of drift the rule exists to
stop. They are now neutral numbers.

The scan cannot catch *semantic* tuning — a threshold moved to make one reconciliation pass, a rule
quietly skipped for a shape only Brightwater has. The defence against that is the hand-authored
golden manifest and the engine-versus-manifest comparison, not a regular expression.

---

## Pass 4 — code quality

### Fixed

| Finding | What was done |
|---|---|
| **A dead 145-line `drilldown` in `engine/reconciliation.py`** duplicated the live persisted drill-down in `pipeline/read_model.py`, and nothing referenced it. Two implementations of the same R1–R4 contributor logic can only diverge | Deleted, with its `__all__` entry |
| **`GET /migrations` recomputed each migration's full input configuration**, and `load_configuration` walked datasets one at a time (three `session.get` calls each, plus a mapping-set query and its columns) | Batched: imports, stored files, source systems and approved mapping sets are each one query, and every mapping set's columns come back together. Measured on the seeded demo (2 migrations, 16 datasets each): **444 ms → 184 ms** for the portfolio read |
| **`GET /migrations/{id}` scanned every migration** and filtered in Python for a primary-key lookup | One query by id |
| **Dead code**: `pipeline.read_model.staged_by_document`, `engine.pipeline.total_exposure`, `core.currency.known_currency_codes` | Deleted |
| **`links_for` existed twice**, and the issues router re-implemented the per-row lookup a third time as an N+1 | One read-model function, resolving the linked issues in a single query |
| **`datasets_for` returned different orders** in the service and the read model, and one of the consumers is an AI that cites evidence | Both order by dataset type, as-of date, then name |
| **A failed job's traceback was lost**: an unexpected exception stored only its class name (correct, SEC-14) and logged no message | The log carries `exc_info` for non-`RelayError` failures; the stored detail is unchanged |
| **A lock-ordering regression test slept for one second** and assumed the approval had reached the lock — on a slow machine it would pass without testing anything | It now polls `pg_locks` until the approval is provably waiting, and fails if it never gets there |

### Recorded, not changed

- **"Exception" and "finding" both name the deterministic rule output** (`RuleException`,
  `exception_count`, `/exceptions`, but `counts["findings"]` and "Findings" in the UI), while
  `Finding` is separately the AI investigation output with its own table. The vocabulary should be
  one word per concept, but renaming crosses the published API surface, so it is a deliberate
  decision for a later change rather than a drive-by.
- **Change request payloads are typed per kind and then erased** to `Any` at the dispatch table and
  `dict[str, Any]` at the API, so the UI hand-casts through `Record<string, unknown>`. Making `Kind`
  generic in its payload would recover the backend half cheaply; the OpenAPI half is a larger call.
- **`mapped_records` skips a row whose transform fails.** Checked rather than assumed: a legacy
  account missing from the drafted mapping set surfaces as `MAP.ACCOUNT_UNMAPPED` (critical) and
  fails G3, so the consequence is reported by another control rather than lost.
- **A blob is written before its transaction commits**, so a rolled-back upload can orphan a file.
  Content-addressed storage makes that harmless (a re-upload reuses the key) and the spool directory
  is cleaned on failure.
- Module-scoped integration stories mutate shared state in order; that is deliberate and is now
  documented in [testing.md](testing.md#24-integration-tests-backendtestsintegration-postgres).

### Checked and found in good shape

One `session.commit()` in the entire runtime (inside `session_scope`); no writes or enqueues in any
read model or GET handler; no `cast(`, no bare `except`, and every broad `except` justified inline
(cleanup that re-raises, or FC-10's errored stages); no `any`, `@ts-ignore` or `eslint-disable`
anywhere in `web/src`; no unused dependencies in either lockfile.
