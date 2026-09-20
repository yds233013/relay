import Link from "next/link";

import { Money } from "@/components/money";
import { BUTTON_STYLES } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";

/**
 * One decision, as the product presents it: what happened, why it matters, how much money it
 * concerns, what only a person can decide, and one way to act on it.
 *
 * The item itself is built server-side from run output (`relay.pipeline.work_queue`). This file
 * only decides how it reads and where its action points.
 */
export type WorkItem = Schemas["WorkItemOut"];

/** What kind of work this is, in the operator's vocabulary rather than the engine's. */
const KIND: Record<string, { label: string; tone: string }> = {
  account_mapping: { label: "Mapping", tone: "border-[var(--critical)]/40 text-[var(--critical)]" },
  reconciliation: {
    label: "Reconciliation",
    tone: "border-[var(--critical)]/40 text-[var(--critical)]",
  },
  migration_defect: {
    label: "Migration defect",
    tone: "border-[var(--warning)]/40 text-[var(--warning)]",
  },
  source_anomaly: {
    label: "Source anomaly",
    tone: "border-[var(--border-strong)] text-[var(--ink-muted)]",
  },
  entity_decision: {
    label: "Duplicate parties",
    tone: "border-[var(--border-strong)] text-[var(--ink-muted)]",
  },
  approval: { label: "Approval", tone: "border-[var(--accent)]/40 text-[var(--accent-ink)]" },
  data_quality: {
    label: "Unreadable data",
    tone: "border-[var(--warning)]/40 text-[var(--warning)]",
  },
};

/** Where the action goes. The server names the destination; the web knows the routes. */
export function actionHref(base: string, item: WorkItem, runId: string | null): string {
  const id = item.target_id ?? "";
  switch (item.target_kind) {
    case "mappings":
      return id ? `${base}/mappings?account=${encodeURIComponent(id)}` : `${base}/mappings`;
    case "reconciliation_line":
      return `${base}/reconciliation/lines/${id}`;
    case "issue":
      return `${base}/issues/${id}`;
    case "entities":
      return `${base}/entities/${id}`;
    case "change_request":
      return `${base}/change-requests/${id}`;
    case "import":
      return `${base}/data/imports/${id}#quarantine`;
    case "record":
      return runId ? `${base}/records/${runId}/${encodeURIComponent(id)}` : `${base}/issues`;
    default:
      return `${base}/issues`;
  }
}

export function WorkItemCard({
  item,
  base,
  runId,
  emphasis = false,
  investigate,
}: {
  item: WorkItem;
  base: string;
  runId: string | null;
  emphasis?: boolean;
  /** The investigation control for this item, rendered by the server where one applies. */
  investigate?: React.ReactNode;
}) {
  const kind = KIND[item.kind] ?? {
    label: item.kind.replaceAll("_", " "),
    tone: "border-[var(--border-strong)] text-[var(--ink-muted)]",
  };
  return (
    <article
      className={`rounded-md border bg-[var(--surface-raised)] p-4 ${
        emphasis
          ? "border-[var(--border)] border-l-4 border-l-[var(--critical)]"
          : "border-[var(--border)]"
      }`}
      data-work-kind={item.kind}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="mb-1 flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${kind.tone}`}
            >
              {kind.label}
            </span>
            {item.blocks.length > 0 ? (
              <span className="text-[11px] text-[var(--ink-subtle)]">
                blocks go-live ({item.blocks.join(", ")})
              </span>
            ) : null}
            {item.count > 1 ? (
              <span className="text-[11px] text-[var(--ink-subtle)] tabular-nums">
                {item.count} findings
              </span>
            ) : null}
          </p>
          <h3 className="text-base font-semibold leading-snug text-[var(--ink)]">{item.title}</h3>
          <p className="mt-1 max-w-3xl text-sm text-[var(--ink-muted)]">{item.summary}</p>
          {item.judgement ? (
            <p className="mt-2 max-w-3xl border-l-2 border-[var(--border-strong)] pl-3 text-sm text-[var(--ink-muted)]">
              <span className="font-medium text-[var(--ink)]">Needs your judgement: </span>
              {item.judgement}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {item.amount ? (
            <p className="text-right">
              <span
                className={`block tabular-nums ${emphasis ? "text-2xl" : "text-xl"} font-semibold text-[var(--ink)]`}
              >
                <Money value={item.amount} currency={item.currency} showCurrency={false} />
              </span>
              <span className="text-[11px] uppercase tracking-wide text-[var(--ink-subtle)]">
                {item.currency} affected
              </span>
            </p>
          ) : null}
          <Link
            href={actionHref(base, item, runId)}
            className={`${BUTTON_STYLES.primary} no-underline`}
          >
            {item.action_label}
          </Link>
          {investigate}
        </div>
      </div>
    </article>
  );
}
