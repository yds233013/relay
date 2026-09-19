# Demo guide

How to run Relay locally, what the opening state should look like, and the walkthrough that shows
the most in the least time. Everything here uses the product's own services — no database editing,
no scripted outcomes, no fixtures written mid-demo.

---

## 1. Setup

Once per machine:

```bash
make setup
```

Then bring up the stack (PostgreSQL, API, worker, web) and load the demo:

```bash
make up && make demo-reset
```

`make up` builds and waits for health. `make demo-reset` **destroys** the local database, recreates
it, migrates, and seeds Brightwater through the real import/mapping/run services as the seeded
users. It takes a couple of minutes.

Check it:

```bash
make smoke
```

It should print `smoke: web -> api -> database OK`.

### If a port is already in use

Host ports default to 55432 (database), 8000 (API), 3000 (web). Override any of them in the
environment — the Makefile threads them through to Compose and to the end-to-end tests:

```bash
export RELAY_DB_HOST_PORT=55432 RELAY_API_HOST_PORT=18000 RELAY_WEB_HOST_PORT=13000
```

Use the same values for every later command in the same shell, or the stack and the tests will
disagree about where the API is.

---

## 2. Open it

**The URL depends on the web port you started the stack with.** Get it from Docker rather than
guessing — this prints the exact address that is listening:

```bash
docker compose port web 3000
```

- Default ports: <http://127.0.0.1:3000>
- With the override above (`RELAY_WEB_HOST_PORT=13000`): <http://127.0.0.1:13000>

Two things that will look like "Relay is down" when it is running:

- **the wrong port** — if you overrode `RELAY_WEB_HOST_PORT`, the default URL has nothing behind it;
- **`https://`** — there is no TLS listener, so the browser gets a connection error. Use `http://`.

Prefer `127.0.0.1` over `localhost`: the ports are published on IPv4 only, and `localhost` resolves
to IPv6 `::1` first on macOS. Browsers fall back to IPv4, but some tools do not.

You land on the **Portfolio**. Click **Brightwater Provisions, Inc.**

---

## 3. The initial state

A clean reset always produces exactly this. If it does not, something has already been changed —
re-run `make demo-reset`.

| | |
|---|---|
| Command center | 1 implementation · 0 ready · 1 not ready |
| Brightwater | **NOT READY FOR GO-LIVE**, 9 of 12 readiness checks still need resolution |
| Unresolved exposure | 217,212.85 USD |
| Findings | 65, grouped into **20 decisions** in the work queue |
| Verified on | the first evaluated run, marked *current* |
| Signed in as | Maya Chen (implementation specialist) |

The seeded people, and what each may do:

| Person | Role | Can |
|---|---|---|
| Maya Chen | implementation specialist | upload, run the checks, propose changes, work issues |
| Daniel Okafor | implementation lead | the above, plus **approve** |
| Priya Raman | customer controller | propose, work issues, **approve** |
| Sam Ortiz | viewer | read only |
| Alex Lindqvist | admin | manage the workspace; **cannot** approve or propose |

Switch with **Switch user** in the header. It is a development identity, not authentication.

---

## 4. The 3–5 minute story

One story, not a tour: **automation → human judgement → control → verification.**

### 1. What are we running? (20 seconds)

Land on the **implementation command center**. One implementation, Brightwater Provisions, moving
from LedgerPro to a new ERP. It is **not ready**, 9 of 12 readiness checks are failing, 217,212.85
is unresolved, and the target go-live has already passed. Click **Open implementation**.

### 2. What did Relay do on its own? (30 seconds)

On the overview, read **What Relay checked automatically**: 24,472 records normalized, 37
accounting controls run, 10 reconciliations performed, 65 findings raised — all counted from the
last verification run, none of it typed in by a person.

Then read the header: **NOT READY FOR GO-LIVE**, and six plain-English checks beneath it — data
completeness, account mapping, ledger integrity, subledgers and cash, open exceptions, approvals and
sign-off. Say the line that matters: *nobody triaged those 65 findings by hand.*

### 3. What needs a person? (30 seconds)

**Needs attention** shows the findings collapsed into decisions. Top of the list:

> **Review how legacy account 1205 is mapped — 38,400.00 USD affected**
> AR subledger vs GL control accounts differs by 38,400.00, and Relay attributes the whole
> difference to legacy account 1205 Allowance for Doubtful Accounts. That account is mapped to 1200
> Accounts Receivable, which the compatibility check flags as the wrong accounting treatment.
> *Needs your judgement: Relay can tell that the treatment conflicts. Choosing the right target
> account is an accounting decision for the implementation team.*

