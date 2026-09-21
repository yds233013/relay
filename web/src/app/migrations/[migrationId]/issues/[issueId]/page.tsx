import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { DemoUnavailable } from "@/components/demo-note";
import { InvestigatePanel } from "@/components/investigate-panel";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import {
  ButtonLink,
  Callout,
  EmptyState,
  MetaList,
  PageHeader,
  Panel,
  ProvenanceBadge,
  Section,
} from "@/components/ui";
import { ApiError, apiGet, type Schemas } from "@/lib/api/client";
import { isPublicDemo } from "@/lib/demo";
import { humanize, param, splitTitle } from "@/lib/format";

import { proposeQuarantineRepair } from "../../governance-actions";
import { addIssueComment, updateIssue } from "../../workflow-actions";

const OPEN = new Set(["open", "in_progress", "awaiting_verification"]);

const CONTROL =
  "rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)]";

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
        // The sentence is the heading; the records it names have their own section below, so
        // repeating them in the h1 only pushes the readable part off the end of the line.
        title={`${issue.key}: ${splitTitle(issue.title, issue.subjects).headline}`}
        breadcrumbs={[
          { label: "Issues", href: `/migrations/${migrationId}/issues` },
          { label: issue.key },
        ]}
        status={
          <span className="flex gap-2">
            <StatusChip status={issue.severity} />
            <StatusChip status={issue.status} />
          </span>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      {/* What this issue is, in one strip: nobody should have to read the page to place it. */}
      <Panel className="mb-6 p-3">
        <MetaList
          columns={3}
          items={[
            { label: "Nature", value: issue.nature.replace("_", " ") },
            { label: "Category", value: humanize(issue.category) },
            { label: "Raised by", value: humanize(issue.source) },
            {
              label: "Amount at risk",
              value: (
                <span className="font-medium">
                  <Money value={issue.amount_at_risk} currency={issue.currency} />
                </span>
              ),
            },
            {
              label: "Rule or reconciliation",
              value: <span className="font-mono text-xs">{issue.rule_or_recon_id ?? "—"}</span>,
            },
            {
              label: "Last seen",
              value: runId ? (
                <Link href={`/migrations/${migrationId}/runs/${runId}`}>run</Link>
              ) : (
                <span className="text-[var(--ink-subtle)]">—</span>
              ),
            },
          ]}
        />
      </Panel>

      {/* Evidence. Read-only, quiet, and labelled with where each value came from. */}
      <Section title="Subjects" actions={<ProvenanceBadge kind="canonical" />}>
        <Panel className="p-4">
          <ul className="space-y-1 text-sm">
            {issue.subjects.map((subject) => (
              <li key={subject}>
                {runId && !subject.startsWith("recon:") && !subject.startsWith("quarantine:") ? (
                  <RecordRef migrationId={migrationId} runId={runId} naturalKey={subject} />
                ) : (
                  <span className="font-mono text-xs text-[var(--ink-muted)]">{subject}</span>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      </Section>
      {exception ? (
        <Section title="Latest finding" actions={<ProvenanceBadge kind="derived" />}>
          <Panel className="p-4">
            <p className="text-sm text-[var(--ink)]">{exception.message}</p>
            {exception.expected !== null || exception.observed !== null ? (
              <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                    Expected
                  </dt>
                  <dd className="mt-0.5 font-mono text-xs break-all text-[var(--ink)]">
                    {JSON.stringify(exception.expected)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                    Observed
                  </dt>
                  <dd className="mt-0.5 font-mono text-xs break-all text-[var(--critical)]">
                    {JSON.stringify(exception.observed)}
                  </dd>
                </div>
              </dl>
            ) : null}
            {exception.lineage.length > 0 ? (
              <div className="mt-3 border-t border-[var(--border)] pt-2">
                <p className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                  Source rows <ProvenanceBadge kind="source" />
                </p>
                <ul className="space-y-0.5 text-sm">
                  {exception.lineage.map((lineage) => (
                    <li key={`${lineage.import_id}-${lineage.line_start}`}>
                      <SourceLocation migrationId={migrationId} lineage={lineage} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {/* Most findings carry no extra detail; an empty `{}` box is noise, not evidence. */}
            {Object.keys(exception.details).length > 0 ? (
              <details className="mt-3">
                <summary className="text-xs uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                  Finding detail
                </summary>
                <pre
                  className="mt-1.5 overflow-x-auto rounded-[var(--radius-control)] border border-[var(--border)] bg-[var(--surface-sunken)] p-2.5 text-xs text-[var(--ink-muted)]"
                  tabIndex={0}
                >
                  {JSON.stringify(exception.details, null, 2)}
                </pre>
              </details>
            ) : null}
          </Panel>
        </Section>
      ) : null}

      {/* Acting on the issue. Everything below changes state, and says so. */}
      <Section
        title="Workflow"
        description="Ownership and progress. Issues become resolved only when a current run no longer reports them."
      >
        <Panel className="p-4">
          <p className="mb-3 text-sm text-[var(--ink-muted)]">
            Owner:{" "}
            <span data-testid="issue-owner" className="font-medium text-[var(--ink)]">
              {ownerName(issue.owner_user_id)}
            </span>
          </p>
          {isPublicDemo() ? (
            <DemoUnavailable what="Assigning an owner or moving an issue's status is ordinary operator work here." />
          ) : (
            <form action={updateIssue} className="flex flex-wrap items-end gap-3">
              <input type="hidden" name="migrationId" value={migrationId} />
              <input type="hidden" name="issueId" value={issue.id} />
              <input type="hidden" name="version" value={issue.version} />
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs font-medium text-[var(--ink-muted)]">Owner</span>
                <select
                  name="owner"
                  defaultValue={issue.owner_user_id ?? "none"}
                  className={CONTROL}
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
                  <span className="text-xs font-medium text-[var(--ink-muted)]">Status</span>
                  <select name="status" defaultValue={issue.status} className={CONTROL}>
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
          )}
        </Panel>
        {issue.fingerprint && OPEN.has(issue.status) ? (
          isPublicDemo() ? (
            <div className="mt-3">
              <DemoUnavailable what="A disposition records a decision about a real legacy misstatement — carry it forward, adjust it, or rule it out — as a change request two people approve." />
            </div>
          ) : (
            <Panel tone="accent" className="mt-3 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--accent-ink)]">
                Governed actions
              </p>
              <p className="mt-0.5 text-sm text-[var(--ink-muted)]">
                These start a change request. Nothing takes effect until it is approved.
              </p>
              <span className="mt-2 flex flex-wrap gap-2">
                <ButtonLink
                  href={`/migrations/${migrationId}/dispositions/new?issue=${issue.id}`}
                  variant="primary"
                >
                  Propose a disposition
                </ButtonLink>
                {issue.rule_or_recon_id?.startsWith("PARTY.") ? (
                  <ButtonLink href={`/migrations/${migrationId}/entities`}>
                    Review entity candidates
                  </ButtonLink>
                ) : null}
              </span>
            </Panel>
          )
        ) : null}
      </Section>
      {exception && exception.rule_id === "NORM.MALFORMED_ROW" && issue.status !== "resolved" ? (
        <Section title="Propose a row repair">
          <Panel className="p-4">
            <Callout title="The original text is never overwritten">
              Rewrite the unreadable text as one CSV record with the file&apos;s columns. The
              original text stays in the import; the repair applies only after approval.
            </Callout>
            <form action={proposeQuarantineRepair} className="mt-3 flex max-w-3xl flex-col gap-3">
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
          </Panel>
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
          <EmptyState
            title="No linked issues."
            hint="Links are created when a disposition or decision covers more than one finding."
          />
        ) : (
          <Panel>
            <ul className="divide-y divide-[var(--border)]" data-testid="issue-links">
              {links.map((link) => (
                <li key={link.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="text-xs uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                    {humanize(link.link_type)}
                  </span>
                  <Link
                    href={`/migrations/${migrationId}/issues/${link.other_issue_id}`}
                    className="font-medium"
                  >
                    {link.other_issue_key} {link.other_issue_title}
                  </Link>
                  <StatusChip status={link.other_issue_status} />
                  <span className="text-xs text-[var(--ink-muted)]">({link.reason})</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </Section>
      <Section title="Comments">
        <ol className="mb-3 space-y-2 text-sm" data-testid="comments">
          {comments.map((comment) => (
            <li
              key={comment.id}
              className="rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)] p-3"
            >
              <p className="text-xs text-[var(--ink-subtle)]">
                {comment.author_name} · <LocalTime value={comment.created_at} />
              </p>
              <p className="mt-1 whitespace-pre-wrap text-[var(--ink)]">{comment.body}</p>
            </li>
          ))}
        </ol>
        {isPublicDemo() ? (
          <DemoUnavailable what="Commenting is how the implementation team works an issue between runs." />
        ) : (
          <form action={addIssueComment} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="issueId" value={issue.id} />
            <TextArea name="body" label="Add a comment" required rows={3} />
            <span>
              <SubmitButton tone="secondary">Comment</SubmitButton>
            </span>
          </form>
        )}
      </Section>
      <Section title="History" description="Every governed change to this issue, in order.">
        <Panel>
          <ol className="divide-y divide-[var(--border)]" data-testid="issue-history">
            {history.map((event) => (
              <li
                key={event.id}
                className="flex flex-wrap items-baseline gap-3 px-3 py-1.5 text-sm"
              >
                <span className="text-xs text-[var(--ink-subtle)]">
                  <LocalTime value={event.occurred_at} />
                </span>
                <span className="text-[var(--ink)]">
                  {humanize(event.action)}
                  {event.after && "status" in event.after ? ` → ${String(event.after.status)}` : ""}
                </span>
                {event.reason ? (
                  <span className="text-[var(--ink-muted)]">— {event.reason}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </Panel>
      </Section>
    </div>
  );
}
