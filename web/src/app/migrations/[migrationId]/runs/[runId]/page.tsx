import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

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
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={`Run #${run.sequence}`}
        description={
          <>
            Requested <Timestamp value={run.requested_at} />
          </>
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
        <p className="mb-3 text-sm text-red-900">Error: {JSON.stringify(run.error)}</p>
      ) : null}
      <Section title="Fingerprint">
        <p className="mb-1 font-mono text-xs break-all">{run.fingerprint}</p>
        <p className="text-xs text-gray-700">
          Result fingerprint: <span className="font-mono">{run.result_fingerprint ?? "—"}</span>
        </p>
      </Section>
      <Section title="Counts and timings">
        <pre className="overflow-x-auto rounded bg-gray-50 p-2 text-xs">
          {JSON.stringify({ counts: run.counts, stage_timings_ms: run.stage_timings }, null, 2)}
        </pre>
      </Section>
      <Section title="Compare with another run">
        {others.length === 0 ? (
          <p className="text-sm text-gray-700">No other successful runs.</p>
        ) : (
          <ul className="flex flex-wrap gap-2 text-sm">
            {others.map((other) => (
              <li key={other.id}>
                <Link
                  href={buildPath(`/migrations/${migrationId}/runs/${runId}`, {
                    compare: other.id,
                  })}
                  className="text-blue-800 underline"
                >
                  from #{other.sequence}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {diff ? (
          <div className="mt-3 space-y-2 text-sm" data-testid="run-diff">
            <p>Changed inputs: {diff.changed_fingerprint_components.join(", ") || "none"}</p>
            <p>
              Findings added {diff.findings_added.length}, removed {diff.findings_removed.length};
              entity candidates {diff.entity_candidates_before} → {diff.entity_candidates_after}
            </p>
            <ul className="list-inside list-disc">
              {diff.gate_changes.map((change) => (
                <li key={change.key}>
                  {change.key}: {change.before ?? "—"} → {change.after ?? "—"}
                </li>
              ))}
              {diff.reconciliation_changes.map((change) => (
                <li key={change.key}>
                  {change.key}: {change.before ?? "—"} → {change.after ?? "—"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>
    </div>
  );
}
