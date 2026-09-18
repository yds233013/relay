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
| Readiness | **NOT READY** |
| Gates | 9 of 12 failing (G2, G4 and G11 pass) |
| Unresolved exposure | 217,212.85 USD |
| Open issues | 65 |
| Evaluated run | the first evaluated run, marked *current* |
| Signed in as | Maya Chen (implementation specialist) |

The seeded people, and what each may do:

| Person | Role | Can |
|---|---|---|
| Maya Chen | implementation specialist | upload, run the pipeline, draft change requests, work issues |
| Daniel Okafor | implementation lead | the above, plus **approve** |
| Priya Raman | customer controller | draft, work issues, **approve** |
| Sam Ortiz | viewer | read only |
| Alex Lindqvist | admin | manage the workspace; **cannot** approve or draft |

Switch with **Switch user** in the header. It is a development identity, not authentication.

---

## 4. The 3–5 minute story

**"The mapping that passed the type check and moved $38,400 into the wrong control account."**

Everything below is produced by the running system. Nothing is scripted.

| # | Where | What to do | What it shows |
|---|---|---|---|
| 1 | **Overview** | Read the header: NOT READY, 9 of 12 gates, 217,212.85 exposure, the gate strip G1–G12. | The whole migration in one screen, and that readiness is a set of named conditions rather than a score. |
| 2 | **Overview → Amount at risk** | Point at the split: 215,779.52 *migration defect* vs 2,617.95 *source anomaly*. | Relay distinguishes "our import is wrong" from "the customer's books are wrong". They get different remedies. |
| 3 | **Mappings** | The filter defaults to *Needing attention*: one row, legacy **1205 Allowance for Doubtful Accounts** (contra asset) → **1200 Accounts Receivable**. Note the chips: target exists ✓, type ✓, **subtype conflict ✕**. | A type check alone passes — asset to asset. The subtype check is what catches a contra-asset landing in the receivables control account. |
| 4 | **Reconciliation → R3** | Open the line `party=unassigned`: difference **(38,400.00)**. Then the line `party=C-0233`: difference **9,340.00**, one document `INV-10877` marked *Left only*, with its ledger record and the **row 3666, line 3667** source link. | Two independent defects in one control; the drill-down names the document and the file line rather than asserting a total. |
| 5 | **Click the source link** | The raw export row, highlighted, tagged **Source**. Then open the record `jl:JE-AR-10877:1` — raw values tagged **Source** beside the normalized record tagged **Canonical**. | Provenance end to end, and a transformed value can never be mistaken for customer evidence. |
| 6 | **Issues → BWP-41** | 38,400.00 at risk, critical, `RECON.R3`. Note there is no "mark resolved" button. | Rule-backed issues are resolved only by a run that stops reporting them — not by a person changing a status. |
| 7 | **Mappings** | In the 1205 row type `1210` into **New target**, add a rationale, a title and a justification, then **Propose mapping change**. | A correction is a proposal with a diff, not an edit. |
| 8 | **The change request** | Read the mapping diff (before struck through, after inserted) and the **Approvals** box: as Maya you see *"requesters cannot review their own change request."* | Segregation of duties, enforced by the API rather than by hiding a button. |
| 9 | **Switch user → Daniel Okafor** | Open the change request, **Approve**. Then **Switch user → Priya Raman** and **Approve**. | `account_mapping_set` needs the implementation lead *and* the customer controller. Two people, neither of them the requester. |
| 10 | **Runs** | Open the newest run and use **Compare with another run**. Then **Reconciliation → R3**: the `unassigned` line is gone. | The run is a deterministic function of its inputs; the diff shows exactly what one approved decision changed. |
| 11 | **Overview / Readiness** | Exposure has dropped by 38,400.00 and G3's blocker is gone. | Readiness moves because the evidence moved. |
| 12 | **Audit log** | Filter Action `change_request.applied`. Expand **before / after**. Note the green **chain verified** chip. | Who, when, why, what changed, who approved — append-only and hash-chained. |

Total: about four minutes at a talking pace.

### Optional deeper tour

- **Reconciliation → R5** — the cash control *ties* and G8 still fails. The callout says why:
  identified is not excused. This is the subtlest accounting point in the product.
- **Entities** — four duplicate candidates. Two are strong (score 1.0000); two score 0.6013 because
  the address token conflicts. Merging all of them would be wrong: `GREEN VALLEY COOP #2` is a
  different store. Relay refuses to decide.
- **Validation** — 37 rules, their versions, and every finding they produced.
- **Data → an import → the row viewer** — 18,369 source rows, one quarantined, kept exactly as
  received.
- **Settings** — the policy that the engine reads, and the fact that changing it is itself a change
  request that invalidates any sign-off.

### Reaching sign-off

Sign-off only becomes available when G1–G11 pass or are waived. To get there without spending the
meeting on it:

```bash
make demo-fast-forward
```

This applies the remaining documented resolutions **as the seeded users through the same services**
— the same approvals, the same audit events, no shortcut. It leaves exactly one gate failing (G12,
sign-off) so you can request sign-off, approve it as the lead and the controller, and watch the
migration turn READY. Then change any policy value in **Settings** and watch the sign-off show
*"the inputs changed after sign-off"*.

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
