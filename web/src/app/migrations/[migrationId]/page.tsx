import Link from "next/link";

import { BusinessDate, Timestamp } from "@/components/dates";
import { InvestigatePanel } from "@/components/investigate-panel";
import { Money } from "@/components/money";
import { StatusChip } from "@/components/status-chip";
import { Callout, MetricCard, Panel, Section } from "@/components/ui";
import { WorkItemCard } from "@/components/work-item";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";
import { groupGates } from "@/lib/readiness";

export const dynamic = "force-dynamic";

const TOP_WORK = 3;

/** What each nature means for the money. A dollar at risk is not a dollar lost. */
const NATURE: Record<string, { label: string; hint: string }> = {
  migration_defect: {
    label: "Migration defects",
    hint: "Relay or the export is wrong — fix before go-live",
  },
  source_anomaly: {
    label: "Source anomalies",
    hint: "The legacy books are wrong — carry a decision forward",
  },
};

type Step = { label: string; state: "done" | "current" | "todo"; detail: string };

/** The implementation lifecycle, each step decided by run data rather than by a stored status. */
function lifecycle(data: Schemas["OverviewOut"], failing: Set<string>): Step[] {
  const stage = (name: string) => data.stages.find((s) => s.stage === name);
  const done = (name: string) => stage(name)?.status === "complete";
  const openWork = data.work_items.filter((item) => item.kind !== "approval").length;
  return [
    {
      label: "Data imported",
      state: done("import") ? "done" : "current",
      detail: stage("import")?.detail ?? "not started",
    },
    {
      label: "Mapped",
      state: done("map") ? "done" : "todo",
      detail: stage("map")?.detail ?? "not started",
    },
    {
      label: "Checked",
      state: done("validate") ? "done" : "todo",
      detail: stage("validate")?.detail ?? "not started",
    },
    {
      label: "Reconciled",
      state: done("reconcile") ? "done" : "todo",
      detail: stage("reconcile")?.detail ?? "not started",
    },
    {
      label: "Exceptions resolved",
      state: openWork === 0 ? "done" : "current",
      detail: openWork === 0 ? "nothing open" : `${openWork} waiting on a person`,
    },
    {
      label: "Changes approved",
      state: failing.has("G11") ? "current" : "done",
      detail: failing.has("G11") ? "changes still pending" : "no pending changes",
    },
    {
      label: "Signed off",
      state: data.overall === "ready" ? "done" : "todo",
      detail: failing.has("G12") ? "not signed off" : "signed off on this run",
    },
  ];
}

