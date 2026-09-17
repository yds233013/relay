import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { InvestigatePanel } from "@/components/investigate-panel";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { ApiError, apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeQuarantineRepair } from "../../governance-actions";
import { addIssueComment, updateIssue } from "../../workflow-actions";

const OPEN = new Set(["open", "in_progress", "awaiting_verification"]);

async function people(): Promise<Schemas["UserOut"][]> {
  try {
    return await apiGet<Schemas["UserOut"][]>("/api/v1/dev/users");
  } catch (error) {
    // The user directory is a development facility; without it owners show as ids.
    if (error instanceof ApiError && error.status === 404) {
      return [];
    }
    throw error;
  }
}

export const dynamic = "force-dynamic";

export default async function IssuePage(
  props: PageProps<"/migrations/[migrationId]/issues/[issueId]">,
) {
  const { migrationId, issueId } = await props.params;
  const query = await props.searchParams;
  const [issue, comments, links, history, users] = await Promise.all([
    apiGet<Schemas["IssueDetailOut"]>(`/api/v1/issues/${issueId}`),
    apiGet<Schemas["CommentOut"][]>(`/api/v1/issues/${issueId}/comments`),
    apiGet<Schemas["IssueLinkOut"][]>(`/api/v1/issues/${issueId}/links`),
    apiGet<Schemas["AuditEventOut"][]>(`/api/v1/issues/${issueId}/history`),
    people(),
  ]);
  const ownerName = (userId: string | null) =>
    userId ? (users.find((u) => u.id === userId)?.display_name ?? userId) : "unassigned";
  const statusOptions =
    issue.source === "manual"
      ? ["open", "in_progress", "closed"]
      : issue.status === "open" || issue.status === "in_progress"
        ? ["open", "in_progress"]
        : [];
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
      <Section title="Workflow">
        <p className="mb-2 text-sm">
          Owner: <span data-testid="issue-owner">{ownerName(issue.owner_user_id)}</span>. Issues
          become resolved only when a current run no longer reports them.
        </p>
        <form action={updateIssue} className="flex flex-wrap items-end gap-3">
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="issueId" value={issue.id} />
          <input type="hidden" name="version" value={issue.version} />
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-gray-700">Owner</span>
            <select
              name="owner"
              defaultValue={issue.owner_user_id ?? "none"}
              className="rounded border border-gray-400 bg-white px-2 py-1"
            >
              <option value="none">Unassigned</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name} ({humanize(user.role)})
                </option>
              ))}
            </select>
          </label>
          {statusOptions.length > 0 ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">Status</span>
              <select
                name="status"
                defaultValue={issue.status}
                className="rounded border border-gray-400 bg-white px-2 py-1"
              >
                {statusOptions.map((option) => (
                  <option key={option} value={option}>
                    {humanize(option)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <TextField name="note" label="Note (optional)" />
          <SubmitButton tone="secondary">Save</SubmitButton>
        </form>
        {issue.fingerprint && OPEN.has(issue.status) ? (
          <p className="mt-3 flex flex-wrap gap-4 text-sm">
            <Link
              href={`/migrations/${migrationId}/dispositions/new?issue=${issue.id}`}
              className="underline"
            >
              Propose a disposition
            </Link>
            {issue.rule_or_recon_id?.startsWith("PARTY.") ? (
              <Link href={`/migrations/${migrationId}/entities`} className="underline">
                Review entity candidates
              </Link>
            ) : null}
          </p>
        ) : null}
      </Section>
      {exception && exception.rule_id === "NORM.MALFORMED_ROW" && issue.status !== "resolved" ? (
        <Section title="Propose a row repair">
          <p className="mb-2 text-sm text-gray-700">
            Rewrite the unreadable text as one CSV record with the file&apos;s columns. The original
            text stays in the import; the repair applies only after approval.
          </p>
          <form action={proposeQuarantineRepair} className="flex max-w-3xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="exceptionId" value={exception.id} />
            <input type="hidden" name="evidenceIssueId" value={issue.id} />
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
      <InvestigatePanel
        migrationId={migrationId}
        issueId={issue.id}
        returnTo={`/migrations/${migrationId}/issues/${issueId}`}
        defaultQuestion={`Why does ${issue.key} occur, and what should we do about it?`}
      />
      <Section title="Related issues">
        {links.length === 0 ? (
          <p className="text-sm text-gray-700">No linked issues.</p>
        ) : (
          <ul className="list-inside list-disc text-sm" data-testid="issue-links">
            {links.map((link) => (
              <li key={link.id}>
                {humanize(link.link_type)}:{" "}
                <Link
                  href={`/migrations/${migrationId}/issues/${link.other_issue_id}`}
                  className="underline"
                >
                  {link.other_issue_key} {link.other_issue_title}
                </Link>{" "}
                <StatusChip status={link.other_issue_status} />{" "}
                <span className="text-xs text-gray-700">({link.reason})</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Comments">
        <ol className="mb-3 space-y-2 text-sm" data-testid="comments">
          {comments.map((comment) => (
            <li key={comment.id} className="rounded border border-gray-200 p-2">
              <p className="text-xs text-gray-700">
                {comment.author_name} · <LocalTime value={comment.created_at} />
              </p>
              <p className="whitespace-pre-wrap">{comment.body}</p>
            </li>
          ))}
        </ol>
        <form action={addIssueComment} className="flex max-w-2xl flex-col gap-2">
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="issueId" value={issue.id} />
          <TextArea name="body" label="Add a comment" required rows={3} />
          <span>
            <SubmitButton tone="secondary">Comment</SubmitButton>
          </span>
        </form>
      </Section>
      <Section title="History">
        <ol className="space-y-1 text-sm" data-testid="issue-history">
          {history.map((event) => (
            <li key={event.id}>
              <LocalTime value={event.occurred_at} /> {humanize(event.action)}
              {event.after && "status" in event.after ? ` → ${String(event.after.status)}` : ""}
              {event.reason ? ` — ${event.reason}` : ""}
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}
