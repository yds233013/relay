import Link from "next/link";

import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function IssuePage(
  props: PageProps<"/migrations/[migrationId]/issues/[issueId]">,
) {
  const { migrationId, issueId } = await props.params;
  const issue = await apiGet<Schemas["IssueDetailOut"]>(`/api/v1/issues/${issueId}`);
  const exception = issue.latest_exception;
  const runId = issue.last_seen_run_id;
  return (
    <div className="max-w-5xl">
      <PageHeader
        title={`${issue.key}: ${issue.title}`}
        description={`${issue.source} · ${issue.category} · ${issue.nature.replace("_", " ")}`}
      >
        <span className="flex gap-2">
          <StatusChip status={issue.severity} />
          <StatusChip status={issue.status} />
        </span>
      </PageHeader>
      <dl className="mb-4 grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
        <div>
          <dt className="text-xs text-gray-700">Amount at risk</dt>
          <dd>
            <Money value={issue.amount_at_risk} currency={issue.currency} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-gray-700">Rule or reconciliation</dt>
          <dd className="font-mono text-xs">{issue.rule_or_recon_id}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-700">Last seen</dt>
          <dd>
            {runId ? (
              <Link href={`/migrations/${migrationId}/runs/${runId}`} className="underline">
                run
              </Link>
            ) : (
              "—"
            )}
          </dd>
        </div>
      </dl>
      <Section title="Subjects">
        <ul className="list-inside list-disc text-sm">
          {issue.subjects.map((subject) => (
            <li key={subject}>
              {runId && !subject.startsWith("recon:") && !subject.startsWith("quarantine:") ? (
                <RecordRef migrationId={migrationId} runId={runId} naturalKey={subject} />
              ) : (
                <span className="font-mono text-xs">{subject}</span>
              )}
            </li>
          ))}
        </ul>
      </Section>
      {exception ? (
        <Section title="Latest finding">
          <p className="mb-2 text-sm">{exception.message}</p>
          {exception.expected !== null || exception.observed !== null ? (
            <p className="mb-2 text-sm">
              Expected <code>{JSON.stringify(exception.expected)}</code>, observed{" "}
              <code>{JSON.stringify(exception.observed)}</code>
            </p>
          ) : null}
          {exception.lineage.length > 0 ? (
            <ul className="list-inside list-disc text-sm">
              {exception.lineage.map((lineage) => (
                <li key={`${lineage.import_id}-${lineage.line_start}`}>
                  <SourceLocation migrationId={migrationId} lineage={lineage} />
                </li>
              ))}
            </ul>
          ) : null}
          <pre className="mt-2 overflow-x-auto rounded bg-gray-50 p-2 text-xs">
            {JSON.stringify(exception.details, null, 2)}
          </pre>
        </Section>
      ) : null}
    </div>
  );
}