That grouping is composed, not scripted: a reconciliation attributed the difference to exactly one
legacy account, and that account's mapping is one the compatibility check doubts.

### 4. Why is it wrong, and where is the evidence? (45 seconds)

Click **Review mapping**. The row is highlighted: `1205 Allowance for Doubtful Accounts` (a contra
asset) mapped to `1200 Accounts Receivable` — **target exists ✓, type ✓, subtype conflict ✕**.

The point worth saying out loud: a type check passes, asset to asset. Only the subtype check catches
a contra-asset landing inside the receivables control account, which is why the ledger still added
up and the subledger did not.

For the evidence chain, detour to **Reconciliation → R3 → `party=unassigned`** (38,400.00, attributed
to account 1205) and to `party=C-0233`, where one invoice is *left only* and links to the exact
source row — file line and all.

### 5. Propose the correction (30 seconds)

Back on **Mappings**, type `1210` as the new target for 1205 (Relay suggests it; you may overrule),
add a rationale and a justification, and click **Propose mapping change**.

Nothing has changed yet. The change request shows the control steps — *proposed → approved →
applied → re-verified* — and the approvals box tells Maya: **requesters cannot review their own
change request.**

### 6. Two other people approve (45 seconds)

**Switch user → Daniel Okafor** (implementation lead) → **Approve**. **Switch user → Priya Raman**
(customer controller) → **Approve**. An account mapping change needs both, and neither may be the
requester. On the second approval the change applies in one transaction and a fresh run is queued.

### 7. Did the correction actually work? (45 seconds)

This is the part most demos skip. Relay re-runs every deterministic check against the new inputs:

- **Verification runs → newest run → Compare with another run** shows what changed;
- **Reconciliation → R3**: the `unassigned` difference is gone;
- **Overview**: unresolved exposure has dropped by 38,400.00 and the work queue is shorter;
- **Readiness**: the account-mapping check moves.

Relay does not take anyone's word that the fix worked — it re-derives the answer.

### 8. Prove what happened (20 seconds)

**Audit log**, filter Action `change_request.applied`, expand **before / after**: who proposed it,
who approved it, what changed, when, and a **chain verified** badge over the whole hash chain.

**The whole story in one sentence:** Relay checked the migration automatically, told the team which
decision was worth 38,400, refused to let the person who proposed the fix approve it, and then
re-verified the books itself.

### Optional deeper tour

- **Reconciliation → R5** — the cash control *ties* and the cash check still fails. Identified is
  not excused.
- **Duplicate parties** — four candidates; two strong, two scoring 0.6013 because the address
  conflicts. Merging all of them would be wrong, so Relay refuses to decide.
- **Record inspector** on any journal entry — the original exported row beside Relay's normalized
  interpretation, so a transformed value can never pass as customer evidence.
- **Imported data → an import** — 18,369 source rows, one quarantined, kept exactly as received.

### Reaching sign-off

Sign-off only becomes available when every other check passes or is waived:

```bash
make demo-fast-forward
```

This applies the remaining documented resolutions **as the seeded users through the same services**
— same approvals, same audit events, no shortcut. It leaves exactly one check failing (sign-off), so
you can request it, approve it as the lead and the controller, and watch the implementation turn
READY. Then change any policy value in **Policy** and watch the sign-off show *"the inputs changed
after sign-off"*.

---

## 5. Recovering

Any of these puts you back at the initial state:

```bash
make demo-reset
```

It is safe to run at any point, takes a couple of minutes, and requires no manual database work. Run
it after the end-to-end suite (`make test-e2e` deliberately mutates demo state) and after rehearsing
the story above.

---

## 6. Known demo limitations

- **Go-live shows a negative "days to go-live"** if today is past 2026-07-01. The scenario's dates
  are fixed so that its expected results stay reproducible; the clock is not.
- **The AI investigator is off.** It needs both a configured provider and recorded customer consent;
  the stack ships with `RELAY_AI_PROVIDER=disabled` and no consent, so the UI shows a short
  "Assistant off" note instead of the panel. No live-model run has ever been recorded — the AI evals
  pass against scripted transcripts only.
- **The user switcher is not authentication.** It exists so one person can demonstrate segregation
  of duties alone.
- **Kestrel** — the second company — is an evaluation scenario, not a demo workspace. Inspect it with
  `make demo-kestrel-verify`, not in the browser.
- **The end-to-end suite changes demo state** (it approves changes, merges entities and signs off).
  Always `make demo-reset` afterwards.
