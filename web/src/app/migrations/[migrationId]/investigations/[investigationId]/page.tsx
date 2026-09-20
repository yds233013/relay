import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { FindingCard, Transcript } from "@/components/ai-finding";
import { AutoRefresh } from "@/components/auto-refresh";
import { Timestamp } from "@/components/dates";
import { SubmitButton, TextField } from "@/components/forms";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { StatusChip } from "@/components/status-chip";
import { Callout, MetaList, PageHeader, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { isPublicDemo } from "@/lib/demo";
import { humanize, param } from "@/lib/format";

import { draftFromFinding, reviewFinding } from "../../ai-actions";

export const dynamic = "force-dynamic";

/**
 * One investigation, presented as a case file rather than a chat log.
 *
 * The page keeps three kinds of statement apart, because conflating them is how an assistant
 * becomes untrustworthy: what the deterministic checks *found* (fact, computed by the engine),
 * what the investigator *thinks* caused it (inference, from a model or a scripted transcript), and
 * what it *proposes* (a suggestion that only a person can act on). Provenance is stated for each.
 */
const PROVIDER_NOTE: Record<string, { title: string; body: string; tone: "accent" | "warning" }> = {
  demo: {
    title: "Scripted demonstration — not a model",
    body:
      "This investigation replayed an authored transcript. The tools below really ran against " +
      "this migration, so every piece of evidence is genuine, but the reasoning was written in " +
      "advance rather than produced by a model.",
    tone: "warning",
  },
  scripted: {
    title: "Scripted transcript — not a model",
    body:
      "Replayed from a fixed transcript used for testing. The evidence is real; the reasoning " +
      "is not a model's.",
    tone: "warning",
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

  return (
    <div className="max-w-5xl">
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

      {/* 1. The deterministic finding: computed, not inferred. */}
      {issue ? (
        <Section
          title="What Relay's checks found"
          description="Produced by the deterministic engine. This part is not an opinion."
        >
          <Panel className="p-3">
            <p className="flex flex-wrap items-center gap-2">
              <Link href={`${base}/issues/${issue.id}`} className="font-medium">
                {issue.key}
              </Link>
              <StatusChip status={issue.severity} />
              <StatusChip status={issue.status} />
              <span className="text-[var(--ink)]">{issue.title}</span>
            </p>
            <div className="mt-3">
              <MetaList
                items={[
                  {
                    label: "Amount at risk",
                    value: issue.amount_at_risk ? (
                      <Money value={issue.amount_at_risk} currency={issue.currency} />
                    ) : (
                      "—"
                    ),
                  },
                  { label: "Raised by", value: issue.rule_or_recon_id ?? "—" },
                  { label: "Nature", value: humanize(issue.nature) },
                ]}
              />
            </div>
          </Panel>
        </Section>
      ) : null}

      {/* 2. What the investigator made of it — clearly attributed. */}
      <Section
        title="Relay investigation"
        description="An interpretation of the evidence. Every claim is checked against the tool results it cites."
        actions={
          <span className="text-xs text-[var(--ink-subtle)]">
            {investigation.tool_call_count} tool call
            {investigation.tool_call_count === 1 ? "" : "s"} ·{" "}
            {investigation.provider === "anthropic" ? investigation.model : investigation.provider}
          </span>
        }
      >
        {note ? (
          <div className="mb-3" data-testid="ai-label">
            <Callout tone={note.tone} title={note.title}>
              {note.body}
            </Callout>
          </div>
        ) : (
          <div className="mb-3" data-testid="ai-label">
            <Callout tone="accent" title="Written by a model, checked by Relay">
              A model read this migration with read-only tools. Relay verified that every quoted
              value and record it cites really appears in those tool results. It cannot change
              anything, and its proposal still needs a person and an approval.
            </Callout>
          </div>
        )}

        <p className="mb-3 text-sm text-[var(--ink-muted)]">
          Question asked:{" "}
          <span className="whitespace-pre-wrap text-[var(--ink)]">{investigation.question}</span>
        </p>

        {investigation.error ? (
          <div className="mb-3">
            <Callout tone="critical" title="The investigation did not finish">
              {String(investigation.error.detail ?? "It failed before submitting any finding.")}
            </Callout>
          </div>
        ) : null}

        {detail.findings.length === 0 ? (
          <Panel className="px-3 py-6 text-center text-sm text-[var(--ink-muted)]">
            {running ? "Reading the evidence…" : "No conclusion was submitted."}
          </Panel>
        ) : (
          <div className="space-y-3">
            {detail.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding}>
                {finding.drafted_change_request_id ? (
                  <p className="mt-2 text-sm">
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
                  <div className="mt-3">
                    <DemoUnavailable what="Accepting a proposal, dismissing it, or turning it into a change request is a person's decision, and the change request that follows still needs two approvals and a fresh run before anything moves." />
                  </div>
                ) : null}
                {!isPublicDemo() && finding.review_status === "proposed" ? (
                  <form action={reviewFinding} className="mt-3 flex flex-wrap items-end gap-2">
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
                  <form action={draftFromFinding} className="mt-3">
                    <input type="hidden" name="migrationId" value={migrationId} />
                    <input type="hidden" name="investigationId" value={investigationId} />
                    <input type="hidden" name="findingId" value={finding.id} />
                    <SubmitButton>Draft a change request from this</SubmitButton>
                  </form>
                ) : null}
              </FindingCard>
            ))}
          </div>
        )}
      </Section>

      {/* 3. Who decides. */}
      {!running && detail.findings.length > 0 ? (
        <Section title="What happens next">
          <Callout tone="neutral" title="Relay will not change anything on its own">
            {verified.length > 0
              ? "A person turns a proposal into a change request, someone else approves it, and a " +
                "fresh verification run decides whether it actually fixed the problem."
              : "Nothing here can be turned into a change: a proposal whose evidence did not check " +
                "out is never promoted."}
          </Callout>
        </Section>
      ) : null}

      <Section
        title="Technical record"
        description="Every step, in order, exactly as it happened — for audit rather than reading."
      >
        <details>
          <summary className="cursor-pointer text-sm text-[var(--ink-muted)]">
            Transcript and tool results ({detail.steps.length} steps)
          </summary>
          <div className="mt-2">
            <Transcript steps={detail.steps} />
          </div>
        </details>
        <p className="mt-2 text-xs text-[var(--ink-subtle)]">
          Started <Timestamp value={investigation.created_at} /> · prompt{" "}
          {investigation.prompt_version} ·{" "}
          {investigation.input_tokens + investigation.output_tokens} tokens
        </p>
      </Section>
    </div>
  );
}
