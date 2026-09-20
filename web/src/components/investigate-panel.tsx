import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { Section } from "@/components/page-header";
import { isPublicDemo } from "@/lib/demo";
import { apiGet, type Schemas } from "@/lib/api/client";
import { Panel } from "@/components/ui";

import { startInvestigation } from "@/app/migrations/[migrationId]/ai-actions";

/** Rendered only when AI is configured and the customer consented for this migration. */
export async function InvestigatePanel({
  migrationId,
  issueId,
  returnTo,
  defaultQuestion,
}: {
  migrationId: string;
  issueId?: string;
  returnTo: string;
  defaultQuestion?: string;
}) {
  const status = await apiGet<Schemas["AIStatusOut"]>("/api/v1/ai/status", {
    migration_id: migrationId,
  });
  if (!status.available) {
    // Off is a deliberate state, not a missing feature: the deterministic engine decides
    // everything on its own, and the assistant needs both a configured provider and the
    // customer's recorded consent before it may read anything.
    return (
      <Panel className="mb-6 p-3" data-testid="ai-unavailable">
        <p className="text-sm font-medium text-[var(--ink)]">
          Investigation assistant — off for this implementation
        </p>
        <p className="mt-1 max-w-3xl text-sm text-[var(--ink-muted)]">
          {status.configured
            ? "The customer has not recorded consent for AI processing on this implementation."
            : "No model provider is configured for this deployment."}{" "}
          Nothing above depends on it. Relay divides the work deliberately:
        </p>
        <ul className="mt-2 grid max-w-4xl grid-cols-1 gap-x-6 gap-y-1 text-sm text-[var(--ink-muted)] sm:grid-cols-2">
          <li>
            <span className="font-medium text-[var(--ink)]">Deterministic controls</span> find the
            accounting and data failures, and decide readiness.
          </li>
          <li>
            <span className="font-medium text-[var(--ink)]">The assistant</span>, when enabled,
            reads that evidence with read-only tools and drafts an explanation — it cannot change
            anything.
          </li>
          <li>
            <span className="font-medium text-[var(--ink)]">A person</span> decides, and a second
            person approves any material correction.
          </li>
          <li>
            <span className="font-medium text-[var(--ink)]">A fresh run</span> re-checks the result
            deterministically.
          </li>
        </ul>
      </Panel>
    );
  }
  const previous = await apiGet<Schemas["InvestigationOut"][]>(
    `/api/v1/migrations/${migrationId}/investigations`,
    { issue_id: issueId, limit: 5 },
  );
  return (
    <Section title="Investigate with AI">
      <div data-testid="investigate-panel">
        <p className="mb-2 text-xs text-[var(--ink-muted)]">
          The investigator reads this migration with read-only tools and cites its evidence. It
          cannot change anything.
        </p>
        {isPublicDemo() ? (
          <p className="mb-2 text-xs text-[var(--ink-muted)]">
            In this public demo every visitor shares one copy, so a finding is investigated once and
            everyone sees that same result. The tools really run against this database — the
            evidence is genuine — and the reasoning is a scripted transcript, not a model.
          </p>
        ) : null}
        <form action={startInvestigation} className="flex max-w-2xl flex-col gap-2">
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="issueId" value={issueId ?? ""} />
          <input type="hidden" name="returnTo" value={returnTo} />
          {isPublicDemo() ? (
            // The answer is derived per finding and per run, so a typed question would not change
            // it here. Offering the box anyway would imply an interaction the demo does not have.
            <input type="hidden" name="question" value={defaultQuestion} />
          ) : (
            <TextArea name="question" label="Question" defaultValue={defaultQuestion} required />
          )}
          <span>
            <SubmitButton tone="secondary" allowedInDemo>
              Investigate
            </SubmitButton>
          </span>
        </form>
        {previous.length > 0 ? (
          <ul className="mt-2 list-inside list-disc text-sm">
            {previous.map((i) => (
              <li key={i.id}>
                <Link
                  href={`/migrations/${migrationId}/investigations/${i.id}`}
                  className="underline"
                >
                  {i.question}
                </Link>{" "}
                ({i.status})
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Section>
  );
}
