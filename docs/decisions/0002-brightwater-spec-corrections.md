# 0002 — Brightwater scenario specification corrections

Status: **Accepted.** Approved by the project owner on 2026-09-17.

**Provenance.** These corrections came out of the pre-implementation consistency review for M1. The review compared the Brightwater specification ([demo-scenario.md](../demo-scenario.md)) against the documented reconciliation definitions ([validation-and-reconciliation.md](../validation-and-reconciliation.md)) and the planned data volumes. **When these corrections were made, no generator, fixture, golden manifest or reconciliation engine existed.** Expected outputs were not changed after observing any engine behavior.

No documented amount, date, account or seeded defect relationship was changed except where stated below.

---

## SC-01 — DS-11 posting identifier and its AP subledger effect

| | |
|---|---|
| **Original** | DS-11 planted `JE-2026-0297` dated 2062-03-14, posting period 2026-03, Dr 6200 1,184.62, Cr 2000 AP, for bill `B-20455` (Portland General Utilities, 2026-03-14). Expected effects: `GL.DATE_IN_WINDOW` and R1 differences only. §6.1 listed G7 as failing because of R3/R3b only. |
| **Changed** | The entry is `JE-AP-20455`, the AP module posting of bill B-20455. Bill, vendor, amount, accounts, the erroneous 2062-03-14 entry date, the 2026-03 posting period and the business-date evidence are unchanged. The expected effects now also include an **R4 discrepancy of 1,184.62 for Portland General Utilities** at cutover. §6.1 lists R4 (DS-11) under G7. |
| **Why** | (1) Module postings are numbered per source document (`JE-AR-10877` in DS-04). Only manual journals use the `JE-2026-NNNN` series, and a bill posting has to be the bill's own AP entry: a separate manual entry would credit AP twice and break AP aging against the GL in the clean books. (2) R4 compares the GL AP balance at cutover, which includes only entries dated on or before 2026-06-30, with open AP items. The 2062-dated credit is excluded from the GL side, so GL differs from open items by 1,184.62 for that vendor, with sign `+1184.62` under the documented convention. The original text omitted a consequence that follows from the reconciliation's own definition. |
| **Gate impact** | None. G7 already failed. Still 9 of 12 gates failing. |

## SC-02 — R2 differences derived from R1

| | |
|---|---|
| **Original** | §6.1 listed R2 as failing only because of DS-12 (the unmapped suspense account). DS-05, DS-08 and DS-11 listed R1 effects only. |
| **Changed** | R2 also shows, on the target accounts mapped from the affected legacy accounts: DS-05 `(450.00)` for 6410 in 2026-04–06; DS-08 `+21,730.00` for 5000 and `(21,730.00)` for 1300 in 2026-03; DS-11 `+1,184.62` for 6200 and `(1,184.62)` for 2000 in 2026-03–06. The reconciliation doc states the sign convention and why R2 inherits R1 differences. |
| **Why** | R2 compares the control TB rolled up through the account mapping with staged balances built from GL detail by derived period. Its right side has the same basis as R1's, so every R1 difference on a mapped account necessarily appears in R2. Suppressing these would require special-casing, which is prohibited. |
| **Gate impact** | None. G6 already failed. |

## SC-03 — Scenario volume and bill numbering

| | |
|---|---|
| **Original** | About 2,600 invoices, 3,900 payments, 21,000 GL lines, 310 AR aging rows and 3,100 bank lines. DS-05's malformed row was placed at physical lines ~14,322–14,323. Bill numbers carried no stated ordering semantics. |
| **Changed** | About 900 invoices, with surrounding activity scaled coherently (see the dataset table). DS-05's malformed row is described as two consecutive physical lines rather than a line number that depended on the old volume. LedgerPro bill reference numbers are documented as assigned independently of bill date. The ~1,400-bill target is kept. Performance testing uses a separate deterministic scaling mechanism. |
| **Why** | The documented invoice identifiers `INV-10301` (2026-02-20) and `INV-10877` (2026-06-18) span 576 numbers in 118 days, about 4.9 invoices per day, or roughly 900 per half-year, not 2,600. Bill `B-20931` is dated 2026-02-24 while the lower number `B-20455` is dated 2026-03-14, which cannot happen if bill numbers are a creation-time sequence. No documented ID, date or amount was changed to hit a record count. |
| **Gate impact** | None. |

