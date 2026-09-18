import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { EmptyState, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function RunsPage(props: PageProps<"/migrations/[migrationId]/runs">) {
  const { migrationId } = await props.params;
  const runs = await apiGet<Schemas["RunOut"][]>(`/api/v1/migrations/${migrationId}/pipeline-runs`);
  const current = runs.find((run) => run.is_current);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Runs"
        description="Each run is a deterministic function of its input fingerprint: the same inputs always produce the same findings, gates and reconciliations. Older runs stay readable as evidence."
      />
      <Section
        title="Run history"
        description={
          current
            ? `Run #${current.sequence} is current: it was computed from the inputs as they stand now. Every other run describes inputs that have since changed.`
            : "No run matches the current inputs. Request a run to evaluate them."
        }
      >
        {runs.length === 0 ? (
          <EmptyState
            title="No runs yet"
            hint="Request a run from Setup or from a dataset once its export is imported and its column mapping approved."
          />
        ) : (
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">{runs.length} runs</caption>
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Run
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Against current inputs
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Input fingerprint
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Findings
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Trigger
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Requested
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className={`border-b border-[var(--border)]/60 last:border-0 ${
                      run.is_current
                        ? "bg-[var(--accent-soft)] shadow-[inset_3px_0_0_var(--accent)]"
                        : "hover:bg-[var(--surface-sunken)]"
                    }`}
                  >
                    <th scope="row" className="px-3 py-2 text-left font-normal whitespace-nowrap">
                      <Link
                        href={`/migrations/${migrationId}/runs/${run.id}`}
                        className="font-medium tabular-nums"
                      >
                        Run #{run.sequence}
                      </Link>
                      {run.is_current ? (
                        <span className="ml-1.5 text-xs font-medium text-[var(--accent-ink)]">
                          (current)
                        </span>
                      ) : null}
                    </th>
                    <td className="px-3 py-2">
                      <StatusChip status={run.status} />
                    </td>
                    <td className="px-3 py-2">
                      {run.is_current ? (
                        <StatusChip status="pass" label="current" />
                      ) : (
                        <StatusChip status="stale" label="stale" />
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className="font-mono text-xs text-[var(--ink-muted)]"
                        title={run.fingerprint}
                      >
                        {run.fingerprint.slice(0, 12)}…
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {String(run.counts.findings ?? "—")}
                    </td>
                    <td className="px-3 py-2 text-[var(--ink-muted)]">{humanize(run.trigger)}</td>
                    <td className="px-3 py-2 text-[var(--ink-muted)]">
                      <Timestamp value={run.requested_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>
    </div>
  );
}
