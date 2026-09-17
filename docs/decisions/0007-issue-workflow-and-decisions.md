# 0007: Issue workflow, entity decisions, dispositions and re-imports (M6)

Status: **Accepted** (autonomous Tier 1 and Tier 2 decisions, 2026-09-17).

| # | Decision | Why |
|---|---|---|
| I-01 | **`relay.changes` sits above `relay.issues`** in the import layers (previously independent). Disposition appliers call the issues workflow service; each module still writes only its own tables. | A disposition and the issue's `dispositioned` status must change in the approval transaction. |
| I-02 | **People move issues only between `open` and `in_progress`**, assign active users as owners, and comment. Manual issues can also be closed and reopened. Setting `resolved` is refused with `issue.resolution_requires_verification`. Updates carry the issue version; a mismatch is `issue.version_conflict`. | governance.md §1.2. |
| I-03 | **Issues named as evidence** (`evidence_refs` entries `{"kind": "issue"}`) move to `awaiting_verification` when a change is applied (dispositions excepted). A current run that still reports the finding moves the issue back to `open` (`issue.verification_failed`); one that no longer reports it resolves it as before. | The diagram's "CR applied → awaiting_verification" needs a rule for a fix that did not work. |
| I-04 | **System links** (`same_root_cause`) join issues of a current run that share a subject or a journal entry (a line `jl:E:n` shares entry `je:E`). Groups larger than 25 issues on one key are not linked. Links are never deleted. | governance.md §1.1 step 4, bounded so a very common key cannot create quadratic link counts. |
| I-05 | **Entity decisions** name party codes that must exist in the named succeeded run. A proposal whose member pairs overlap an active decision is refused (revert first). Lead approval. Survivorship per field is not implemented: the survivor is the whole record. Transitive contradictions (A=B, B=C, A≠C) are not detected. | Pairwise overlap is the conflict the engine's clustering cannot resolve deterministically; the rest is recorded as a limitation. |
| I-06 | **One disposition change request can cover several issues** (for example six months of the same bank fee). Each issue gets a disposition row; the amount is stored on the row only when the request covers one issue, and on the change request otherwise. Critical findings cannot be accepted as risk. A carry-forward adjustment states its amount. | DS-10 is one decision about six findings. |
| I-07 | **Disposition approvals**: customer controller for `accepted_risk`, `carry_forward_adjustment`, and any disposition of a critical or high finding; implementation lead for low or medium `false_positive` and `not_applicable`. | governance.md §2.3 lists `not_applicable` under the lead without a severity; requiring the controller for critical and high findings is the conservative reading. |
| I-08 | **`revert` targets any overlay**: `{"target": "record_override" | "entity_decision" | "disposition", "target_id"}`. The M5 form `{"record_override_id"}` is still accepted. Reverting a disposition reopens the issue. | One kind for every overlay; old stored payloads stay valid. |
| I-09 | **Corrected exports are committed fixtures**: `fixtures/demo/brightwater_reexport/` holds the files that change when the same books are exported without filters (chart of accounts, customers, invoices). `relay-demo generate` writes them and `relay-demo check` verifies them; a test checks they equal the documented resolution's re-exports. | Re-imports (DS-04, DS-09, DS-12) are exercised through the UI and API with real files. |
| I-10 | **Web uploads pass through a Server Function** with a 10 MB body limit (`serverActions.bodySizeLimit`); larger files go to the API directly. | Next.js defaults to 1 MB; the Brightwater GL export is 1.1 MB. |
| I-11 | **Issue comments are append-only** (database trigger, as for audit events). | data-model.md §10: comments are immutable. |
| I-12 | **G11 counts submitted and stale change requests**, as governance.md specifies; stale requests can be withdrawn. This reverses M5's G-06. | G-06 contradicted the specification. Stale requests would otherwise block G11 forever. |
| I-13 | **New migrations** are created by users with `manage_workspace` (implementation leads): company and conversion plan, then source systems and datasets on a Setup page. The owner selector uses the development user directory, which exists only with development identity. | E2E-8. |

## Found while building M6

- **Commits happened after responses.** The database session was a FastAPI yield dependency with the default scope, which ends after the response is sent. A client could receive 201 for data it could not yet read (seen as "mapping set does not exist" when E2E-8 proposed a mapping right after creating it), or for a transaction that later failed to commit. The session dependency now uses `scope="function"`: commit or roll back before responding (unit test checks the scope).
- **Deadlock between an approval and a running pipeline.** An approval wrote audit events (per-migration audit advisory lock) and then requested a run (pipeline lock); the worker takes the pipeline lock and then writes audit events. Approvals now take the pipeline lock first. An integration test holds the pipeline lock as the worker would, starts an approval, then takes the audit lock: it reproduced `deadlock detected` before the fix and passes after.

- The API accepted issue key prefixes with digits while the database requires 2–6 capital letters, so creating such a migration failed with an internal error. The API and the service now reject it with 422 (regression test).
- A draft whose submission was refused stayed behind as an orphan draft. The web now withdraws it.
- The answer-leak test's `\bgolden\b` pattern matched inactive customer names such as "Golden Hollow Foods" in the unfiltered export. The pattern now targets evaluation vocabulary ("golden manifest", "golden truth" and similar) instead of the adjective.
- A Playwright step read the page URL before the redirect after "Propose" completed. Tests now wait for the change request URL.
- Suggestions did not recognize "Customer Code". Customer and vendor code and number synonyms were added; the Brightwater measurement is unchanged (112 of 126 source columns).

## Known limitations

- **Approvals wait for a running pipeline.** `execute_run` holds the per-migration pipeline lock for the whole run, and applying a change requests a run under the same lock, so an approval that applies a change blocks until an in-flight run finishes (seconds for Brightwater; about a minute for a 250,000-line migration). The lock currently guarantees that only current runs synchronize issues. Planned for M9: hold the lock only to claim the run and to commit, and skip issue synchronization when the fingerprint is no longer current at commit. Found when an E2E approval took longer than 5 seconds.

- Readiness is still evaluated only when a run executes (P-14): withdrawing a stale request or reverting a disposition without a fingerprint change does not re-evaluate gates.
- Priority on issues, `caused_by`/`blocks` user links, and bulk issue updates are not implemented.
- Owner selection depends on the development user directory.