export default async function OverviewPage(props: PageProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const base = `/migrations/${migrationId}`;
  const [data, readiness] = await Promise.all([
    apiGet<Schemas["OverviewOut"]>(`/api/v1/migrations/${migrationId}/overview`),
    apiGet<Schemas["ReadinessOut"]>(`/api/v1/migrations/${migrationId}/readiness`),
  ]);
  const currency = data.currency;
  const migration = data.migration;
  const automation = data.automation;
  const stale = data.overall === "stale";
  const ready = data.overall === "ready";
  const categories = groupGates(readiness.gates);
  const failing = new Set(
    readiness.gates.filter((gate) => gate.status === "fail").map((gate) => gate.gate_id),
  );
  const work = data.work_items;
  const top = work.filter((item) => item.kind !== "approval").slice(0, TOP_WORK);
  const approvals = work.filter((item) => item.kind === "approval");
  const steps = lifecycle(data, failing);

  return (
    <div className="max-w-6xl">
      <h1 className="sr-only">
        {migration.company_name} — {migration.name}
      </h1>

      {/* Can this customer go live? */}
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
              {migration.name} · legacy history{" "}
              <BusinessDate value={migration.history_start_date} /> to cutover{" "}
              <BusinessDate value={migration.cutover_date} /> · target go-live{" "}
              <BusinessDate value={migration.go_live_date} />
            </p>
          </div>
          <div className="text-right">
            {stale ? (
              <>
                <StatusChip status="stale" label="RESULTS STALE" />
                <p className="mt-2 max-w-xs text-sm text-[var(--ink-muted)]">
                  The inputs changed after run #{data.run_sequence}. Re-run the checks to find out
                  where this stands.
                </p>
              </>
            ) : (
              <>
                <p
                  className={`text-2xl font-semibold tracking-tight ${
                    ready ? "text-[var(--positive)]" : "text-[var(--critical)]"
                  }`}
                >
                  <span aria-hidden="true">{ready ? "✓ " : "✕ "}</span>
                  {ready ? "READY FOR GO-LIVE" : "NOT READY FOR GO-LIVE"}
                </p>
                <p className="mt-1 text-sm text-[var(--ink)]">
                  {ready ? (
                    "Every readiness check passes on the current run."
                  ) : (
                    <>
                      <Link href={`${base}/readiness`} data-testid="failing-gates">
                        {data.failing_gate_count} of {data.gate_count} readiness checks
                      </Link>{" "}
                      still need resolution.
                    </>
                  )}
                </p>
                <p className="text-xs text-[var(--ink-subtle)]">
                  verified on{" "}
                  <Link href={`${base}/runs/${data.run_id ?? ""}`}>run #{data.run_sequence}</Link> (
                  {data.run_is_current ? "current" : "stale"})
                </p>
              </>
            )}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 border-t border-[var(--border)] pt-3 sm:grid-cols-3 lg:grid-cols-6">
          {categories.map((category) => (
            <Link
              key={category.id}
              href={`${base}/readiness#${category.id}`}
              title={category.question}
              className={`rounded border px-2 py-1.5 no-underline ${
                category.status === "fail"
                  ? "border-[var(--critical)]/40 bg-[var(--critical-soft)]"
                  : category.status === "waived"
                    ? "border-[var(--accent)]/40 bg-[var(--accent-soft)]"
                    : "border-[var(--positive)]/40 bg-[var(--positive-soft)]"
              }`}
            >
              <span className="flex items-center gap-1 text-xs font-medium text-[var(--ink)]">
                <span
                  aria-hidden="true"
                  className={
                    category.status === "fail"
                      ? "text-[var(--critical)]"
                      : category.status === "waived"
                        ? "text-[var(--accent-ink)]"
                        : "text-[var(--positive)]"
                  }
                >
                  {category.status === "fail" ? "✕" : category.status === "waived" ? "~" : "✓"}
                </span>
                {category.title}
              </span>
              <span className="mt-0.5 block text-[11px] text-[var(--ink-subtle)]">
                {category.status === "fail"
                  ? `${category.failing.length} of ${category.members.length} failing`
                  : "clear"}
              </span>
            </Link>
          ))}
        </div>
      </Panel>

      {/* What should I do next? */}
      <Section
        title="Needs attention"
        description="Findings grouped into the decisions that actually need a person."
        actions={
          <Link href={`${base}/work`} className="font-medium">
            Open the work queue ({work.length}) →
          </Link>
        }
      >
        {work.length === 0 ? (
          <Callout tone="positive">
            Nothing is waiting on a person. Every check either passed or has been resolved.
          </Callout>
        ) : (
          <div className="space-y-3">
            {approvals.slice(0, 1).map((item) => (
              <WorkItemCard key={item.key} item={item} base={base} runId={data.run_id ?? null} />
            ))}
            {top.map((item, index) => (
              <WorkItemCard
                key={item.key}
                item={item}
                base={base}
                runId={data.run_id ?? null}
                emphasis={index === 0 && approvals.length === 0}
              />
            ))}
          </div>
        )}
      </Section>

      {/* How much money is affected? */}
      <Section
        title="Financial exposure"
        description="Money the open findings put in question — counted once, even when several findings name it."
      >
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Unresolved exposure"
            value={<Money value={data.unresolved_exposure} currency={currency} />}
            hint="Every open finding that carries an amount"
            href={`${base}/issues?status=open&order=amount`}
            tone="critical"
            emphasis
          />
          <MetricCard
            label="Open findings"
            value={data.open_issue_count}
            hint="Cleared only when a run stops reporting them"
            href={`${base}/issues?status=open`}
          />
          {data.open_issue_amounts_by_nature.map((entry) => (
            <MetricCard
              key={entry.nature}
              label={NATURE[entry.nature]?.label ?? humanize(entry.nature)}
              value={<Money value={entry.amount} currency={currency} />}
              hint={NATURE[entry.nature]?.hint}
              href={`${base}/issues?status=open&nature=${entry.nature}&order=amount`}
            />
          ))}
        </dl>
      </Section>

      {/* Where is this implementation? */}
      <Section
        title="Implementation progress"
        description="Each step is decided by the latest run, not by anyone ticking a box."
      >
        <Panel className="p-3">
          <ol className="flex flex-wrap items-stretch gap-1">
            {steps.map((step, index) => (
              <li key={step.label} className="flex items-stretch">
                <div
                  className={`w-36 rounded border px-2 py-1.5 ${
                    step.state === "done"
                      ? "border-[var(--positive)]/40 bg-[var(--positive-soft)]"
                      : step.state === "current"
                        ? "border-[var(--critical)]/40 bg-[var(--critical-soft)]"
                        : "border-[var(--border)] bg-[var(--surface-sunken)]"
                  }`}
                >
                  <p className="flex items-center gap-1 text-xs font-medium text-[var(--ink)]">
                    <span
                      aria-hidden="true"
                      className={
                        step.state === "done"
                          ? "text-[var(--positive)]"
                          : step.state === "current"
                            ? "text-[var(--critical)]"
                            : "text-[var(--ink-subtle)]"
                      }
                    >
                      {step.state === "done" ? "✓" : step.state === "current" ? "●" : "○"}
                    </span>
                    {step.label}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-tight text-[var(--ink-muted)]">
                    {step.detail}
                  </p>
                </div>
                {index < steps.length - 1 ? (
                  <span aria-hidden="true" className="self-center px-1 text-[var(--ink-subtle)]">
                    →
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        </Panel>
      </Section>

      {/* What Relay did without being asked. */}
      <Section
        title="What Relay checked automatically"
        description="Every figure here is counted from the last verification run."
        actions={
          <Link href={`${base}/runs/${data.run_id ?? ""}`}>Run #{automation.run_sequence}</Link>
        }
      >
        <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <MetricCard
            label="Records normalized"
            value={(automation.staged_records ?? 0).toLocaleString("en-US")}
            hint="Read from the imported source files"
          />
          <MetricCard
            label="Accounting controls run"
            value={automation.controls_evaluated ?? 0}
            hint={
              automation.controls_errored
                ? `${automation.controls_errored} errored — readiness fails`
                : "None errored"
            }
            href={`${base}/validation`}
          />
          <MetricCard
            label="Reconciliations performed"
            value={automation.reconciliations_performed ?? 0}
            hint={`${automation.reconciliations_with_differences ?? 0} with differences`}
            href={`${base}/reconciliation`}
          />
          <MetricCard
            label="Findings raised"
            value={automation.findings ?? 0}
            hint={`Grouped into ${work.length} decision${work.length === 1 ? "" : "s"}`}
            href={`${base}/work`}
          />
        </dl>
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Assigned to you">
          {data.my_issues.length === 0 && data.my_approvals.length === 0 ? (
            <Callout>
              Nothing is assigned to you and no approval is waiting on your role. Switch user to act
              as the implementation lead or the customer controller.
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

        <Section
          title="Recent activity"
          actions={<Link href={`${base}/audit`}>Full audit trail</Link>}
        >
          <Panel className="divide-y divide-[var(--border)]">
            {data.recent_activity.slice(0, 8).map((event) => (
              <p key={event.id} className="flex items-baseline gap-3 px-3 py-1.5 text-sm">
                <span className="w-40 shrink-0 text-xs text-[var(--ink-subtle)]">
                  <Timestamp value={event.occurred_at} />
                </span>
                <span className="text-[var(--ink)]">{humanize(event.action)}</span>
                <span className="text-xs text-[var(--ink-subtle)]">{event.actor_type}</span>
              </p>
            ))}
          </Panel>
        </Section>
      </div>

      <InvestigatePanel migrationId={migrationId} returnTo={base} />
    </div>
  );
}
