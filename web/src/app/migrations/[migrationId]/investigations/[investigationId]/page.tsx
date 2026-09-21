import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { FindingCard, KindLabel, ProcessSteps, Transcript } from "@/components/ai-finding";
import { AutoRefresh } from "@/components/auto-refresh";
import { Timestamp } from "@/components/dates";
import { SubmitButton, TextField } from "@/components/forms";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { StatusChip } from "@/components/status-chip";
import { Callout, PageHeader, Panel, ProvenanceBadge } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { isPublicDemo } from "@/lib/demo";
import { humanize, param, splitTitle } from "@/lib/format";

import { draftFromFinding, reviewFinding } from "../../ai-actions";

export const dynamic = "force-dynamic";

/**
 * One investigation, presented as a case file rather than a chat log.
 *
 * Two panes on a wide screen. The left is the *process*: the deterministic finding the
 * investigation started from, then every read-only tool it called and how long each took. The
 * right is the *assessment*: what the investigator concluded, the evidence Relay re-checked
 * underneath it, what it proposes, and the decision only a person can make.
 *
 * The split is the point. Process is verifiable and boring; assessment is an interpretation that
 * could be wrong. Interleaving them — the way a chat transcript does — is what makes a reader
 * treat a guess as a result, so they never share a column.
 */
const PROVIDER_NOTE: Record<string, { title: string; body: string }> = {
  demo: {
    title: "Scripted demonstration — not a model",
    body:
      "This investigation replayed an authored transcript. The tools below really ran against " +
      "this migration, so every piece of evidence is genuine, but the reasoning was written in " +
      "advance rather than produced by a model.",
  },
  scripted: {
    title: "Scripted transcript — not a model",
    body:
      "Replayed from a fixed transcript used for testing. The evidence is real; the reasoning " +
      "is not a model's.",
  },
};

