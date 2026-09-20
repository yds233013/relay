import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { Timestamp } from "@/components/dates";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Callout, EmptyState, MetaList, MetricCard, Panel } from "@/components/ui";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

export const dynamic = "force-dynamic";

/** Counts and timings arrive as open JSON objects; render each leaf as text, never as markup. */
function text(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

/**
 * Only a value the run actually recorded is shown. Nothing on this page is computed from the
 * payload: a number that is not stored is simply absent.
 */
function stored(source: { [key: string]: unknown }, key: string): number | null {
  const value = source[key];
  return typeof value === "number" ? value : null;
}

/** Whole counts and millisecond durations, grouped for reading. Never money (FC-15). */
function whole(value: number): string {
  return value.toLocaleString("en-US");
}

/** What asked for the run, in the words an operator would use. */
const TRIGGER: Record<string, string> = {
  change_request_applied: "an approved change",
  import_activated: "a new import",
  manual: "an operator",
};

function triggeredBy(trigger: string): string {
  return TRIGGER[trigger] ?? humanize(trigger).toLowerCase();
}

/** The work a run does, in the order the pipeline does it. Timings not listed here still show. */
const STAGES: readonly { key: string; title: string; detail: string }[] = [
  {
    key: "load_ms",
    title: "Read the imported records",
    detail: "The active import's source rows, exactly as they arrived.",
  },
  {
    key: "engine_ms",
    title: "Ran the deterministic checks",
    detail: "Normalized the records, evaluated every control and performed the reconciliations.",
  },
  {
    key: "persist_ms",
    title: "Recorded the results",
    detail: "Staged records, findings, reconciliations and readiness gates, in one transaction.",
  },
  {
    key: "issues_ms",
    title: "Updated the issue log",
    detail: "Opened, reopened and verified-resolved issues against what this run found.",
  },
];

/** The counts an operator reads first, with the meaning rather than the field name. */
const HEADLINE_COUNTS: readonly { key: string; label: string; hint: string }[] = [
  {
    key: "staged_records",
    label: "Records normalized",
    hint: "read from the imported source rows",
  },
  { key: "findings", label: "Findings raised", hint: "each one became an issue to work" },
  {
    key: "reconciliation_discrepancies",
    label: "Reconciliation discrepancies",
    hint: "lines that did not tie to their control",
  },
  {
    key: "entity_candidates",
    label: "Entity candidates",
    hint: "possible duplicate parties to decide",
  },
];

const ISSUE_COUNTS: readonly { key: string; label: string }[] = [
  { key: "issues_created", label: "Issues opened" },
  { key: "issues_reopened", label: "Issues reopened" },
  { key: "issues_verified_resolved", label: "Issues verified resolved" },
];

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];

/** `findings_by_severity` is an open object; show only its numeric entries, worst first. */
function severities(counts: { [key: string]: unknown }): readonly [string, number][] {
  const raw = counts["findings_by_severity"];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return [];
  }
  const entries = Object.entries(raw).flatMap(([severity, value]): [string, number][] =>
    typeof value === "number" ? [[severity, value]] : [],
  );
  return entries.sort(([a], [b]) => {
    const left = SEVERITY_ORDER.indexOf(a);
    const right = SEVERITY_ORDER.indexOf(b);
    return (
      (left === -1 ? SEVERITY_ORDER.length : left) - (right === -1 ? SEVERITY_ORDER.length : right)
    );
  });
}

