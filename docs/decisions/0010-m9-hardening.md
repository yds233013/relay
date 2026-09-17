# 0010: M9 hardening — security review, measured performance, engine error handling

Status: **Accepted** (autonomous Tier 1 and Tier 2 decisions, 2026-09-17).

M9 began with a file-by-file audit of every requirement ID in
[security-and-correctness.md](../security-and-correctness.md). The result is
[traceability.md](../traceability.md): each ID maps to the tests that check it or to a stated
limitation. These decisions record what that audit changed.

| # | Decision | Why |
|---|---|---|
| H-01 | **A rule or reconciliation that raises is recorded, not fatal.** The engine catches the exception per rule and per reconciliation, records an `ErroredStage` (`rule:<id>` or `reconciliation:<id>`) carrying the exception type and message, and continues. G4 fails with those stages as evidence; the rule run is persisted with status `errored` and its message (Alembic `0007_errored_stages`). An error-free result keeps exactly the fingerprint it had, so only runs that errored change identity. | FC-10 and governance.md §4.2 name "no errored rules/recons" as part of G4, but `errored_stages` was never populated: a raising rule failed the whole run, losing every other finding. Readiness still cannot pass — now the evidence survives and names the broken stage. |
| H-02 | **A reconciliation may not explain more than its difference.** `ReconLine` refuses construction when the explained amount runs past the difference, reverses its sign, or explains anything on a tied line. | FC-11 ("never beyond the remaining difference") had no enforcement: `unexplained = difference - explained` could silently reverse. The whole Brightwater scenario, with every planted defect, builds under the invariant, so it is not over-strict. |
| H-03 | **Gate evidence resolves only the lines it names.** `resolve_evidence` loaded every reconciliation line of the run once per gate. | Measured: the readiness endpoint took 2.26 s on a 60,000-line migration and 5.8 s on 250,000 lines; it now takes 0.09 s. The overview endpoint fell from 0.8 s to about 0.12 s. |
| H-04 | **A route inventory test.** Every mounted route must depend on the actor dependency unless it is listed as deliberately public, and every non-GET route must appear in a table of governed operations with what it does. | SEC-10 asks for default deny and GV-01 for a route inventory. Authentication is declared per route, so nothing would have caught a new endpoint that forgot it. 72 routes are covered. |
| H-05 | **Static guards for what code enforced silently**: no `eval`/`exec`/`pickle`/`subprocess`/`yaml` in `relay.*` (SEC-04), every `text(...)` a literal (SEC-13), `.env` ignored and `.env.example` valueless (SEC-23), lockfiles committed (SEC-30), images pinned by digest and non-root (SEC-31), no downloads in builds (SEC-32). | These were true but untestable claims. The SQL guard immediately found one f-string statement (`SET LOCAL statement_timeout = …` in the AI read-only session); it now binds the value through `set_config`. |
| H-06 | **Nonce-based Content Security Policy on the web** (`web/src/proxy.ts`): scripts only by per-request nonce plus `strict-dynamic`, never `unsafe-inline`; everything else `'self'` or `'none'`; `frame-ancestors 'none'`. The API sends `default-src 'none'; frame-ancestors 'none'; base-uri 'none'`. **CORS stays unconfigured**: the browser never calls the API, so no origin needs to be allowed and the default (no CORS headers) is the strictest option. | SEC-15 was the largest missing control. Every Relay page is dynamically rendered, so Next.js can apply the nonce to its own scripts. An end-to-end test asserts the served header and that the app runs under it with no violations. |
| H-07 | **Uploads are rate limited per person** (`RELAY_MAX_UPLOADS_PER_HOUR`, default 300), checked before any bytes are read. | SEC-17 asked for rate limiting on upload and investigation endpoints; only investigations had it. The default is high enough for real work — loading one migration uploads about 16 files and re-imports repeat some — and low enough to bound runaway automation. Counted from persisted rows, so rejected uploads do not count. |
| H-08 | **CSV headers are limited to 512 columns** (SEC-01). | Byte, row, field and record-line limits existed; a pathological header would still have sized every row dictionary and every profile. |
| H-09 | **CI runs the full suite under `TZ=Australia/Adelaide`.** | FC-06 asks for tests with a non-UTC process timezone; only one unit test set `TZ` itself. A half-hour offset ahead of UTC exposes dates built from local time. Everything passes: 892 unit, 99 integration, 115/115 manifest. |
| H-10 | **Optimistic concurrency stays a `version` field in the request body** (409 on conflict), not `If-Match`/`ETag`/412 as GV-08 states. | The version is part of the resource the client already loads and edits, the API has no caching semantics that `ETag` would serve, and every mutation is a command rather than a resource replacement. Recorded as a deviation rather than changed; the missing test for change request drafts was added. |
| H-11 | **Separate database roles (SEC-25) are not implemented.** One role owns and runs everything, so the application role could disable the append-only triggers. | Doing it properly needs a second credential, a Compose init script (roles exist before migrations run), grants re-applied as migrations add tables, and a split between the migrating and running identities. It is stated as a limitation in [traceability.md](../traceability.md) rather than half-built. The audit log stays tamper-**evident**: `make verify-audit` reports exactly where a chain was broken. |
| H-12 | **A persisted-pipeline performance measurement** (`make pipeline-perf`, `relay-demo perf-pipeline`): a synthetic migration loaded through the same services as the demo seed, then a governed change and its rerun, a readiness re-evaluation, and the main read endpoints timed in process. It uses a throwaway database and drops it. | `make engine-perf` measured only the pure engine. Every number in progress.md comes from one run of this tool on this machine. |

## Found while hardening

- `test_database.py`'s migration round trip shared the test database with `test_ai.py`, whose
  drafted change requests correctly block the `0006` downgrade. The round-trip and readiness-probe
  tests now create their own empty database; the guard is unchanged.
- The first upload limit (60/hour) failed the test suite, which seeds several migrations as the same
  person within an hour. That was the limit being wrong, not the tests: a real implementer uploads
  at least that many files in a day of work.

## Known limitations after M9

- SEC-25 (database roles) as above; SEC-05 (CSV export neutralisation) has nothing to apply to.
- GV-05 has no instrumented check that every committing service method writes an audit event.
- SEC-21 recognises sensitive fields by name and pattern rather than by classification in the
  canonical schemas.
- SEC-20 has no static guard against a future log call taking row values, prompts or completions.
- `load_configuration` issues about 90 queries per call (one per dataset for its active import,
  stored file, mapping set and source system). At 250,000 lines that is roughly 0.1 s on every
  overview and readiness read.
