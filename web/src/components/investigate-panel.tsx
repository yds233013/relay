import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { Section } from "@/components/page-header";
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
      <Panel className="mb-6 px-3 py-2" data-testid="ai-unavailable">
        <p className="text-sm text-[var(--ink-muted)]">
          <span className="font-medium text-[var(--ink)]">Assistant off.</span>{" "}
          {status.configured
            ? "This migration has not recorded customer consent for AI processing."
            : "No AI provider is configured for this deployment."}{" "}
          Nothing on this page depends on it: every finding, reconciliation and gate above is
          produced by the deterministic engine.
        </p>
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
        <form action={startInvestigation} className="flex max-w-2xl flex-col gap-2">
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="issueId" value={issueId ?? ""} />
          <input type="hidden" name="returnTo" value={returnTo} />
          <TextArea name="question" label="Question" defaultValue={defaultQuestion} required />
          <span>
            <SubmitButton tone="secondary">Investigate</SubmitButton>
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
