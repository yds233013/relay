# Relay — project brief

**Live demo:** https://web-production-9032d5.up.railway.app · **Code:**
https://github.com/yds233013/relay

Independent portfolio project. All data is fictional.

**Problem.** Every ERP implementation is a data migration. The team has to move messy legacy
accounting data into a new system and decide whether it is safe to launch. Today that is
spreadsheets, email and judgement: exports compared by hand against trial balances, fixes applied
straight to staging data, and a go-live call made in a meeting.

**Why I built it.** Most of that work is repeatable — comparing, chasing differences, proving a fix
held. I wanted to see how far it can be automated without handing judgement or authority to a
model.

**What it automates.** Importing and profiling legacy exports; mapping them onto a canonical model;
37 accounting rules and 10 reconciliations against the customer's own control reports; grouping 65
findings into the 20 decisions a person must make; gathering evidence for each; re-running every
check after a fix; and evaluating 12 go-live readiness gates.

**How it works.** Import → profile → map → normalize → validate → reconcile → investigate →
resolve and approve → verify → launch. Source rows are append-only. Every correction is an overlay
applied by an approved change request, followed by a fresh deterministic run. An issue is resolved
only when a run stops reporting it.

**AI design.** A bounded investigator with 15 read-only tools, scoped server-side to one migration
and one run, over read-only database sessions. It returns a structured finding, and the system
re-checks every value and record it cites against the tool results before the finding can become
a draft change request. It can propose but never apply, approve, or change an issue. Removing it
removes no correctness. The public demo replays a scripted transcript against the real tools; no
live-model run has been recorded.

**Safety and governance.** Server-enforced segregation of duties: the requester never approves, and
material changes need two named roles. Every governed mutation writes a hash-chained audit event in
the same transaction. Sign-off is bound to one exact run and lapses on any input change. The public
demo refuses every mutation except starting an investigation, by a deny-by-default policy applied
before routing.

**Technical architecture.** Modular monolith with import contracts: a pure deterministic core (no
DB, I/O, clock or randomness), database modules, and FastAPI, a PostgreSQL job worker and Next.js
at the edges. Python 3.12, SQLAlchemy 2.0, PostgreSQL 16, Next.js 16, TypeScript. Deployed on
Railway: a public web service, a private API-plus-worker service with a volume, private Postgres.

**Evaluation.** Expected results were hand-written from the accounting specification before the
engine ran, and are never edited to match it. A second fictional company with a different legacy
system, formats, currency and fiscal year runs through the unchanged engine. CI runs 1,096 unit and
scenario tests, 135 integration tests on real PostgreSQL, 46 web tests, 115/115 and 31/31 expected
results, and 12 end-to-end specs.

**Most interesting engineering decision.** Keeping the AI out of the path of correctness. The
engine decides what is wrong and whether a fix worked; the investigator only gathers evidence, and
even that is verified before a person sees a proposal. That made the AI optional — and made every
number in the product traceable to a line in a file.

**What I learned.** Hand-writing the expected results first was the decision everything rested on:
it turned every disagreement with the engine into an investigation rather than a diff to accept.
The second company was the proof — it found three real engine bugs that the first dataset could
never have shown.
