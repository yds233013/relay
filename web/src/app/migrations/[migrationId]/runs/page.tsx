import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { Timestamp } from "@/components/dates";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ButtonLink, Callout, EmptyState, MetricCard, Panel, Section } from "@/components/ui";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Counts arrive as an open JSON object. Only a key the run actually recorded is shown: a number
 * that is not in the payload is not displayed, and never stood in for by a computed one.
 */
function count(counts: { [key: string]: unknown }, key: string): number | null {
  const value = counts[key];
  return typeof value === "number" ? value : null;
}

/** Whole counts, grouped for reading. No money is ever formatted this way (FC-15). */
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

function sentence(phrase: string): string {
  return phrase.charAt(0).toUpperCase() + phrase.slice(1);
}

export default async function RunsPage(props: PageProps<"/migrations/[migrationId]/runs">) {
  const { migrationId } = await props.params;
  const runs = await apiGet<Schemas["RunOut"][]>(`/api/v1/migrations/${migrationId}/pipeline-runs`);
  const current = runs.find((run) => run.is_current);
  const live = runs.some((run) => run.status === "queued" || run.status === "running");

  /**
   * The run each row can be compared against: the nearest earlier run that produced results.
   * The list arrives newest first, so the candidates for a row are the rows after it.
   */
  const previousWithResults = (index: number): Schemas["RunOut"] | undefined =>
    runs.slice(index + 1).find((run) => run.status === "succeeded");

  const currentCounts = current
    ? [
        { label: "Records normalized", key: "staged_records" },
        { label: "Findings raised", key: "findings" },
        { label: "Reconciliation discrepancies", key: "reconciliation_discrepancies" },
        { label: "Entity candidates", key: "entity_candidates" },
      ].flatMap(({ label, key }) => {
        const value = count(current.counts, key);
        return value === null ? [] : [{ label, value }];
      })
    : [];

  return (
    <div className="max-w-6xl">
      <AutoRefresh active={live} />
      <PageHeader
        title="Verification runs"
        description="Every time the inputs change, Relay re-checks this migration from scratch: it normalizes the imported records, evaluates every control, performs the reconciliations and raises what fails. A run is a deterministic function of its inputs, so the same inputs always produce the same findings, gates and reconciliations — and older runs stay readable as evidence of what was true at the time."
      />

      {live ? (
        <div className="mb-5">
          <Callout tone="accent" title="A verification run is in progress">
            Relay is re-checking this migration now. This page refreshes itself every few seconds.
          </Callout>
        </div>
      ) : null}

      {current ? (
        <Section
          title="Latest verification"
          description="What Relay found when it last checked this migration against the inputs as they stand now."
          actions={
            <ButtonLink href={`/migrations/${migrationId}/runs/${current.id}`}>
              Open Run #{current.sequence}
            </ButtonLink>
          }
        >
          <Panel tone="accent" className="p-3">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <Link
                href={`/migrations/${migrationId}/runs/${current.id}`}
                className="font-medium tabular-nums"
              >
                Run #{current.sequence}
              </Link>
              <span className="text-xs font-medium text-[var(--accent-ink)]">(current)</span>
              <StatusChip status={current.status} />
              <span className="text-[var(--ink-muted)]">
                Triggered by {triggeredBy(current.trigger)} ·{" "}
                {current.finished_at ? (
                  <>
                    completed <Timestamp value={current.finished_at} />
                  </>
                ) : (
                  <>
                    requested <Timestamp value={current.requested_at} />
                  </>
                )}
              </span>
            </p>
            {currentCounts.length > 0 ? (
              <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {currentCounts.map((item) => (
                  <MetricCard
                    key={item.label}
                    label={item.label}
                    value={whole(item.value)}
                    tone="neutral"
                  />
                ))}
              </dl>
            ) : null}
          </Panel>
        </Section>
      ) : null}

      <Section
        title="Run history"
        description={
          current
            ? `Run #${current.sequence} is current: it was computed from the inputs as they stand now. Every other run describes inputs that have since changed, and is kept as evidence rather than as an answer about today.`
            : "No run matches the current inputs. Request a run to evaluate them."
        }
      >
        {runs.length === 0 ? (
          <EmptyState
            title="No runs yet"
            hint="Request a run from Setup or from a dataset once its export is imported and its column mapping approved."
          />
        ) : (
          <>
            <Panel className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">{runs.length} verification runs, newest first</caption>
                <thead>
                  <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Run
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Result
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Findings raised
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Records normalized
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Triggered by
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Requested
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Compare
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, index) => {
                    const findings = count(run.counts, "findings");
                    const records = count(run.counts, "staged_records");
                    const previous = previousWithResults(index);
                    const comparable = run.status === "succeeded" && previous !== undefined;
                    return (
                      <tr
                        key={run.id}
                        className={`border-b border-[var(--border)]/60 last:border-0 ${
                          run.is_current
                            ? "bg-[var(--accent-soft)] shadow-[inset_3px_0_0_var(--accent)]"
                            : "hover:bg-[var(--surface-sunken)]"
                        }`}
                      >
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          <span className="flex flex-wrap items-baseline gap-1.5 whitespace-nowrap">
                            <Link
                              href={`/migrations/${migrationId}/runs/${run.id}`}
                              className="font-medium tabular-nums"
                            >
                              Run #{run.sequence}
                            </Link>
                            {run.is_current ? (
                              <span className="text-xs font-medium text-[var(--accent-ink)]">
                                (current)
                              </span>
                            ) : null}
                          </span>
                          <span
                            className="mt-0.5 block font-mono text-[10px] font-normal text-[var(--ink-subtle)]"
                            title={`Input fingerprint ${run.fingerprint}`}
                          >
                            {run.fingerprint.slice(0, 12)}…
                          </span>
                        </th>
                        <td className="px-3 py-2">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <StatusChip status={run.status} />
                            {run.is_current ? (
                              <StatusChip status="pass" label="current" />
                            ) : run.status === "succeeded" ? (
                              <StatusChip status="stale" label="stale" />
                            ) : null}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {findings === null ? (
                            <span className="text-[var(--ink-subtle)]">—</span>
                          ) : (
                            whole(findings)
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {records === null ? (
                            <span className="text-[var(--ink-subtle)]">—</span>
                          ) : (
                            whole(records)
                          )}
                        </td>
                        <td className="px-3 py-2 text-[var(--ink-muted)]">
                          {sentence(triggeredBy(run.trigger))}
                        </td>
                        <td className="px-3 py-2 text-[var(--ink-muted)]">
                          <Timestamp value={run.requested_at} />
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {comparable && previous ? (
                            <Link
                              href={buildPath(`/migrations/${migrationId}/runs/${run.id}`, {
                                compare: previous.id,
                              })}
                              className="tabular-nums"
                              aria-label={`Compare Run #${run.sequence} with Run #${previous.sequence}`}
                            >
                              vs Run #{previous.sequence}
                            </Link>
                          ) : (
                            <span className="text-[var(--ink-subtle)]">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
            <div className="mt-3">
              <Callout title="Reading this history">
                A <strong>succeeded</strong> run produced results, and the one marked{" "}
                <strong>(current)</strong> was computed from today&rsquo;s inputs. A{" "}
                <strong>superseded</strong> run never produced results: the inputs changed again
                before it started, so a later run covers them — that is bookkeeping, not a failure.
                A <strong>stale</strong> run did produce results, but they describe inputs that have
                since changed. <strong>Compare</strong> re-reads an earlier run beside this one, so
                a correction can be checked against what it was supposed to change.
              </Callout>
            </div>
          </>
        )}
      </Section>
    </div>
  );
}
