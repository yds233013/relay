# Relay

**Migration operations for ERP implementations: prove the data is right before go-live.**

> **Status: planning.** This repository currently contains design documentation only. No application code has been written yet. See [docs/implementation-plan.md](docs/implementation-plan.md).

---

## What it is

Moving a company onto a new ERP isn't just importing CSVs. Legacy exports quietly drop inactive records. Mappings put contra-accounts in the wrong place. Old books carry duplicate vendors and double payments. Fixes get made in spreadsheets nobody can audit. And the go-live decision often comes down to "looks good" in a meeting.

Relay is an internal command center for implementation teams:

- **Import** legacy ledgers, subledgers, control reports and bank data. Raw rows stay immutable, and every row keeps its file and line lineage.
- **Map** source fields and legacy accounts onto a canonical model and a target chart of accounts, using versioned, approved mappings.
- **Validate** with a deterministic, extensible rules engine: double-entry integrity, orphan references, impossible dates, currency mismatches, duplicates.
- **Reconcile** extracted detail against independent control reports (trial balance, AR/AP agings, bank statement), and source against staged data. Every discrepancy drills down to the records behind it.
- **Govern** fixes as change requests with segregation of duties, staleness detection and an append-only, hash-chained audit log.
- **Investigate** with an AI agent that has read-only tools and must cite verifiable evidence. It can draft proposals but can never change financial data.
- **Decide** go-live with 12 deterministic readiness gates, bound to a specific reproducible pipeline run and signed off by two people.

## The demo

**Brightwater Provisions, Inc.** is a fictional Portland food distributor migrating off a legacy desktop ERP. The demo data includes 13 realistic defects and 5 false-positive traps. Examples:

- An allowance account mapped into AR.
- An invoice dropped by an export filter.
- A journal entry broken by an unquoted newline.
- A duplicate vendor that hides a $14,862.50 double payment.
- EUR invoices keyed as USD.
- A prompt injection planted in a vendor note.

See [docs/demo-scenario.md](docs/demo-scenario.md).

## Planned stack

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 · PostgreSQL 16 · Postgres-backed job worker · Next.js · TypeScript · Tailwind · TanStack Query/Table · Playwright · Docker Compose · provider-abstracted LLM integration (works with AI disabled)

## Documentation

| Doc | Contents |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for contributors and AI coding sessions |
| [docs/product-spec.md](docs/product-spec.md) | Problem, critique of the original brief, MVP scope, UX |
| [docs/architecture.md](docs/architecture.md) | System design, modules, pipeline, API, jobs |
| [docs/data-model.md](docs/data-model.md) | Domain model and schema |
| [docs/validation-and-reconciliation.md](docs/validation-and-reconciliation.md) | Rules engine, reconciliations, entity resolution |
| [docs/governance.md](docs/governance.md) | Issues, change requests, approvals, audit, readiness gates |
| [docs/ai-safety.md](docs/ai-safety.md) | AI tools, verification, threat model, evals |
| [docs/demo-scenario.md](docs/demo-scenario.md) | Brightwater scenario and expected results |
| [docs/testing.md](docs/testing.md) | Test strategy |
| [docs/security-and-correctness.md](docs/security-and-correctness.md) | Requirement IDs for correctness and security |
| [docs/implementation-plan.md](docs/implementation-plan.md) | Milestones and acceptance criteria |

## Getting started

Nothing to run yet. Setup instructions will be added when milestone M0 lands.