function KeyValueTable({
  caption,
  label,
  rows,
}: {
  caption: string;
  label: string;
  rows: readonly (readonly [string, unknown])[];
}) {
  if (rows.length === 0) {
    return <EmptyState title={`No ${caption.toLowerCase()} recorded`} />;
  }
  return (
    <Panel className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
            <th scope="col" className="px-3 py-1.5 font-medium">
              {label}
            </th>
            <th scope="col" className="px-3 py-1.5 text-right font-medium">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key} className="border-b border-[var(--border)]/60 last:border-0">
              <th scope="row" className="px-3 py-1.5 text-left font-normal text-[var(--ink-muted)]">
                {humanize(key)}
              </th>
              <td className="px-3 py-1.5 text-right tabular-nums">{text(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/** A before → after list for gates or reconciliations, each side shown as its own status. */
function StatusChanges({
  caption,
  label,
  changes,
}: {
  caption: string;
  label: string;
  changes: readonly Schemas["StatusChangeOut"][];
}) {
  return (
    <Panel className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="border-b border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
          {caption} <span className="tabular-nums">({changes.length})</span>
        </caption>
        <thead>
          <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
            <th scope="col" className="px-3 py-1.5 font-medium">
              {label}
            </th>
            <th scope="col" className="px-3 py-1.5 font-medium">
              Before
            </th>
            <th scope="col" className="px-3 py-1.5 font-medium">
              After
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.length === 0 ? (
            <tr>
              <td colSpan={3} className="px-3 py-2 text-[var(--ink-subtle)]">
                No change.
              </td>
            </tr>
          ) : (
            changes.map((change) => (
              <tr key={change.key} className="border-b border-[var(--border)]/60 last:border-0">
                <th scope="row" className="px-3 py-1.5 text-left font-medium">
                  {change.key}
                </th>
                <td className="px-3 py-1.5">
                  {change.before ? (
                    <StatusChip status={change.before} />
                  ) : (
                    <span className="text-xs text-[var(--ink-subtle)]">not evaluated</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  {change.after ? (
                    <StatusChip status={change.after} />
                  ) : (
                    <span className="text-xs text-[var(--ink-subtle)]">not evaluated</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function FindingList({
  caption,
  hint,
  findings,
  tone,
}: {
  caption: string;
  hint: string;
  findings: readonly Schemas["FindingChangeOut"][];
  tone: "critical" | "positive";
}) {
  return (
    <Panel>
      <p
        className={`border-b border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-1.5 text-xs font-semibold uppercase tracking-wide ${
          findings.length === 0
            ? "text-[var(--ink-muted)]"
            : tone === "critical"
              ? "text-[var(--critical)]"
              : "text-[var(--positive)]"
        }`}
      >
        {caption} <span className="tabular-nums">({findings.length})</span>
      </p>
      <p className="border-b border-[var(--border)]/60 px-3 py-1.5 text-xs text-[var(--ink-subtle)]">
        {hint}
      </p>
      {findings.length === 0 ? (
        <p className="px-3 py-2 text-sm text-[var(--ink-subtle)]">None.</p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {findings.map((finding) => (
            <li key={finding.fingerprint} className="px-3 py-2 text-sm">
              <p className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium text-[var(--ink)]">{finding.rule_id}</span>
                <span
                  className="font-mono text-xs text-[var(--ink-subtle)]"
                  title={finding.fingerprint}
                >
                  {finding.fingerprint.slice(0, 12)}…
                </span>
              </p>
              <p className="text-[var(--ink-muted)]">{finding.message}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default async function RunPage(props: PageProps<"/migrations/[migrationId]/runs/[runId]">) {
  const { migrationId, runId } = await props.params;
  const search = await props.searchParams;
  const [run, runs] = await Promise.all([
    apiGet<Schemas["RunOut"]>(`/api/v1/pipeline-runs/${runId}`),
    apiGet<Schemas["RunOut"][]>(`/api/v1/migrations/${migrationId}/pipeline-runs`),
  ]);
  const compareTo = param(search.compare);
  const diff = compareTo
    ? await apiGet<Schemas["RunDiffOut"]>(`/api/v1/pipeline-runs/${compareTo}/diff/${runId}`)
    : null;
  const others = runs.filter((r) => r.id !== runId && r.status === "succeeded");
  const baseRun = diff ? runs.find((r) => r.id === diff.base_run_id) : undefined;

  const live = run.status === "queued" || run.status === "running";
  const superseded = run.status === "superseded";
  const errorCode = run.error && typeof run.error["code"] === "string" ? run.error["code"] : null;
  const errorDetail =
    run.error && typeof run.error["detail"] === "string" ? run.error["detail"] : null;

  const headline = HEADLINE_COUNTS.flatMap((entry) => {
    const value = stored(run.counts, entry.key);
    return value === null ? [] : [{ ...entry, value }];
  });
  const issueCounts = ISSUE_COUNTS.flatMap((entry) => {
    const value = stored(run.counts, entry.key);
    return value === null ? [] : [{ label: entry.label, value: whole(value) }];
  });
  const bySeverity = severities(run.counts);

  const known = new Set([
    ...HEADLINE_COUNTS.map((entry) => entry.key),
    ...ISSUE_COUNTS.map((entry) => entry.key),
    "findings_by_severity",
  ]);
  const otherCounts = Object.entries(run.counts).filter(([key]) => !known.has(key));

  const totalMs = stored(run.stage_timings, "total_ms");
  const stages = [
    ...STAGES.flatMap((stage) => {
      const value = stored(run.stage_timings, stage.key);
      return value === null ? [] : [{ ...stage, value }];
    }),
    ...Object.entries(run.stage_timings).flatMap(
      (entry): { key: string; title: string; detail: string; value: number }[] => {
        const [key, value] = entry;
        const listed = STAGES.some((stage) => stage.key === key);
        return listed || key === "total_ms" || typeof value !== "number"
          ? []
          : [{ key, title: humanize(key.replace(/_ms$/, "")), detail: "", value }];
      },
    ),
  ];

  /**
   * The comparison: on a run that has one it is the whole point of the page, so it is rendered
   * first. Without one it is an invitation, and sits after what the run itself did.
   */
  const comparison = (
    <Section
      title={diff ? "What changed since the earlier run" : "Compare with another run"}
      description={
        diff
          ? "Relay re-checked the migration after the inputs changed. This is the evidence that a correction did what it claimed — and nothing else."
          : "Put this run beside an earlier one to see what a correction changed: which findings went away, which appeared, and which gates and reconciliations moved."
      }
    >
      {others.length === 0 ? (
        diff ? null : (
          <EmptyState
            title="No other successful runs"
            hint="A comparison needs a second successful run of this migration."
          />
        )
      ) : (
        <div className="mb-3 flex flex-wrap items-baseline gap-2 text-sm">
          <span className="text-[var(--ink-muted)]" id="compare-from">
            Compare with:
          </span>
          <ul aria-labelledby="compare-from" className="flex flex-wrap gap-2">
            {others.map((other) => (
              <li key={other.id}>
                <Link
                  href={buildPath(`/migrations/${migrationId}/runs/${runId}`, {
                    compare: other.id,
                  })}
                  aria-current={other.id === compareTo ? "true" : undefined}
                  className={`rounded border px-2 py-0.5 text-sm no-underline ${
                    other.id === compareTo
                      ? "border-[var(--accent)] bg-[var(--accent-soft)] font-medium text-[var(--accent-ink)]"
                      : "border-[var(--border-strong)] bg-white text-[var(--ink)] hover:bg-[var(--surface-sunken)]"
                  }`}
                >
                  Run #{other.sequence}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {diff ? (
        <div className="space-y-3" data-testid="run-diff">
          <Panel tone="accent" className="p-3">
            <p className="text-sm font-medium text-[var(--ink)]">
              {baseRun ? `Run #${baseRun.sequence}` : "The earlier run"} → Run #{run.sequence}
            </p>
            <p className="mt-0.5 text-sm text-[var(--ink-muted)]">
              What the re-check after the correction found, compared with what stood before it.
            </p>
            <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricCard
                label="Findings resolved"
                value={whole(diff.findings_removed.length)}
                hint="no longer raised"
                tone={diff.findings_removed.length === 0 ? "neutral" : "positive"}
                emphasis
              />
              <MetricCard
                label="Findings added"
                value={whole(diff.findings_added.length)}
                hint="raised for the first time"
                tone={diff.findings_added.length === 0 ? "neutral" : "critical"}
                emphasis
              />
              <MetricCard
                label="Gates changed"
                value={whole(diff.gate_changes.length)}
                hint="readiness gates that moved"
                emphasis
              />
              <MetricCard
                label="Reconciliations changed"
                value={whole(diff.reconciliation_changes.length)}
                hint="controls that moved"
                emphasis
              />
            </dl>
            <div className="mt-3">
              <MetaList
                columns={2}
                items={[
                  {
                    label: "Entity candidates",
                    value: (
                      <span className="tabular-nums">
                        {whole(diff.entity_candidates_before)} →{" "}
                        {whole(diff.entity_candidates_after)}
                      </span>
                    ),
                  },
                  {
                    label: "Inputs that changed",
                    value:
                      diff.changed_fingerprint_components.length === 0 ? (
                        <span className="text-[var(--ink-subtle)]">none</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {diff.changed_fingerprint_components.map((component) => (
                            <span
                              key={component}
                              className="rounded border border-[var(--border-strong)] bg-[var(--surface-sunken)] px-1.5 py-0.5 text-xs"
                            >
                              {humanize(component)}
                            </span>
                          ))}
                        </span>
                      ),
                  },
                ]}
              />
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <StatusChanges
              caption="Readiness gates that changed"
              label="Gate"
              changes={diff.gate_changes}
            />
            <StatusChanges
              caption="Reconciliations that changed"
              label="Reconciliation"
              changes={diff.reconciliation_changes}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <FindingList
              caption="Findings resolved"
              hint="Raised before, and not raised by this run."
              findings={diff.findings_removed}
              tone="positive"
            />
            <FindingList
              caption="Findings added"
              hint="Raised by this run, and not raised before."
              findings={diff.findings_added}
              tone="critical"
            />
          </div>

          <details>
            <summary className="cursor-pointer text-xs text-[var(--ink-subtle)]">Raw diff</summary>
            <pre className="mt-2 overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface-sunken)] p-2 text-xs">
              {JSON.stringify(diff, null, 2)}
            </pre>
          </details>
        </div>
      ) : null}
    </Section>
  );

  return (
    <div className="max-w-5xl">
      <AutoRefresh active={live} />
      <PageHeader
        breadcrumbs={[
          { label: "Runs", href: `/migrations/${migrationId}/runs` },
          { label: `Run #${run.sequence}` },
        ]}
        title={`Run #${run.sequence}`}
        description={
          <>
            {live ? (
              <>
                Relay is re-checking this migration, triggered by {triggeredBy(run.trigger)}.
                Requested <Timestamp value={run.requested_at} />.
              </>
            ) : superseded ? (
              <>
                This run was superseded before it did any work, so it produced no results. It was
                requested <Timestamp value={run.requested_at} /> by {triggeredBy(run.trigger)}.
              </>
            ) : run.status === "failed" ? (
              <>
                This verification did not finish, so it produced no results. It was requested{" "}
                <Timestamp value={run.requested_at} /> by {triggeredBy(run.trigger)}.
              </>
            ) : (
              <>
                Relay verified this migration <Timestamp value={run.finished_at} />, triggered by{" "}
                {triggeredBy(run.trigger)}.
                {run.is_current
                  ? " It was computed from the inputs as they stand now."
                  : " The inputs have changed since; these results describe the migration as it was, not as it is."}
              </>
            )}
          </>
        }
        status={
          run.is_current ? (
            <span className="text-xs font-medium text-[var(--accent-ink)]">(current)</span>
          ) : null
        }
      >
        <span className="flex gap-2">
          <StatusChip status={run.status} />
          {run.is_current ? (
            <StatusChip status="pass" label="current" />
          ) : run.status === "succeeded" ? (
            <StatusChip status="stale" />
          ) : null}
        </span>
      </PageHeader>

      {live ? (
        <div className="mb-5">
          <Callout
            tone="accent"
            title={
              run.status === "queued"
                ? "Queued: waiting for a worker"
                : "Running: Relay is checking the records now"
            }
          >
            {run.status === "queued" ? (
              <p>The run starts as soon as a worker picks it up.</p>
            ) : (
              <p>
                It started <Timestamp value={run.started_at} />.
              </p>
            )}
            <p className="mt-1">
              This page refreshes itself every few seconds; results appear when the run finishes.
              Nothing is estimated in the meantime.
            </p>
          </Callout>
        </div>
      ) : null}

      {run.error ? (
        <div className="mb-5">
          <Callout
            tone={superseded ? "neutral" : "critical"}
            title={
              superseded ? "Superseded: a later run covers these inputs" : "This run did not finish"
            }
          >
            <p>
              {errorDetail ??
                (superseded
                  ? "The inputs changed before this run started."
                  : "The run stopped before it produced results.")}
              {superseded
                ? " That is bookkeeping rather than a failure: no result was ever computed from these inputs, so this run has no counts, timings or findings."
                : " Nothing was recorded from it, and readiness still reflects the last run that finished."}
            </p>
            <p className="mt-1">
              <Link href={`/migrations/${migrationId}/runs`}>Back to the run history</Link>
              {errorCode ? (
                <span className="ml-2 font-mono text-xs text-[var(--ink-subtle)]">{errorCode}</span>
              ) : null}
            </p>
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-[var(--ink-subtle)]">
                Raw error
              </summary>
              <pre className="mt-1 overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface-sunken)] p-2 text-xs">
                {JSON.stringify(run.error, null, 2)}
              </pre>
            </details>
          </Callout>
        </div>
      ) : null}

      {diff ? comparison : null}

      <Section
        title="What this run did"
        description="Everything below is recorded by the run itself. Relay recomputes all of it from the inputs on every run; nobody types these numbers in."
      >
        {headline.length === 0 && issueCounts.length === 0 && bySeverity.length === 0 ? (
          <EmptyState
            title={live ? "No results yet" : "This run recorded no counts"}
            hint={
              live
                ? "Counts appear when the run finishes."
                : "A run records counts only when it completes."
            }
          />
        ) : (
          <>
            {headline.length > 0 ? (
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {headline.map((entry) => (
                  <MetricCard
                    key={entry.key}
                    label={entry.label}
                    value={whole(entry.value)}
                    hint={entry.hint}
                    emphasis
                  />
                ))}
              </dl>
            ) : null}

            {bySeverity.length > 0 ? (
              <Panel className="mt-3 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
                  Findings by severity
                </p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {bySeverity.map(([severity, value]) => (
                    <li key={severity}>
                      <StatusChip
                        status={severity}
                        label={`${whole(value)} ${severity.replaceAll("_", " ")}`}
                      />
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}

            {issueCounts.length > 0 ? (
              <Panel className="mt-3 p-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
                  What it did to the issue log
                </p>
                <MetaList
                  columns={3}
                  items={issueCounts.map((entry) => ({
                    label: entry.label,
                    value: <span className="tabular-nums">{entry.value}</span>,
                  }))}
                />
                <p className="mt-2 text-xs text-[var(--ink-subtle)]">
                  An issue is resolved only when a run stops producing its finding — never by hand.
                </p>
              </Panel>
            ) : null}

            {otherCounts.length > 0 ? (
              <div className="mt-3">
                <KeyValueTable caption="Other counts" label="Count" rows={otherCounts} />
              </div>
            ) : null}
          </>
        )}

        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-[var(--ink-subtle)]">
            Raw counts and timings
          </summary>
          <pre className="mt-2 overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface-sunken)] p-2 text-xs">
            {JSON.stringify({ counts: run.counts, stage_timings_ms: run.stage_timings }, null, 2)}
          </pre>
        </details>
      </Section>

      <Section
        title="Work completed"
        description="The stages of the run, in the order Relay performs them, with how long each one took."
      >
        {stages.length === 0 ? (
          <EmptyState
            title={live ? "No stages completed yet" : "No stage timings recorded"}
            hint={
              live
                ? "Relay is working through the stages; each one is timed when it completes."
                : "Stage timings are recorded only by a run that completes."
            }
          />
        ) : (
          <Panel>
            <ol className="divide-y divide-[var(--border)]">
              {stages.map((stage) => (
                <li
                  key={stage.key}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="text-sm font-medium text-[var(--ink)]">{stage.title}</span>
                    {stage.detail ? (
                      <span className="mt-0.5 block text-xs text-[var(--ink-muted)]">
                        {stage.detail}
                      </span>
                    ) : null}
                  </span>
                  <span className="tabular-nums text-sm text-[var(--ink-muted)]">
                    {whole(stage.value)} ms
                  </span>
                </li>
              ))}
            </ol>
            {totalMs === null ? null : (
              <p className="flex flex-wrap items-baseline justify-between gap-x-4 border-t border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2 text-sm">
                <span className="font-medium text-[var(--ink)]">Total</span>
                <span className="tabular-nums text-[var(--ink-muted)]">{whole(totalMs)} ms</span>
              </p>
            )}
          </Panel>
        )}
      </Section>

      {diff ? null : comparison}

      <Section
        title="Audit identifiers"
        description="The input fingerprint identifies the exact inputs; the result fingerprint identifies what the engine produced from them. Identical inputs must produce an identical result fingerprint — that is how a run can be re-verified rather than trusted."
      >
        <Panel className="p-3">
          <MetaList
            columns={2}
            items={[
              {
                label: "Input fingerprint",
                value: <span className="font-mono text-xs break-all">{run.fingerprint}</span>,
              },
              {
                label: "Result fingerprint",
                value: (
                  <span className="font-mono text-xs break-all">
                    {run.result_fingerprint ?? "—"}
                  </span>
                ),
              },
              { label: "Requested", value: <Timestamp value={run.requested_at} /> },
              { label: "Started", value: <Timestamp value={run.started_at} /> },
              { label: "Finished", value: <Timestamp value={run.finished_at} /> },
              {
                label: "Run id",
                value: <span className="font-mono text-xs break-all">{run.id}</span>,
              },
            ]}
          />
        </Panel>
      </Section>
    </div>
  );
}
