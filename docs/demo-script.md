# Relay — three-minute demo

**Live demo:** https://web-production-9032d5.up.railway.app

This walkthrough runs against the live public demo. It is read-only for visitors, so where the
story needs an approval, it shows one that has already happened. Everything shown is real
application behaviour on fictional data. Nothing is staged except the investigator's reasoning,
which is a scripted replay, and the page says so.

Budget: about 20 seconds per step. The spoken lines are written to be said aloud; trim freely.

---

### 1. Command center — the job (0:00)

**Page:** `/migrations`
**Click:** nothing yet.
**Say:** "Relay is an implementation-operations system for getting legacy accounting data through
migration QA to a verified ERP go-live. This is the command center: every implementation, whether
it can go live, and how much money is in question. This one is a fictional distributor called
Brightwater, moving off a legacy ledger."
**Notice:** *Not ready*, 9 of 12 checks to resolve, $217,212.85 of unresolved exposure, and the
go-live date already past.

### 2. Overview — the verdict (0:20)

**Page:** click **Open implementation**.
**Say:** "The overview answers one question — can this customer go live? No: nine of twelve
readiness checks fail on the latest verification run, and every one of those numbers is computed,
not typed in. Relay normalized about twenty-four thousand records, ran thirty-seven accounting
controls and ten reconciliations against the customer's own reports, and nobody had to ask it to."
**Notice:** the red *Not ready for go-live* plate, *run #17 (current)*, the six readiness
categories, and the exposure tile.

### 3. Work queue — findings become decisions (0:40)

**Page:** sidebar → **Work queue**.
**Say:** "Sixty-five findings is noise. The work queue groups them into the twenty decisions a
person actually has to make, blocking work first, then by money. The top one is a thirty-eight
thousand dollar difference."
**Notice:** *20 items*, the *Blocks go-live* chips, and **Review how legacy account 1205 is
mapped — 38,400.00**.

### 4. The $38,400 issue — deterministic evidence (1:00)

**Page:** read the leading card, then sidebar → **Reconciliation**.
**Say:** "This came from a deterministic reconciliation, not a guess. The receivables subledger
disagrees with the general ledger control account by exactly thirty-eight thousand four hundred,
and Relay traced the whole difference to one legacy account. That account is an allowance for
doubtful accounts — a contra-asset — mapped into ordinary receivables. The mapping check flags the
subtype conflict."
**Notice:** *AR subledger vs GL control accounts* with a discrepancy. Click a differing line to show
it drills down to the records and the exact source file line.

### 5. Investigation — bounded evidence gathering (1:20)

**Page:** back to **Work queue** → **Investigate** on the leading item.
**Say:** "This is the investigator. On the left is what it did: the deterministic finding it
started from, then every tool call. The tools are read-only and scoped to this one migration. On
the right is its reading of the evidence, and underneath, Relay's own check that every claim it
makes appears in what those tools returned. In this public demo the reasoning is a scripted replay,
not a live model, and the page says so. The tools and the evidence are real."
**Notice:** *Scripted demonstration — not a model*; the tool calls; *2 claims re-checked by
Relay*, both *evidence checked*; the recommended action *Change account mapping — would require
approval*; *Human decision required*; *0* tokens under Provenance.

### 6. Change and approval — human authority (1:45)

**Page:** sidebar → **Approvals** → set **Status: Applied** → open **CR-17**, *Account mapping from
the implementation mapping file*.
**Say:** "The investigator can only propose. A fix is a change request, and it's governed: whoever
requests it can never approve it, and an account mapping needs both the implementation lead and the
customer controller. This one — the original mapping — went through exactly that. The same control
would apply to the fix for account 1205."
**Notice:** the four-step strip: *Proposed with evidence → Approved by other people → Applied in
one transaction → Re-verified by a fresh run*, and two different approvers, neither of them the
requester.

### 7. Re-run — verification, not a checkbox (2:05)

**Page:** same change request — point at step 4 — then sidebar → **Verification runs**.
**Say:** "Applying a change doesn't close anything by itself. It triggers a fresh deterministic
run, and an issue is only resolved when that run stops reporting it. Nobody ticks a finding off by
hand."
**Notice:** *Re-verified by a fresh run*, and the run history ending at run #17.

### 8. Readiness — is launch safe? (2:25)

**Page:** sidebar → **Readiness**.
**Say:** "Readiness is six plain questions answered by twelve checks. Each one says what it
observed, what the threshold is, and links to the evidence. Sign-off only unlocks when everything
else passes, and it's bound to this exact run — change any input and it lapses."
**Notice:** *Needs resolution* against specific checks, e.g. *Account mapping complete — 1
unmapped or invalid target*.

### 9. Audit — provenance (2:45)

**Page:** sidebar → **Audit log**.
**Say:** "Every governed action is written to an append-only log in the same transaction, chained
by hash so any tampering shows. Who did what, when, and what it changed."
**Notice:** *chain verified*, and the who / did what / when / result columns.

### Close (3:00)

**Say:** "So: deterministic software finds and verifies the failures, a bounded investigator does
the evidence gathering, people keep authority over the changes, and the system proves the fix
worked before anyone signs off. That's the loop that has to scale when every ERP implementation is
a data migration."

---

**Things not to claim.** The investigator in this demo is a scripted replay; no live-model run has
been recorded, so don't cite model accuracy. Brightwater and every person, account and amount are
fictional. Relay is an independent portfolio project, not any company's internal system.
