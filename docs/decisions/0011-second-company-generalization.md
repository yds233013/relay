# 0011: A second company — the generalization test

Status: **Accepted** (autonomous Tier 1 and Tier 2 decisions, 2026-09-17).

Every result Relay has produced so far comes from one fictional company. Brightwater's golden
manifest proves the engine agrees with a specification on Brightwater; it cannot prove the engine
did not learn Brightwater. So a second company was built — **Kestrel Instruments Ltd**, a precision
instrument workshop — and the same runtime engine, unchanged, was pointed at it.

Kestrel is not Brightwater renamed. Nothing is shared:

| | Brightwater Provisions, Inc. | Kestrel Instruments Ltd |
|---|---|---|
| Legacy system | LedgerPro | Tallyworks 9 |
| Delimiter / encoding | comma, cp1252 | **semicolon, UTF-8 with BOM** |
| Dates | `MM/DD/YYYY` | **`DD.MM.YYYY`** |
| Amounts | `1,234.56`, negatives in parentheses | **`1.234,56`, leading minus** |
| GL amount columns | separate debit and credit | **one signed amount** |
| Trial balance | debit and credit columns | **signed balance per period** |
| Receipts and payments | two files | **one file with a `Type` column** |
| Functional currency | USD (foreign: EUR, CAD) | **EUR (foreign: USD)** |
| Fiscal year starts | January | **July** |
| Conversion window | 2025 history, 2026-06-30 cutover | 2026-01-01 … **2026-06-30** cutover |
| Chart of accounts | 1000/1100/… four digits | 1010/1200/… with `11-1000` targets |
| Parties | `C-0xxx`, `V-1xxx` | `K-000x`, `L-000x` |
| Row order | mostly chronological | **account then date; documents descending by number** |
| Defects | 13 | **6, a different combination** |
| Benign look-alikes | duplicate-looking schedules, FX pairs | monthly rent, an accrual reversal, same-day receipts |

Truth is kept separate exactly as Brightwater's is: `evaluation/kestrel/expected.toml` is hand
authored from the defect definitions and the reconciliation specification, runtime code never reads
it, and `relay_scenarios.kestrel` (which knows what it plants) cannot import it.

## What the second company found

Kestrel was written and its expectations authored **before** the engine ran against it. The first
run disagreed with the manifest in six places. Each was classified before anything was changed.

| # | Disagreement | Classification | Resolution |
|---|---|---|---|
| M-K01 | R3 reported an extra `unassigned` line of −6,500.00 | **Manifest bug** | KS-03 maps customer deposits into the receivables control account, so that balance joins the AR control side with no customer to own it. A consequence of the defect the manifest had missed; the engine is right. Manifest corrected, annotated. |
| M-K02 | `MAP.SUBTYPE_COMPATIBLE` also fired on the same account | **Manifest bug** | The catalog says the type and subtype rules fire independently. The draft named only the type conflict. Manifest corrected, annotated. |
| M-K03 | `BANK.UNMATCHED_LEDGER_MOVEMENT` did not exist | **Engine bug** — see M-K04 | |
| M-K04 | R5 raised `OverExplainedLineError` | **Engine bug** | The cash difference had bank-only activity on one side and a keyed-short ledger payment on the other. Listing only the bank side explained 18,775.00 of an 18,762.50 difference — FC-11 refuses that, correctly. The ledger-only side was never modelled. Fixed generally: `ledger_only_movement` items with a `BANK.UNMATCHED_LEDGER_MOVEMENT` finding (high, migration_defect), and G8 now blocks on both classifications. |
| M-K05 | R6 tied while a row was quarantined | **Engine bug** | The quarantined row has one field too many, so it cannot be reconstructed and names no period; it therefore belonged to no line and vanished from the control. It is now reported on a `period = "unreadable"` line: an activity control must not tie while a source row is unaccounted for. |
| M-K06 | `MAP.TYPE_COMPATIBLE` severity | **Manifest bug** | The draft guessed `critical`; the rule catalog says `high`. Manifest corrected against the catalog, annotated. |

Two more were my own setup errors, found while getting the *clean* books to stay silent, and they
are worth recording because in each case the engine was right and the scenario was wrong: optional
columns that Kestrel's exports do not have must be declared `"required": false` in the mapping set,
and a settlement in a foreign currency must be converted at the **payment-date** rate, not the
invoice's, with the difference booked to exchange gains and losses.

## Decisions

| # | Decision | Why |
|---|---|---|
| K-01 | **Three engine changes came out of this, all general.** `ledger_only_movement` (M-K04), the R6 unreadable-row line (M-K05), and `parse_period` accepting `MM.YYYY` and `YYYY/MM` (Kestrel writes periods `01.2026`). None of them names a company, a file, an account or an amount. | The test is worthless if passing it requires knowing about Kestrel. Adding a *format* to a declarative transform is configuration the mapping set chooses, not scenario knowledge. |
| K-02 | **`test_payment_that_never_clears` was rewritten, not deleted.** It asserted that an unclearable payment leaves an unexplained difference and a `RECON.R5` finding. It now asserts the payment is named as a `ledger_only_movement`, raises `BANK.UNMATCHED_LEDGER_MOVEMENT`, and still fails G8. | The old assertion encoded the bug: §B.4 says a reconciling item must be backed by matched records *and* that error indicators must keep the gate failing. Identifying a difference is not excusing it. The doc now says so explicitly, and the gate behaviour is unchanged: the run still cannot go live. |
| K-03 | **Kestrel's identifiers joined the anti-cheating scan.** `kestrel`, `KS-0x`, `K-000x`, `L-000x`, `JNL-00xxx`, `S-2026-00xx`, `NB-8842`, `Tallyworks`, `Nordbank` and its defect amounts are now banned from `relay.*`, the migrations and the web app, alongside Brightwater's. | A second scenario is a second opportunity to overfit. |
| K-04 | **Kestrel is an evaluation scenario, not a second demo.** It is generated, verified and committed as fixtures; it is not seeded into the database, has no UI, and no fast-forward. | Its purpose is to answer one question — does the engine generalize — and everything beyond that is cost without evidence. The seeding path is already exercised by Brightwater and the two portfolio migrations. |
| K-05 | **`make check` runs it.** `demo-kestrel-check` (fixtures match a fresh generation) and `demo-kestrel-verify` (31 expectations) sit beside the Brightwater equivalents, and `tests/scenario/test_kestrel.py` runs the same comparison in the unit suite. | Generalization is a property that can regress. |

## Result

31 of 31 expectations met, on the unchanged runtime engine:

- the clean books produce **no** finding, no reconciliation discrepancy and no errored stage;
- all six planted defects are caught, each by a general rule or control;
- every finding the engine reports is one the manifest expects — no extras;
- the three benign look-alikes stay silent;
- Brightwater's golden manifest still passes 115 of 115 after the three engine changes.

The honest limitation: Kestrel exercises ingestion, mapping, normalization, rules, reconciliations
and readiness. It does not exercise persistence, governance, the web app or AI — those are covered
by their own tests against Brightwater, and a second company would test the same code paths with
different rows.
