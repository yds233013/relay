import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ApiError, apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeDisposition } from "../../workflow-actions";

export const dynamic = "force-dynamic";

const KINDS = [
  ["carry_forward_adjustment", "Carry-forward adjustment (post a correction in the new ERP)"],
  ["accepted_risk", "Accepted risk"],
  ["false_positive", "False positive"],
  ["not_applicable", "Not applicable"],
] as const;
const OPEN = new Set(["open", "in_progress", "awaiting_verification"]);

export default async function NewDispositionPage(
  props: PageProps<"/migrations/[migrationId]/dispositions/new">,
) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const issueId = param(query.issue) ?? "";
  const issue = await apiGet<Schemas["IssueDetailOut"]>(`/api/v1/issues/${issueId}`);
  const similar = issue.rule_or_recon_id
    ? await apiGet<Schemas["Page_IssueOut_"]>(`/api/v1/migrations/${migrationId}/issues`, {
        rule: issue.rule_or_recon_id,
        limit: 100,
      })
    : { items: [issue], next_cursor: null };
  const candidates = similar.items.filter((i) => OPEN.has(i.status) && i.fingerprint);
  let users: Schemas["UserOut"][] = [];
  try {
    users = await apiGet<Schemas["UserOut"][]>("/api/v1/dev/users");
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) {
      throw error;
    }
  }
  const page = `/migrations/${migrationId}/dispositions/new?issue=${issueId}`;
  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Propose a disposition"
        description={
          <>
            A disposition accepts a finding with a documented decision instead of changing migration
            data. The issue stays visible and leaves the unresolved exposure.{" "}
            <Link href={`/migrations/${migrationId}/issues/${issueId}`} className="underline">
              Back to {issue.key}
            </Link>
          </>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <form action={proposeDisposition}>
        <input type="hidden" name="migrationId" value={migrationId} />
        <input type="hidden" name="returnTo" value={page} />
        <Section title={`Issues (${humanize(issue.rule_or_recon_id ?? issue.source)})`}>
          <div className="overflow-x-auto">
            <table
              className="w-full border-collapse text-left text-sm"
              data-testid="disposition-issues"
            >
              <caption className="sr-only">Open issues with the same rule</caption>
              <thead>
                <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
                  <th scope="col" className="px-2 py-1.5">
                    Include
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Issue
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Severity
                  </th>
                  <th scope="col" className="px-2 py-1.5 text-right">
                    Amount at risk
                  </th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((item) => (
                  <tr key={item.id} className="border-b border-gray-100">
                    <td className="px-2 py-1.5">
                      <input
                        type="checkbox"
                        name="issueId"
                        value={item.id}
                        defaultChecked={item.id === issueId}
                        aria-label={`Include ${item.key}`}
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      {item.key}: {item.title}
                    </td>
                    <td className="px-2 py-1.5">
                      <StatusChip status={item.severity} />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <Money value={item.amount_at_risk} currency={item.currency} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section title="Decision">
          <div className="flex max-w-2xl flex-col gap-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">Kind</span>
              <select name="kind" className="rounded border border-gray-400 bg-white px-2 py-1">
                {KINDS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              name="amount"
              label={`Amount (${issue.currency}; required for carry-forward adjustments)`}
              placeholder="0.00"
            />
            <TextField name="followUp" label="Follow-up" />
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">Follow-up owner</span>
              <select
                name="followUpOwner"
                defaultValue=""
                className="rounded border border-gray-400 bg-white px-2 py-1"
              >
                <option value="">None</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              name="title"
              label="Title"
              required
              defaultValue={`Disposition: ${issue.title}`}
            />
            <TextArea name="justification" label="Justification" required />
            <span>
              <SubmitButton>Propose disposition</SubmitButton>
            </span>
          </div>
        </Section>
      </form>
    </div>
  );
}
