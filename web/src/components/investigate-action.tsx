import Link from "next/link";

import { SubmitButton } from "@/components/forms";
import { apiGet, type Schemas } from "@/lib/api/client";
import type { WorkItem } from "@/components/work-item";

import { startInvestigation } from "@/app/migrations/[migrationId]/ai-actions";

/**
 * The investigation state of one piece of work, and the way to start one.
 *
 * Investigation is part of doing the work, not a separate assistant to go and consult, so it lives
 * on the item itself. It is only offered where there is a finding to investigate and the customer
 * has consented; everywhere else this renders nothing rather than a disabled button nobody can use.
 */
const STATE: Record<string, { label: string; className: string }> = {
  queued: {
    label: "Investigating…",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  },
  running: {
    label: "Investigating…",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  },
  succeeded: {
    label: "Investigated",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  },
  failed: {
    label: "Investigation failed",
    className: "border-[var(--warning)]/40 bg-[var(--warning-soft)] text-[var(--warning)]",
  },
};

export async function InvestigateAction({
  item,
  base,
  migrationId,
  returnTo,
}: {
  item: WorkItem;
  base: string;
  migrationId: string;
  returnTo: string;
}) {
  if (!item.issue_id) {
    return null;
  }
  const state = item.investigation;
  if (state) {
    const style = STATE[state.status as string] ?? STATE.failed;
    return (
      <Link
        href={`${base}/investigations/${state.id}`}
        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-medium no-underline ${style?.className ?? ""}`}
      >
        {style?.label ?? "Investigation"}
        {state.status === "succeeded" && typeof state.finding_count === "number"
          ? ` · ${state.finding_count} finding${state.finding_count === 1 ? "" : "s"}`
          : ""}
      </Link>
    );
  }
  const status = await apiGet<Schemas["AIStatusOut"]>("/api/v1/ai/status", {
    migration_id: migrationId,
  });
  if (!status.available) {
    return null;
  }
  return (
    <form action={startInvestigation}>
      <input type="hidden" name="migrationId" value={migrationId} />
      <input type="hidden" name="issueId" value={item.issue_id} />
      <input type="hidden" name="returnTo" value={returnTo} />
      <input
        type="hidden"
        name="question"
        value={`${item.title}. What is the likely cause, and what should we do about it?`}
      />
      <SubmitButton tone="secondary">Investigate</SubmitButton>
    </form>
  );
}