---

## SC-04 — Opening AR/AP by party: opening agings and carried-forward documents

Discovered in the same pre-implementation review, before any M1 code existed. Approved 2026-09-17.

| | |
|---|---|
| **Original assumption** | R3/R4 compare the "staged GL balance" of AR/AP accounts with open items at party grain. The only opening-balance source was the control trial balance, which has no party breakdown. The invoice and bill exports covered the history window only. |
| **Problem** | GL balance at cutover = opening balance + H1 activity. At party grain the opening balance has no party, so the entire opening AR balance falls into `unassigned`. A net-30 wholesale distributor with ~$24M revenue carries roughly $2M of receivables at year end. The documented DS-03 effect ("unassigned = (38,400.00)") holds only if opening AR is zero, which is implausible. H1 receipts are also applied to invoices dated 2025 that were open at 2025-12-31; a history-only export makes those applications reference documents that don't exist, creating unintended exceptions in clean books. The same applies to AP and to SC-01's per-vendor R4 effect. |
| **Approved correction** | (1) Invoice and bill exports use an **open items + history** scope: every document dated in the history window, plus documents dated before 2026-01-01 still open at 2025-12-31 (carried-forward documents). (2) Two independent LedgerPro control reports are added: `ledgerpro_ar_aging_20251231.csv` and `ledgerpro_ap_aging_20251231.csv`. (3) R3/R4 party grain: *left(p)* = opening aging balance(p) + H1 GL activity on mapped AR/AP accounts for party p, dated on or before cutover; *left(unassigned)* = opening TB balance of the mapped AR/AP accounts − Σ opening aging + H1 activity with no party. The left total therefore still equals the GL balance at cutover. *Right(p)* = open items at cutover. (4) New opening control checks: opening AR aging total = opening TB balance of legacy AR-subtype accounts, and opening AP aging total = opening TB balance of legacy AP-subtype accounts. |
| **Expected-result impact** | None on documented effects. DS-03 unassigned `(38,400.00)` = opening 1205 balance + H1 1205 activity (unchanged by carried-forward AR); DS-04 C-0233 `+9,340.00`; R3 total `(29,060.00)`; DS-11 Portland General Utilities R4 `+1,184.62`. In clean books the opening checks tie. No gate outcome changes. |

## SC-05 — Invoice identifiers are not chronological

Discovered before any M1 code existed. Approved 2026-09-17.

| | |
|---|---|
| **Original assumption** | Implicit: invoice numbers follow invoice dates. SC-03 checked only the end-to-end average rate. |
| **Problem** | At ~900 invoices per half-year (~5/day): `INV-10542` (2026-03-12) and `INV-10611` (2026-04-09) leave 68 numbers for ~135 invoices dated between them, while `INV-10301` (2026-02-20) to `INV-10542` leaves 240 numbers for ~95 invoices. Chronological numbering would need volume swinging from ~12/day to ~2.5/day. No steady-volume chronological sequence satisfies the documented anchors. |
| **Approved correction** | LedgerPro invoice numbers are reserved at sales-order entry, including standing and export orders entered ahead of fulfillment, so they are not chronological. **Identifiers establish identity; business dates establish chronology.** Production code must never infer chronology from identifier magnitude. |
| **Expected-result impact** | None. No documented ID, date or amount changes. |

## SC-06 — Manual journal numbering context

Discovered before any M1 code existed. Approved 2026-09-17.

| | |
|---|---|
| **Original assumption** | Implicit: manual journal numbers `JE-2026-NNNN` are a dense chronological sequence. |
| **Problem** | Anchors `JE-2026-0388` (2026-04-02), `0412` (04-30), `0455` (05-31) and `0456` (06-01) leave room for at most 387 manual journals before 04-02, 23 in April and 42 in May. That implies very uneven manual-journal volume if numbers are dense. |
| **Approved correction (context, not an invariant)** | During Q1 Brightwater posted daily per-warehouse COGS relief journals by hand. LedgerPro perpetual inventory was enabled on 2026-04-01; from then on COGS posts automatically with each invoice. Draft journal numbers can be reserved and abandoned, leaving gaps. Journal identifiers are opaque. Volumes are **not** tuned to force a number sequence, and no gap percentage is an invariant. |
| **Expected-result impact** | None on documented effects. |

