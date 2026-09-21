import Link from "next/link";

import { Money } from "@/components/money";
import { BUTTON_STYLES } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";

/**
 * One decision, as the product presents it: what happened, why it matters, how much money it
 * concerns, what only a person can decide, and one way to act on it.
 *
 * The plain sentence leads and the technical labels follow it, because the operator reading this
 * is deciding whether to spend an hour on it, not looking up a gate id. Nothing here knows which
 * item it is looking at: the ordering, the blocking flag and the amount all arrive from the
 * server's own composition of run output (`relay.pipeline.work_queue`). This file only decides
 * how an item reads and where its action points.
 */
export type WorkItem = Schemas["WorkItemOut"];

const NEUTRAL_CHIP = "bg-[var(--surface-sunken)] text-[var(--ink-muted)]";

/**
 * What kind of work this is, in the operator's vocabulary rather than the engine's.
 *
 * Kind is a category, not a severity, so these are neutral. Whether an item blocks go-live is the
 * only thing on a card allowed to be red — otherwise a queue of ordinary work reads as an
 * emergency, and the one item that really is blocking stops standing out.
 */
const KIND: Record<string, { label: string; tone: string }> = {
  account_mapping: { label: "Mapping", tone: NEUTRAL_CHIP },
  reconciliation: { label: "Reconciliation", tone: NEUTRAL_CHIP },
  migration_defect: { label: "Migration defect", tone: NEUTRAL_CHIP },
  source_anomaly: { label: "Source anomaly", tone: NEUTRAL_CHIP },
  entity_decision: { label: "Duplicate parties", tone: NEUTRAL_CHIP },
  approval: { label: "Approval", tone: "bg-[var(--accent-soft)] text-[var(--accent-ink)]" },
  data_quality: { label: "Unreadable data", tone: NEUTRAL_CHIP },
};

const CHIP =
  "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em]";

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
    tone: NEUTRAL_CHIP,
  };
  const blocking = item.blocks.length > 0;
  return (
    <article
      className={`rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)] p-4 transition-colors hover:border-[var(--border-strong)] sm:p-5 ${
        blocking ? "border-l-[3px] border-l-[var(--critical)]" : ""
      } ${
        emphasis
          ? "shadow-[var(--shadow-raised)] ring-1 ring-[var(--critical)]/25"
          : "shadow-[var(--shadow-card)]"
      }`}
      data-work-kind={item.kind}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <p className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className={`${CHIP} ${kind.tone}`}>{kind.label}</span>
            {blocking ? (
              <span className={`${CHIP} bg-[var(--critical-soft)] text-[var(--critical)]`}>
                Blocks go-live
              </span>
            ) : null}
            {item.count > 1 ? (
              <span className="text-[11px] tabular-nums text-[var(--ink-subtle)]">
                {item.count} findings
              </span>
            ) : null}
          </p>
          <h3 className="text-base font-semibold leading-snug tracking-tight text-[var(--ink)]">
            {item.title}
          </h3>
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-[var(--ink-muted)]">
            {item.summary}
          </p>
          {item.judgement ? (
            <p className="mt-3 max-w-3xl border-l-2 border-[var(--border-strong)] pl-3 text-sm leading-relaxed text-[var(--ink-muted)]">
              <span className="font-semibold text-[var(--ink)]">Needs your judgement: </span>
              {item.judgement}
            </p>
          ) : null}
          {/* The technical tier, last and quiet: which readiness checks this item is keeping down. */}
          {blocking ? (
            <p className="mt-2 font-mono text-[11px] text-[var(--ink-subtle)]">
              readiness {item.blocks.join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-start gap-2.5 sm:items-end">
          {item.amount ? (
            <p className="sm:text-right">
              <span
                className={`block text-[var(--ink)] ${emphasis ? "figure-hero" : "text-xl font-semibold tracking-tight tabular-nums"}`}
              >
                <Money value={item.amount} currency={item.currency} showCurrency={false} />
              </span>
              <span className="text-[11px] uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
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
