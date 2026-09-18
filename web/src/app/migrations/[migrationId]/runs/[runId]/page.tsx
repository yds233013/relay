import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Callout, EmptyState, MetaList, Panel } from "@/components/ui";
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
          {caption}
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
                    <span className="text-[var(--ink-subtle)]">—</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  {change.after ? (
                    <StatusChip status={change.after} />
                  ) : (
                    <span className="text-[var(--ink-subtle)]">—</span>
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
  findings,
  tone,
}: {
  caption: string;
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
  return (
    <div className="max-w-5xl">
      <PageHeader
        breadcrumbs={[
          { label: "Runs", href: `/migrations/${migrationId}/runs` },
          { label: `Run #${run.sequence}` },
        ]}
        title={`Run #${run.sequence}`}
        description={
          <>
            Requested <Timestamp value={run.requested_at} />, triggered by{" "}
            {run.trigger.replaceAll("_", " ")}.
            {run.is_current
              ? " This run was computed from the inputs as they stand now."
              : " The inputs have changed since this run; its results no longer describe the migration."}
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
          ) : (
            <StatusChip status="stale" />
          )}
        </span>
      </PageHeader>

      {run.error ? (
        <div className="mb-5">
          <Callout tone="critical" title="This run failed">
            <span className="font-mono text-xs break-all">{JSON.stringify(run.error)}</span>
          </Callout>
        </div>
      ) : null}

      <Section
        title="Fingerprint"
        description="The input fingerprint identifies the exact inputs; the result fingerprint identifies what the engine produced from them. Identical inputs must produce an identical result fingerprint."
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
              { label: "Started", value: <Timestamp value={run.started_at} /> },
              { label: "Finished", value: <Timestamp value={run.finished_at} /> },
            ]}
          />
        </Panel>
      </Section>

      <Section
        title="Counts and timings"
        description="What the run produced at each stage, and how long each stage took."
      >
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <KeyValueTable caption="Counts" label="Count" rows={Object.entries(run.counts)} />
          <KeyValueTable
            caption="Stage timings (ms)"
            label="Stage (ms)"
            rows={Object.entries(run.stage_timings)}
          />
        </div>
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
        title="Compare with another run"
        description="What changed between two runs, and which inputs caused it. This is the evidence that a fix did what it claimed and nothing else."
      >
        {others.length === 0 ? (
          <EmptyState
            title="No other successful runs"
            hint="A comparison needs a second successful run of this migration."
          />
        ) : (
          <div className="mb-3 flex flex-wrap items-baseline gap-2 text-sm">
            <span className="text-[var(--ink-muted)]">Compare from:</span>
            <ul className="flex flex-wrap gap-2">
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
            <Panel className="p-3">
              <p className="mb-3 text-sm text-[var(--ink-muted)]">
                {baseRun ? `Run #${baseRun.sequence}` : "The earlier run"} → Run #{run.sequence}
              </p>
              <MetaList
                columns={3}
                items={[
                  {
                    label: "Changed inputs",
                    value:
                      diff.changed_fingerprint_components.length === 0 ? (
                        <span className="text-[var(--ink-subtle)]">none</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {diff.changed_fingerprint_components.map((component) => (
                            <span
                              key={component}
                              className="rounded border border-[var(--border-strong)] bg-[var(--surface-sunken)] px-1.5 py-0.5 font-mono text-xs"
                            >
                              {component}
                            </span>
                          ))}
                        </span>
                      ),
                  },
                  {
                    label: "Findings",
                    value: (
                      <span className="tabular-nums">
                        <span className="text-[var(--critical)]">
                          +{diff.findings_added.length}
                        </span>{" "}
                        added,{" "}
                        <span className="text-[var(--positive)]">
                          -{diff.findings_removed.length}
                        </span>{" "}
                        removed
                      </span>
                    ),
                  },
                  {
                    label: "Entity candidates",
                    value: (
                      <span className="tabular-nums">
                        {diff.entity_candidates_before} → {diff.entity_candidates_after}
                      </span>
                    ),
                  },
                ]}
              />
            </Panel>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <FindingList
                caption="Findings added"
                findings={diff.findings_added}
                tone="critical"
              />
              <FindingList
                caption="Findings removed"
                findings={diff.findings_removed}
                tone="positive"
              />
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <StatusChanges caption="Gate changes" label="Gate" changes={diff.gate_changes} />
              <StatusChanges
                caption="Reconciliation changes"
                label="Reconciliation"
                changes={diff.reconciliation_changes}
              />
            </div>

            <details>
              <summary className="cursor-pointer text-xs text-[var(--ink-subtle)]">
                Raw diff
              </summary>
              <pre className="mt-2 overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface-sunken)] p-2 text-xs">
                {JSON.stringify(diff, null, 2)}
              </pre>
            </details>
          </div>
        ) : null}
      </Section>
    </div>
  );
}
