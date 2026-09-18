import Link from "next/link";

import { AiLabel, FindingCard, Transcript } from "@/components/ai-finding";
import { AutoRefresh } from "@/components/auto-refresh";
import { SubmitButton, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { draftFromFinding, reviewFinding } from "../../ai-actions";

export const dynamic = "force-dynamic";

export default async function InvestigationPage(
  props: PageProps<"/migrations/[migrationId]/investigations/[investigationId]">,
) {
  const { migrationId, investigationId } = await props.params;
  const query = await props.searchParams;
  const detail = await apiGet<Schemas["InvestigationDetailOut"]>(
    `/api/v1/investigations/${investigationId}`,
  );
  const investigation = detail.investigation;
  const running = investigation.status === "queued" || investigation.status === "running";
  return (
    <div className="max-w-5xl">
      <AutoRefresh active={running} />
      <PageHeader
        title="Investigation"
        description={`${investigation.provider} · ${investigation.model} · ${investigation.prompt_version} · ${investigation.tool_call_count} tool calls · ${investigation.input_tokens + investigation.output_tokens} tokens`}
      >
        <StatusChip status={investigation.status} label={humanize(investigation.status)} />
      </PageHeader>
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <AiLabel />
      <p className="mb-3 text-sm">
        Question: <span className="whitespace-pre-wrap">{investigation.question}</span>
        {investigation.issue_id ? (
          <>
            {" "}
            (
            <Link
              href={`/migrations/${migrationId}/issues/${investigation.issue_id}`}
              className="underline"
            >
              issue
            </Link>
            )
          </>
        ) : null}
      </p>
      {investigation.error ? (
        <p role="alert" className="mb-3 text-sm text-red-900">
          {String(investigation.error.detail ?? "The investigation failed.")}
        </p>
      ) : null}
      <Section title="Findings">
        {detail.findings.length === 0 ? (
          <p className="text-sm text-[var(--ink-muted)]">
            {running ? "Investigating…" : "No findings were submitted."}
          </p>
        ) : (
          <div className="space-y-3">
            {detail.findings.map((finding) => (
              <FindingCard key={finding.id} finding={finding}>
                {finding.drafted_change_request_id ? (
                  <p className="text-sm">
                    <Link
                      href={`/migrations/${migrationId}/change-requests/${finding.drafted_change_request_id}`}
                      className="underline"
                    >
                      Draft change request
                    </Link>
                  </p>
                ) : null}
                {finding.review_status === "proposed" ? (
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
                {finding.draftable ? (
                  <form action={draftFromFinding} className="mt-2">
                    <input type="hidden" name="migrationId" value={migrationId} />
                    <input type="hidden" name="investigationId" value={investigationId} />
                    <input type="hidden" name="findingId" value={finding.id} />
                    <SubmitButton tone="secondary">Draft a change request from this</SubmitButton>
                  </form>
                ) : null}
              </FindingCard>
            ))}
          </div>
        )}
      </Section>
      <Section title="Transcript">
        <Transcript steps={detail.steps} />
      </Section>
    </div>
  );
}
