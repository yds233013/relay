import Link from "next/link";

import { BusinessDate, Timestamp } from "@/components/dates";
import { EvidenceLink } from "@/components/evidence-link";
import { GateStrip } from "@/components/gate-strip";
import { InvestigatePanel } from "@/components/investigate-panel";
import { Money } from "@/components/money";
import { StatusChip } from "@/components/status-chip";
import { Callout, MetricCard, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

const STAGE_LINKS: Record<string, string> = {
  import: "/data",
  profile: "/data",
  map: "/data",
  normalize: "/validation",
  validate: "/validation",
  reconcile: "/reconciliation",
};

/** What each nature means for the money. A dollar at risk is not a dollar lost. */
const NATURE_HINT: Record<string, string> = {
  migration_defect: "Relay or the export is wrong — fix before go-live",
  source_anomaly: "The legacy books are wrong — carry forward a decision",
};

/** Where an operator goes to act on a failing gate, rather than merely read about it. */
const GATE_ACTION: Record<string, { label: string; href: string }> = {
  G1: { label: "Review the data", href: "/data" },
  G2: { label: "Review column mappings", href: "/mappings" },
  G3: { label: "Fix the account mapping", href: "/mappings" },
  G4: { label: "Open the run", href: "/runs" },
  G5: { label: "Work the issues", href: "/issues?status=open&order=amount" },
  G6: { label: "Open the reconciliations", href: "/reconciliation" },
  G7: { label: "Open the reconciliations", href: "/reconciliation" },
  G8: { label: "Open cash vs bank", href: "/reconciliation" },
  G9: { label: "Review exposure", href: "/issues?status=open&order=amount" },
  G10: { label: "Decide the duplicates", href: "/entities" },
  G11: { label: "Review approvals", href: "/approvals" },
  G12: { label: "Go to sign-off", href: "/readiness" },
};

export default async function OverviewPage(props: PageProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const base = `/migrations/${migrationId}`;
  const [data, readiness] = await Promise.all([
    apiGet<Schemas["OverviewOut"]>(`/api/v1/migrations/${migrationId}/overview`),
    apiGet<Schemas["ReadinessOut"]>(`/api/v1/migrations/${migrationId}/readiness`),
  ]);
  const currency = data.currency;
  const migration = data.migration;
  const stale = data.overall === "stale";
  const ready = data.overall === "ready";
  const passing = data.gate_count - data.failing_gate_count;

  return (
    <div className="max-w-6xl">
      <h1 className="sr-only">
        {migration.company_name} — {migration.name}
      </h1>

      {/* Identity and readiness: what is being migrated, and whether it can go live. */}
      <Panel
        className={`mb-6 border-l-4 p-4 ${
          stale
            ? "border-l-[var(--warning)]"
            : ready
              ? "border-l-[var(--positive)]"
              : "border-l-[var(--critical)]"
        }`}
      >
        <div
          className="flex flex-wrap items-start justify-between gap-4"
          role="status"
          data-testid="readiness-banner"
        >
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
              {humanize(migration.status)} · books in {migration.functional_currency}
            </p>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-[var(--ink)]">
              {migration.company_name}
            </p>
            <p className="text-sm text-[var(--ink-muted)]">
              {migration.name} · history from <BusinessDate value={migration.history_start_date} />{" "}
              to cutover <BusinessDate value={migration.cutover_date} /> · go-live{" "}
              <BusinessDate value={migration.go_live_date} />
            </p>
          </div>
          <div className="text-right">
            {stale ? (
              <>
                <StatusChip status="stale" label="RESULTS STALE" />
                <p className="mt-2 text-sm text-[var(--ink-muted)]">
                  Inputs changed since{data.run_sequence ? ` Run #${data.run_sequence}` : ""}.
                  Re-run to evaluate.
                </p>
              </>
            ) : (
              <>
                <p
                  className={`text-2xl font-semibold tracking-tight ${ready ? "text-[var(--positive)]" : "text-[var(--critical)]"}`}
                >
                  <span aria-hidden="true">{ready ? "✓ " : "✕ "}</span>
                  {ready ? "READY FOR GO-LIVE" : "NOT READY"}
                </p>
                <p className="mt-1 text-sm">
                  <Link
                    href={`${base}/readiness`}
                    className="font-medium text-[var(--accent-ink)]"
                    data-testid="failing-gates"
                  >
                    {data.failing_gate_count} of {data.gate_count} gates failing
                  </Link>
                  <span className="text-[var(--ink-subtle)]"> · {passing} passing</span>
                </p>
                <p className="text-xs text-[var(--ink-subtle)]">
                  evaluated on{" "}
                  <Link href={`${base}/runs`} className="underline">
                    Run #{data.run_sequence}
                  </Link>{" "}
                  ({data.run_is_current ? "current" : "stale"})
                </p>
              </>
            )}
          </div>
        </div>
        {readiness.gates.length > 0 ? (
          <div className="mt-4 border-t border-[var(--border)] pt-3">
            <GateStrip gates={readiness.gates} base={base} />
          </div>
        ) : null}
      </Panel>

      {/* Money. Exposure is what is unresolved, split by whose problem it is. */}
      <Section
        title="Amount at risk"
        description="Unresolved exposure de-duplicates issues that name the same money."
      >
        <dl className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Unresolved exposure"
            value={<Money value={data.unresolved_exposure} currency={currency} />}
            hint="Every open issue with an amount, counted once"
            href={`${base}/issues?status=open&order=amount`}
            tone="critical"
            emphasis
          />
          <MetricCard
            label="Open issues"
            value={data.open_issue_count}
            hint="Resolved only when a run stops reporting them"
            href={`${base}/issues?status=open`}
          />
          {data.open_issue_amounts_by_nature.map((entry) => (
            <MetricCard
              key={entry.nature}
              label={humanize(entry.nature)}
              value={<Money value={entry.amount} currency={currency} />}
              hint={NATURE_HINT[entry.nature]}
              href={`${base}/issues?status=open&nature=${entry.nature}&order=amount`}
            />
          ))}
        </dl>
        <Panel className="overflow-hidden">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="border-b border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
              Largest open issues
            </caption>
            <thead>
              <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Issue
                </th>
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Severity
                </th>
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Title
                </th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">
                  Amount at risk
                </th>
              </tr>
            </thead>
            <tbody>
              {data.top_issues.map((issue) => (
                <tr key={issue.id} className="border-b border-[var(--border)]/60 last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5 font-medium">
                    <Link href={`${base}/issues/${issue.id}`}>{issue.key}</Link>
                  </td>
                  <td className="px-3 py-1.5">
                    <StatusChip status={issue.severity} />
                  </td>
                  <td className="px-3 py-1.5 text-[var(--ink-muted)]">{issue.title}</td>
                  <td className="px-3 py-1.5 text-right">
                    <Money value={issue.amount_at_risk} currency={currency} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </Section>

      {/* Blockers: one row per failing gate, with the single most useful way in. */}
      <Section
        title="What is blocking go-live"
        description="Every gate states what it observed and links to the evidence behind it."
        actions={
          <Link href={`${base}/readiness`} className="text-[var(--accent-ink)]">
            All gates
          </Link>
        }
      >
        {data.blockers.length === 0 ? (
          <Callout tone="positive">No failing gates on this run.</Callout>
        ) : (
          <ul className="space-y-2" data-testid="blockers">
            {data.blockers.map((blocker) => {
              const action = GATE_ACTION[blocker.gate_id];
              return (
                <li
                  key={blocker.gate_id}
                  className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"
                >
                  <p className="flex flex-wrap items-center gap-2">
                    <StatusChip status="fail" label={blocker.gate_id} />
                    <span className="font-medium text-[var(--ink)]">{blocker.title}</span>
                    <span className="text-sm text-[var(--ink-subtle)]">— {blocker.summary}</span>
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-3">
                    <p className="text-sm">
                      <span className="text-[var(--ink-subtle)]">Observed: </span>
                      <span className="font-medium text-[var(--critical)]">{blocker.observed}</span>
                    </p>
                    {action ? (
                      <Link
                        href={`${base}${action.href}`}
                        className="shrink-0 text-sm font-medium text-[var(--accent-ink)]"
                      >
                        {action.label} →
                      </Link>
                    ) : null}
                  </div>
                  {blocker.evidence.length > 0 ? (
                    <div className="mt-2 border-t border-[var(--border)] pt-2">
                      <p className="mb-1 text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                        Evidence{" "}
                        <span className="tabular-nums">
                          ({blocker.evidence.length} of {blocker.evidence_count})
                        </span>
                      </p>
                      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                        {blocker.evidence.map((link, index) => (
                          <li key={`${blocker.gate_id}-${index}`} className="max-w-full truncate">
                            <EvidenceLink migrationId={migrationId} link={link} />
                          </li>
                        ))}
                        {blocker.evidence_count > blocker.evidence.length ? (
                          <li>
                            <Link
                              href={`${base}/readiness#${blocker.gate_id}`}
                              className="text-[var(--accent-ink)]"
                            >
                              All evidence ({blocker.evidence_count} items)
                            </Link>
                          </li>
                        ) : null}
                      </ul>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section
          title="Waiting for you"
          description="Issues assigned to you and change requests you can approve."
        >
          {data.my_issues.length === 0 && data.my_approvals.length === 0 ? (
            <Callout>
              Nothing assigned to you and no approvals waiting. Switch user to act as the lead or
              the controller.
            </Callout>
          ) : (
            <Panel className="divide-y divide-[var(--border)]">
              {data.my_issues.map((issue) => (
                <p key={issue.id} className="px-3 py-2 text-sm">
                  <Link href={`${base}/issues/${issue.id}`} className="font-medium">
                    {issue.key}
                  </Link>{" "}
                  <span className="text-[var(--ink-muted)]">{issue.title}</span>
                </p>
              ))}
              {data.my_approvals.map((change) => (
                <p key={change.id} className="px-3 py-2 text-sm">
                  <Link href={`${base}/change-requests/${change.id}`} className="font-medium">
                    {change.key}
                  </Link>{" "}
                  <span className="text-[var(--ink-muted)]">{change.title}</span>{" "}
                  <span className="text-xs text-[var(--warning)]">(awaiting your approval)</span>
                </p>
              ))}
            </Panel>
          )}
        </Section>

        <Section title="Pipeline" description="Every stage of the latest run.">
          <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {data.stages.map((stage) => (
              <li key={stage.stage}>
                <Panel className="p-2.5">
                  <p className="flex items-center justify-between gap-2">
                    <Link
                      href={`${base}${STAGE_LINKS[stage.stage] ?? ""}`}
                      className="text-sm font-medium"
                    >
                      {humanize(stage.stage)}
                    </Link>
                    <StatusChip status={stage.status} />
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--ink-muted)]">{stage.detail}</p>
                </Panel>
              </li>
            ))}
          </ol>
        </Section>
      </div>

      <InvestigatePanel migrationId={migrationId} returnTo={base} />

      <Section
        title="Recent activity"
        actions={
          <Link href={`${base}/audit`} className="text-[var(--accent-ink)]">
            Full audit log
          </Link>
        }
      >
        <Panel className="divide-y divide-[var(--border)]">
          {data.recent_activity.map((event) => (
            <p key={event.id} className="flex items-baseline gap-3 px-3 py-1.5 text-sm">
              <span className="w-44 shrink-0 text-xs text-[var(--ink-subtle)]">
                <Timestamp value={event.occurred_at} />
              </span>
              <span className="font-mono text-xs text-[var(--ink)]">{event.action}</span>
              <span className="text-xs text-[var(--ink-subtle)]">{event.actor_type}</span>
            </p>
          ))}
        </Panel>
      </Section>
    </div>
  );
}