## SC-07 — Vendor and customer codes

Discovered before any M1 code existed. Approved 2026-09-17.

| | |
|---|---|
| **Original assumption** | Implicit: party codes are chronological creation sequences. |
| **Problem** | `V-1187` was created 2026-02-11 yet `V-1263` exists in a ~95-vendor master; a creation sequence would mean 76 vendor codes issued since February. Customer codes reach at least `C-0412` while only ~178 active customers are exported. |
| **Approved correction** | Vendor codes are typed by the AP clerk and are not chronological. Customer code gaps correspond partly to historical inactive customers. These exist in the LedgerPro universe, normally have no H1 activity, are excluded by the normal active-only customer export, and must not create unrelated reconciliation failures. |
| **Expected-result impact** | None. Inactive historical customers hold no open items at either aging date and have no H1 activity. |

---

## Final pre-implementation consistency review (2026-09-17)

Performed after SC-01 – SC-07, still before any M1 code. The following were checked together for mutual consistency. Each check became an executable invariant or golden-manifest test in M1.

| Area | Result |
|---|---|
| Opening TB balances; opening AR/AP agings; carried-forward documents | Consistent under SC-04: opening aging totals equal the opening TB control accounts by construction of the legacy universe, and carried-forward documents explain H1 applications. |
| H1 activity; cutover TB; cutover agings | Consistent: TB closing = opening + posted activity by posting period; aging at cutover = open documents − unapplied credits. |
| Bank controls (DS-10) | Consistent: bank − GL = 18,585.75 (outstanding checks) − 4,120.00 (deposit in transit) − 270.00 (unrecorded fees) = 14,195.75, and 412,906.18 + 14,195.75 = 427,101.93 ✓. The clean books (before DS-02's duplicate disbursement of 14,862.50 and DS-10's 270.00 of fees) have GL cash 427,768.68 and bank 442,234.43; the difference 14,465.75 = 18,585.75 − 4,120.00 is exactly the timing items. |
| DS-07 | 7,800.00 × 1.0850 = 8,463.00; 5,450.00 × 1.0790 = 5,880.55; 11,200.00 × 1.1120 = 12,454.40; understatement 663.00 + 430.55 + 1,254.40 = 2,347.95 ✓. INV-10542 and INV-10611 must be open at cutover (otherwise each receipt would leave a documented-but-absent unapplied credit); INV-10689 was paid at the booked rate. |
| DS-01/DS-02 | V-1042 23 bills and V-1187 4 bills after both injectors: the clean books have 26 Pacific Coast Packaging bills; DS-01 moves 3 bills dated on or after 2026-02-11 (including open B-21544 6,120.00) to V-1187; DS-02 adds duplicate B-21007. Both disbursements clear the bank, so R4 and R5 are unaffected. |
| DS-03/DS-04 R3 | Unassigned (38,400.00) + C-0233 +9,340.00 = (29,060.00) ✓. R3b: INV-10877 left-only +9,340.00. |
| DS-05, DS-08, DS-11, DS-12 R1/R2 | Signs follow `left − right` (SC-02). DS-12's R2 `unmapped` difference is +2,315.77 at every period end after its last suspense entry (February onward); January shows the January-to-date net of the suspense entries. |
| DS-11 R4 | +1,184.62 for Portland General Utilities requires B-20455 to be paid within the window (its payment debit is in the GL while the 2062-dated credit is excluded) — the generator pays it in April. |
| DS-06, DS-09, DS-13 | No reconciliation effects. DS-09's customer is excluded from the customer export only; its documents and receipt remain exported. |
| TN-01 – TN-05 | Legitimate in clean books; none alters any control total. |
| Readiness | 9 of 12 gates fail in Run #1; SC-01 – SC-07 change no gate outcome. |

No contradiction remains that would alter ground truth.
