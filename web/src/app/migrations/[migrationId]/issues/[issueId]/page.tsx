import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

import { proposeQuarantineRepair } from "../../governance-actions";

export const dynamic = "force-dynamic";

export default async function IssuePage(
  props: PageProps<"/migrations/[migrationId]/issues/[issueId]">,
) {
  const { migrationId, issueId } = await props.params;
  const query = await props.searchParams;
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
      <Notice error={param(query.error)} notice={param(query.notice)} />
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
      {exception && exception.rule_id === "NORM.MALFORMED_ROW" && issue.status !== "resolved" ? (
        <Section title="Propose a row repair">
          <p className="mb-2 text-sm text-gray-700">
            Rewrite the unreadable text as one CSV record with the file&apos;s columns. The original
            text stays in the import; the repair applies only after approval.
          </p>
          <form action={proposeQuarantineRepair} className="flex max-w-3xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="exceptionId" value={exception.id} />
            <input
              type="hidden"
              name="returnTo"
              value={`/migrations/${migrationId}/issues/${issueId}`}
            />
            <TextArea
              name="replacementText"
              label="Replacement record"
              defaultValue={String(exception.details.raw_text ?? "")}
              rows={4}
              mono
              required
            />
            <TextArea name="justification" label="Justification" required />
            <span>
              <SubmitButton>Propose repair</SubmitButton>
            </span>
          </form>
        </Section>
      ) : null}
    </div>
  );
}
