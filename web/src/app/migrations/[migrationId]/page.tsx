import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { EvidenceLink } from "@/components/evidence-link";
import { InvestigatePanel } from "@/components/investigate-panel";
import { Money } from "@/components/money";
import { Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
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

export default async function OverviewPage(props: PageProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const base = `/migrations/${migrationId}`;
  const data = await apiGet<Schemas["OverviewOut"]>(`/api/v1/migrations/${migrationId}/overview`);
  const currency = data.currency;
  const banner =
    data.overall === "stale" ? (
      <>
        <StatusChip status="stale" label="Results stale" /> inputs changed since the latest run
        {data.run_sequence ? ` (Run #${data.run_sequence})` : ""}
      </>
    ) : (
      <>
        <StatusChip
          status={data.overall}
          label={data.overall === "ready" ? "READY" : "NOT READY"}
        />
        <Link href={`${base}/readiness`} className="underline" data-testid="failing-gates">
          {data.failing_gate_count} of {data.gate_count} gates failing
        </Link>
        <span className="text-gray-700">
          evaluated on Run #{data.run_sequence} ({data.run_is_current ? "current" : "stale"})
        </span>
      </>
    );

  return (
    <div className="max-w-5xl">
      <h1 className="sr-only">Overview</h1>
      <div
        className="mb-4 flex flex-wrap items-center gap-2 rounded border border-gray-300 bg-gray-50 p-3 text-sm"
        role="status"
        data-testid="readiness-banner"
      >
        {banner}
      </div>

      <Section title="Blockers">
        {data.blockers.length === 0 ? (
          <p className="text-sm text-gray-700">No failing gates.</p>
        ) : (
          <ul className="space-y-2" data-testid="blockers">
            {data.blockers.map((blocker) => (
              <li key={blocker.gate_id} className="rounded border border-gray-200 p-2 text-sm">
                <p>
                  <StatusChip status="fail" label={blocker.gate_id} />{" "}
                  <span className="font-medium">{blocker.title}</span>
                  <span className="text-gray-700">: {blocker.observed}</span>
                </p>
                <p className="text-gray-700">{blocker.summary}</p>
                {blocker.evidence.length > 0 ? (
                  <ul className="mt-1 list-inside list-disc">
                    {blocker.evidence.map((link, index) => (
                      <li key={`${blocker.gate_id}-${index}`}>
                        <EvidenceLink migrationId={migrationId} link={link} />
                      </li>
                    ))}
                  </ul>
                ) : null}
                {blocker.evidence_count > blocker.evidence.length ? (
                  <p className="mt-1">
                    <Link
                      href={`${base}/readiness#${blocker.gate_id}`}
                      className="text-blue-800 underline"
                    >
                      All evidence ({blocker.evidence_count} items)
                    </Link>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Amount at risk">
        <dl className="mb-2 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
          <div className="rounded border border-gray-200 p-2">
            <dt className="text-xs text-gray-700">Unresolved exposure (de-duplicated)</dt>
            <dd>
              <Link href={`${base}/issues?status=open&order=amount`} className="underline">
                <Money value={data.unresolved_exposure} currency={currency} />
              </Link>
            </dd>
          </div>
          <div className="rounded border border-gray-200 p-2">
            <dt className="text-xs text-gray-700">Open issues</dt>
            <dd>
              <Link href={`${base}/issues?status=open`} className="underline tabular-nums">
                {data.open_issue_count}
              </Link>
            </dd>
          </div>
          {data.open_issue_amounts_by_nature.map((entry) => (
            <div key={entry.nature} className="rounded border border-gray-200 p-2">
              <dt className="text-xs text-gray-700">
                Open {humanize(entry.nature).toLowerCase()} issue amounts
              </dt>
              <dd>
                <Link
                  href={`${base}/issues?status=open&nature=${entry.nature}&order=amount`}
                  className="underline"
                >
                  <Money value={entry.amount} currency={currency} />
                </Link>
              </dd>
            </div>
          ))}
        </dl>
        <table className="w-full border-collapse text-left text-sm">
          <caption className="mb-1 text-left text-xs font-medium text-gray-700">
            Largest open issues
          </caption>
          <thead>
            <tr className="border-b border-gray-200 text-xs text-gray-700">
              <th scope="col" className="px-2 py-1">
                Issue
              </th>
              <th scope="col" className="px-2 py-1">
                Severity
              </th>
              <th scope="col" className="px-2 py-1">
                Title
              </th>
              <th scope="col" className="px-2 py-1 text-right">
                Amount at risk
              </th>
            </tr>
          </thead>
          <tbody>
            {data.top_issues.map((issue) => (
              <tr key={issue.id} className="border-b border-gray-100">
                <td className="px-2 py-1">
                  <Link href={`${base}/issues/${issue.id}`} className="text-blue-800 underline">
                    {issue.key}
                  </Link>
                </td>
                <td className="px-2 py-1">
                  <StatusChip status={issue.severity} />
                </td>
                <td className="px-2 py-1">{issue.title}</td>
                <td className="px-2 py-1 text-right">
                  <Money value={issue.amount_at_risk} currency={currency} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="My queue">
        {data.my_issues.length === 0 && data.my_approvals.length === 0 ? (
          <p className="text-sm text-gray-700">Nothing assigned to you and no approvals waiting.</p>
        ) : (
          <ul className="list-inside list-disc text-sm">
            {data.my_issues.map((issue) => (
              <li key={issue.id}>
                <Link href={`${base}/issues/${issue.id}`} className="underline">
                  {issue.key}
                </Link>{" "}
                {issue.title}
              </li>
            ))}
            {data.my_approvals.map((change) => (
              <li key={change.id}>
                {change.key} {change.title} (awaiting your approval)
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Pipeline stages">
        <ol className="grid grid-cols-1 gap-2 text-sm md:grid-cols-3">
          {data.stages.map((stage) => (
            <li key={stage.stage} className="rounded border border-gray-200 p-2">
              <p className="flex items-center justify-between">
                <Link
                  href={`${base}${STAGE_LINKS[stage.stage] ?? ""}`}
                  className="font-medium underline"
                >
                  {humanize(stage.stage)}
                </Link>
                <StatusChip status={stage.status} />
              </p>
              <p className="text-gray-700">{stage.detail}</p>
            </li>
          ))}
        </ol>
      </Section>

      <InvestigatePanel migrationId={migrationId} returnTo={base} />
      <Section title="Recent activity">
        <ul className="text-sm">
          {data.recent_activity.map((event) => (
            <li key={event.id} className="flex gap-2 border-b border-gray-100 py-1">
              <Timestamp value={event.occurred_at} />
              <span className="font-mono text-xs">{event.action}</span>
              <span className="text-gray-700">{event.actor_type}</span>
            </li>
          ))}
        </ul>
        <p className="mt-1 text-sm">
          <Link href={`${base}/audit`} className="text-blue-800 underline">
            Full audit log
          </Link>
        </p>
      </Section>
    </div>
  );
}
