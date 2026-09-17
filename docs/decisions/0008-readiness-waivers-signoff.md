# 0008: Readiness gates, waivers and sign-off (M7)

Status: **Accepted** (autonomous Tier 1 and Tier 2 decisions, 2026-09-17).

| # | Decision | Why |
|---|---|---|
| R-01 | **A waiver is bound to the gate's scope, not to one fingerprint.** Each failing waivable gate reports a scope: every discrepancy line with its unexplained amount (G6, G7), the unexplained cash difference and each open unrecorded bank item (G8), or the exposure (G9). A waiver applies while the gate's current scope equals the approved scope, across unrelated input changes; it lapses (audited `gate_waiver.lapsed`) when any waived amount changes or a discrepancy appears or disappears. Reconciliations that could not run are never waivable. Gate set version 1 → 2. | governance.md §4.3. The M2 engine bound waivers to one fingerprint only, which contradicted "remain valid across fingerprints only if the waived lines' unexplained amounts are unchanged". The Brightwater scenario test now checks both survival (DS-01 merge) and lapse (DS-08 correction). |
| R-02 | **Readiness can be evaluated more than once per run.** A run's first evaluation happens when it executes; waivers, sign-offs and pending change requests change readiness without changing the fingerprint, so an `evaluate_readiness` job re-runs the deterministic engine on the current run's inputs, requires the same result fingerprint (`readiness.reproduction_failed` otherwise), and records a new evaluation (`sequence`, `trigger=governance`). Reads use the latest evaluation. | Keeps one code path for gate evaluation; the result-fingerprint check makes the re-evaluation self-verifying. Cost: one engine run per governance change (about 1 second for Brightwater, about 35 seconds for a 250,000-line migration). |
| R-03 | **Waiver and sign-off payloads are resolved by the server** from the current run's latest evaluation (`relay.pipeline.readiness`): a waiver names only its gate; a sign-off names nothing. Submission and every approval re-check the resolution; a request whose run or scope no longer matches becomes stale. | Clients cannot choose a scope or a fingerprint. |
| R-04 | **Sign-off preconditions**: G1–G10 pass or are waived on the current run, and no other change request is submitted or stale. Lead and controller approve. Applying it records the sign-off against Relay's run fingerprint and sets the migration to `signed_off`; the engine receives it translated to its own input fingerprint. | governance.md §4.2 (G12 after G1–G11). G11 would otherwise always count the sign-off request itself. |
| R-05 | **Any later fingerprint change invalidates a sign-off** (audited `readiness.signoff_invalidated`) and returns the migration to `in_progress`. Invalidation is checked whenever a run is requested, executed or re-evaluated. | governance.md §4.2. |
| R-06 | **Change request orchestration lives in `relay.pipeline.approvals`**, shared by the API, the seed and the fast-forward tool: payload resolution, the pipeline-lock-first ordering, run requests after application, and readiness re-evaluation otherwise. | Demo tooling must follow exactly the path people follow. |
| R-07 | **`relay-demo fast-forward --to before-signoff`** (`make demo-fast-forward`) applies the documented resolutions as the seeded people through that orchestration. It skips steps already done and fails unless only G12 fails at the end. | demo-scenario.md §7 step 10. It lives in `relay_scenarios` (demo tooling may know the planted problems) and never reads evaluation truth. |
| R-08 | **`GET /migrations/{id}/policy`** and a Settings page propose policy changes. | E2E-5 changes policy through the UI. |

## Found while building M7

- The sign-off was stored against Relay's run fingerprint while the engine compared it with its engine input fingerprint, so G12 never passed. The configuration now translates sign-offs for the current fingerprint (integration test).
- The 0005 downgrade guard first refused on recomputable rows (repeated evaluations, readiness jobs) and did not protect governed waivers and sign-offs. It now refuses only when waivers or sign-offs exist and removes derived rows.

## Known limitations

- Waiver expiry dates are not implemented.
- Readiness re-evaluation runs the whole engine; persisted results are not reused.
- Approvals still wait for a running pipeline (0007).