export default async function InvestigationPage(
  props: PageProps<"/migrations/[migrationId]/investigations/[investigationId]">,
) {
  const { migrationId, investigationId } = await props.params;
  const query = await props.searchParams;
  const base = `/migrations/${migrationId}`;
  const detail = await apiGet<Schemas["InvestigationDetailOut"]>(
    `/api/v1/investigations/${investigationId}`,
  );
  const investigation = detail.investigation;
  const running = investigation.status === "queued" || investigation.status === "running";
  const issue = investigation.issue_id
    ? await apiGet<Schemas["IssueDetailOut"]>(`/api/v1/issues/${investigation.issue_id}`)
    : null;
  const note = PROVIDER_NOTE[investigation.provider];
  const verified = detail.findings.filter((f) => f.verification_status !== "failed");
  const toolCalls = detail.steps.filter((step) => step.tool_name !== null);

  return (
    <div className="max-w-[1280px]">
      <AutoRefresh active={running} />
      <PageHeader
        title="Investigation"
        breadcrumbs={[
          { label: "Work queue", href: `${base}/work` },
          ...(issue ? [{ label: issue.key, href: `${base}/issues/${issue.id}` }] : []),
          { label: "Investigation" },
        ]}
        description={
          running
            ? "Relay is reading the evidence for this finding."
            : "What Relay's checks found, what the investigator makes of it, and what it proposes."
        }
        status={<StatusChip status={investigation.status} label={humanize(investigation.status)} />}
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        {/* ── Left: the process, which is checkable ─────────────────────────────────── */}
        <div className="space-y-4">
          {issue ? (
            <Panel>
              <div className="border-b border-[var(--border)] px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <KindLabel kind="deterministic">Starting facts</KindLabel>
                  <ProvenanceBadge kind="derived" />
                </div>
                <p className="mt-2 text-sm font-semibold leading-snug text-[var(--ink)]">
                  {splitTitle(issue.title, issue.subjects).headline}
                </p>
                {splitTitle(issue.title, issue.subjects).subject ? (
                  <p className="mt-1 font-mono text-[11px] text-[var(--ink-subtle)]">
                    {splitTitle(issue.title, issue.subjects).subject}
                  </p>
                ) : null}
                <p className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Link href={`${base}/issues/${issue.id}`} className="font-mono text-xs">
                    {issue.key}
                  </Link>
                  <StatusChip status={issue.severity} />
                  <StatusChip status={issue.status} />
                </p>
              </div>
              <dl className="divide-y divide-[var(--border)]">
                <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
                  <dt className="text-xs text-[var(--ink-subtle)]">Amount at risk</dt>
                  <dd className="text-sm font-semibold tabular-nums text-[var(--ink)]">
                    {issue.amount_at_risk ? (
                      <Money value={issue.amount_at_risk} currency={issue.currency} />
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
                  <dt className="text-xs text-[var(--ink-subtle)]">Raised by</dt>
                  <dd className="font-mono text-xs text-[var(--ink-muted)]">
                    {issue.rule_or_recon_id ?? "—"}
                  </dd>
                </div>
                <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
                  <dt className="text-xs text-[var(--ink-subtle)]">Nature</dt>
                  <dd className="text-xs text-[var(--ink-muted)]">{humanize(issue.nature)}</dd>
                </div>
              </dl>
            </Panel>
          ) : null}

          <Panel>
            <div className="border-b border-[var(--border)] px-4 py-3">
              <KindLabel kind="deterministic">Investigation process</KindLabel>
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--ink-muted)]">
                {toolCalls.length} tool call{toolCalls.length === 1 ? "" : "s"} against this
                migration. None of them can change its data.
              </p>
            </div>
            <ProcessSteps steps={detail.steps} />
            <div className="border-t border-[var(--border)] px-4 py-3">
              <details>
                <summary className="text-xs text-[var(--ink-muted)]">
                  Full transcript and tool results ({detail.steps.length} steps)
                </summary>
                <div className="mt-2">
                  <Transcript steps={detail.steps} />
                </div>
              </details>
            </div>
          </Panel>

          <Panel className="px-4 py-3">
            <KindLabel kind="deterministic">Provenance</KindLabel>
            <dl className="mt-2 space-y-1.5 text-[11px] text-[var(--ink-subtle)]">
              <div className="flex justify-between gap-3">
                <dt>Source of reasoning</dt>
                <dd className="text-right text-[var(--ink-muted)]">
                  {investigation.provider === "anthropic"
                    ? investigation.model
                    : `${investigation.provider} transcript`}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Prompt version</dt>
                <dd className="font-mono text-[var(--ink-muted)]">
                  {investigation.prompt_version}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Tokens</dt>
                <dd className="tabular-nums text-[var(--ink-muted)]">
                  {investigation.input_tokens + investigation.output_tokens}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Started</dt>
                <dd className="text-[var(--ink-muted)]">
                  <Timestamp value={investigation.created_at} />
                </dd>
              </div>
              {investigation.finished_at ? (
                <div className="flex justify-between gap-3">
                  <dt>Finished</dt>
                  <dd className="text-[var(--ink-muted)]">
                    <Timestamp value={investigation.finished_at} />
                  </dd>
                </div>
              ) : null}
            </dl>
          </Panel>
        </div>

        {/* ── Right: the assessment, which is an interpretation ─────────────────────── */}
        <div className="min-w-0 space-y-4">
          {note ? (
            <div data-testid="ai-label">
              <Callout tone="accent" title={note.title}>
                {note.body}
              </Callout>
            </div>
          ) : (
            <div data-testid="ai-label">
              <Callout tone="accent" title="Written by a model, checked by Relay">
                A model read this migration with read-only tools. Relay verified that every quoted
                value and record it cites really appears in those tool results. It cannot change
                anything, and its proposal still needs a person and an approval.
              </Callout>
            </div>
          )}

          <Panel className="px-4 py-3">
            <KindLabel kind="deterministic">Question asked</KindLabel>
            <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-[var(--ink)]">
              {investigation.question}
            </p>
          </Panel>

          {investigation.error ? (
            <Callout tone="critical" title="The investigation did not finish">
              {String(investigation.error.detail ?? "It failed before submitting any finding.")}
            </Callout>
          ) : null}

          {detail.findings.length === 0 ? (
            <Panel className="px-4 py-10 text-center text-sm text-[var(--ink-muted)]">
              {running ? "Reading the evidence…" : "No conclusion was submitted."}
            </Panel>
          ) : (
            detail.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding}>
                <div className="mt-5 rounded-[var(--radius-control)] border border-dashed border-[var(--border-strong)] bg-[var(--surface-sunken)] p-3.5">
                  <KindLabel kind="decision">Human decision required</KindLabel>
                  {finding.drafted_change_request_id ? (
                    <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-muted)]">
                      A change request was drafted from this:{" "}
                      <Link
                        href={`${base}/change-requests/${finding.drafted_change_request_id}`}
                        className="font-medium"
                      >
                        open it
                      </Link>
                      . It still needs a justification, a submission and two approvals.
                    </p>
                  ) : null}
                  {isPublicDemo() ? (
                    <div className="mt-2">
                      <DemoUnavailable what="Accepting a proposal, dismissing it, or turning it into a change request is a person's decision, and the change request that follows still needs two approvals and a fresh run before anything moves." />
                    </div>
                  ) : null}
                  {!isPublicDemo() && finding.review_status === "proposed" ? (
                    <form action={reviewFinding} className="mt-2 flex flex-wrap items-end gap-2">
                      <input type="hidden" name="migrationId" value={migrationId} />
                      <input type="hidden" name="investigationId" value={investigationId} />
                      <input type="hidden" name="findingId" value={finding.id} />
                      <TextField name="comment" label="Review comment" />
                      {finding.verification_status !== "failed" ? (
                        <SubmitButton tone="secondary" name="decision" value="accept">
                          Accept
                        </SubmitButton>
                      ) : null}
                      <SubmitButton tone="secondary" name="decision" value="dismiss">
                        Dismiss
                      </SubmitButton>
                    </form>
                  ) : null}
                  {!isPublicDemo() && finding.draftable ? (
                    <form action={draftFromFinding} className="mt-2">
                      <input type="hidden" name="migrationId" value={migrationId} />
                      <input type="hidden" name="investigationId" value={investigationId} />
                      <input type="hidden" name="findingId" value={finding.id} />
                      <SubmitButton>Draft a change request from this</SubmitButton>
                    </form>
                  ) : null}
                  {!isPublicDemo() &&
                  finding.review_status !== "proposed" &&
                  !finding.draftable &&
                  !finding.drafted_change_request_id ? (
                    <p className="mt-1.5 text-sm text-[var(--ink-muted)]">
                      This finding has been reviewed. Nothing further is waiting on a person here.
                    </p>
                  ) : null}
                </div>
              </FindingCard>
            ))
          )}

          {!running && detail.findings.length > 0 ? (
            <Callout tone="neutral" title="Relay will not change anything on its own">
              {verified.length > 0
                ? "A person turns a proposal into a change request, someone else approves it, and a " +
                  "fresh verification run decides whether it actually fixed the problem."
                : "Nothing here can be turned into a change: a proposal whose evidence did not check " +
                  "out is never promoted."}
            </Callout>
          ) : null}
        </div>
      </div>
    </div>
  );
}
