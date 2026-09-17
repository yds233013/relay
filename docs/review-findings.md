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
