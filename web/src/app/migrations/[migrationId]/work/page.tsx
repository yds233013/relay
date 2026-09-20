import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { FilterForm, SelectFilter } from "@/components/filters";
import { TextField } from "@/components/forms";
import { Money } from "@/components/money";
import { BUTTON_STYLES, Callout, EmptyState, PageHeader, Panel, Section } from "@/components/ui";
import { InvestigateAction } from "@/components/investigate-action";
import { actionHref, WorkItemCard, type WorkItem } from "@/components/work-item";
import { apiGet, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

/** Kinds of work, in the operator's vocabulary. Same names the card badge uses. */
const KIND_LABELS: Record<string, string> = {
  account_mapping: "Mapping",
  reconciliation: "Reconciliation",
  migration_defect: "Migration defect",
  source_anomaly: "Source anomaly",
  entity_decision: "Duplicate parties",
  approval: "Approval",
  data_quality: "Unreadable data",
};

const KIND_VALUES = [
  "account_mapping",
  "reconciliation",
  "migration_defect",
  "source_anomaly",
  "entity_decision",
  "approval",
  "data_quality",
] as const;

const BLOCKING_VALUES = ["yes", "no"] as const;

const INVESTIGATION_VALUES = ["none", "investigating", "investigated", "failed"] as const;

type InvestigationState = (typeof INVESTIGATION_VALUES)[number];

const INVESTIGATION_LABELS: Record<InvestigationState, string> = {
  none: "Not investigated",
  investigating: "Investigating now",
  investigated: "Investigated",
  failed: "Investigation failed",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind.replaceAll("_", " ");
}

/** Only values this page knows about survive; anything else is treated as no filter at all. */
function oneOf<T extends string>(value: string | undefined, allowed: readonly T[]): T | undefined {
  return allowed.find((entry) => entry === value);
}

/**
 * The investigation state of an item, derived from the run's own investigation record. The payload
 * carries it as an open object, so the status is read defensively.
 */
function investigationState(item: WorkItem): InvestigationState {
  const status = item.investigation?.status;
  if (typeof status !== "string") {
    return "none";
  }
  if (status === "succeeded") {
    return "investigated";
  }
  if (status === "queued" || status === "running") {
    return "investigating";
  }
  return "failed";
}

/**
 * The tail of a section: one row per decision, in the order the server chose.
 *
 * Below the leading items a card's full argument is repetition, and repetition is what makes a
 * twenty-item queue unreadable. A row keeps exactly what the next action depends on — what kind of
 * work it is, whether it blocks go-live, how much money it concerns, whether anyone has
 * investigated it, and the way in — with amounts in one right-aligned tabular column so they can be
 * compared down the page.
 */
function CompactRows({
  items,
  base,
  runId,
  migrationId,
  caption,
}: {
  items: readonly WorkItem[];
  base: string;
  runId: string | null;
  migrationId: string;
  caption: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
            <th scope="col" className="px-2 py-1.5 font-medium">
              Decision
            </th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">
              Amount
            </th>
            <th scope="col" className="px-2 py-1.5 font-medium">
              Investigation
            </th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">
              Next action
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.key}
              data-work-kind={item.kind}
              className="border-b border-[var(--border)]/60 align-top hover:bg-[var(--surface-sunken)]"
            >
              <th scope="row" className="px-2 py-2 text-left font-normal">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center rounded border border-[var(--border-strong)] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
                    {kindLabel(item.kind)}
                  </span>
                  {item.blocks.length > 0 ? (
                    <span className="inline-flex items-center rounded border border-[var(--critical)]/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--critical)]">
                      Blocks {item.blocks.join(", ")}
                    </span>
                  ) : null}
                  {item.count > 1 ? (
                    <span className="text-[11px] text-[var(--ink-subtle)] tabular-nums">
                      {item.count} findings
                    </span>
                  ) : null}
                </span>
                <span className="mt-0.5 block font-medium text-[var(--ink)]">{item.title}</span>
              </th>
              <td className="px-2 py-2 text-right">
                <Money value={item.amount} currency={item.currency} />
              </td>
              <td className="px-2 py-2">
                <InvestigateAction
                  item={item}
                  base={base}
                  migrationId={migrationId}
                  returnTo={`${base}/work`}
                />
              </td>
              <td className="px-2 py-2 text-right">
                <Link
                  href={actionHref(base, item, runId)}
                  className={`${BUTTON_STYLES.secondary} whitespace-nowrap no-underline`}
                >
                  {item.action_label}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** How many items of a group are argued in full before the rest become rows. */
const LEAD = 2;

function Group({
  title,
  description,
  items,
  base,
  runId,
  migrationId,
  emphasiseFirst = false,
}: {
  title: string;
  description: string;
  items: readonly WorkItem[];
  base: string;
  runId: string | null;
  migrationId: string;
  emphasiseFirst?: boolean;
}) {
  if (items.length === 0) {
    return null;
  }
  const lead = items.slice(0, LEAD);
  const tail = items.slice(LEAD);
  return (
    <Section
      title={title}
      description={description}
      actions={
        <span className="text-[var(--ink-muted)] tabular-nums">
          {items.length} item{items.length === 1 ? "" : "s"}
        </span>
      }
    >
      <div className="space-y-3">
        {lead.map((item, index) => (
          <WorkItemCard
            key={item.key}
            item={item}
            base={base}
            runId={runId}
            emphasis={emphasiseFirst && index === 0}
            investigate={
              <InvestigateAction
                item={item}
                base={base}
                migrationId={migrationId}
                returnTo={`${base}/work`}
              />
            }
          />
        ))}
      </div>
      {tail.length > 0 ? (
        <Panel className="mt-3 px-2 py-1">
          <CompactRows
            items={tail}
            base={base}
            runId={runId}
            migrationId={migrationId}
            caption={`${title}: the remaining ${tail.length} item${tail.length === 1 ? "" : "s"}, in priority order`}
          />
        </Panel>
      ) : null}
    </Section>
  );
}

/**
 * Everything still waiting on a person, so nobody has to go hunting through mappings, validation,
 * reconciliation, issues, entities and approvals to work out what to do next.
 *
 * The order is the server's (blocking first, then amount) and is never re-sorted here. Filtering
 * narrows that same order: the filters live in the URL, are applied on the server, and the page
 * always says in words which population is on screen.
 */
export default async function WorkQueuePage(props: PageProps<"/migrations/[migrationId]/work">) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const base = `/migrations/${migrationId}`;
  const [queue, overview] = await Promise.all([
    apiGet<Schemas["WorkQueueOut"]>(`/api/v1/migrations/${migrationId}/work-queue`),
    apiGet<Schemas["OverviewOut"]>(`/api/v1/migrations/${migrationId}/overview`),
  ]);
  const items = queue.items;
  const automation = queue.automation;
  const runId = overview.run_id ?? null;

  const filters = {
    kind: oneOf(param(search.kind), KIND_VALUES),
    blocking: oneOf(param(search.blocking), BLOCKING_VALUES),
    investigation: oneOf(param(search.investigation), INVESTIGATION_VALUES),
    q: (param(search.q) ?? "").trim(),
  };
  const needle = filters.q.toLowerCase();
  const visible = items.filter(
    (item) =>
      (filters.kind === undefined || item.kind === filters.kind) &&
      (filters.blocking === undefined || (filters.blocking === "yes") === item.blocks.length > 0) &&
      (filters.investigation === undefined || investigationState(item) === filters.investigation) &&
      (needle === "" || `${item.title} ${item.summary}`.toLowerCase().includes(needle)),
  );

  // Stated in words, so a filtered queue is never mistaken for the whole of the work.
  const applied = [
    filters.kind === undefined ? null : `kind ${kindLabel(filters.kind).toLowerCase()}`,
    filters.blocking === undefined
      ? null
      : filters.blocking === "yes"
        ? "blocking go-live"
        : "not blocking go-live",
    filters.investigation === undefined
      ? null
      : INVESTIGATION_LABELS[filters.investigation].toLowerCase(),
    needle === "" ? null : `text "${filters.q}"`,
  ].filter((entry): entry is string => entry !== null);
  const filtered = applied.length > 0;

  const approvals = visible.filter((item) => item.kind === "approval");
  const blocking = visible.filter((item) => item.kind !== "approval" && item.blocks.length > 0);
  const rest = visible.filter((item) => item.kind !== "approval" && item.blocks.length === 0);

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Work queue"
        description="Everything the automatic checks could not settle on their own, most consequential first."
        status={
          <span className="text-sm text-[var(--ink-muted)] tabular-nums">
            {filtered ? (
              <>
                showing {visible.length} of {items.length}
              </>
            ) : (
              <>
                {items.length} item{items.length === 1 ? "" : "s"}
              </>
            )}
          </span>
        }
      />

      <div className="mb-5">
        <Callout>
          Relay evaluated {automation.controls_evaluated ?? 0} accounting controls and{" "}
          {automation.reconciliations_performed ?? 0} reconciliations over{" "}
          <span className="tabular-nums">
            {automation.staged_records?.toLocaleString("en-US") ?? 0}
          </span>{" "}
          records on run #{automation.run_sequence}
          {automation.finished_at ? (
            <>
              {" "}
              (<Timestamp value={automation.finished_at} />)
            </>
          ) : null}{" "}
          and raised {automation.findings ?? 0} findings. Those findings are grouped below into the{" "}
          {items.length} decision{items.length === 1 ? "" : "s"} that need a person.{" "}
          <Link href={`${base}/runs/${overview.run_id ?? ""}`}>See what the run did</Link>.
        </Callout>
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="Nothing is waiting on a person."
          hint="Every check either passed or has already been resolved or dispositioned."
        />
      ) : (
        <>
          {/* Narrowing the queue, in the URL: every view here is linkable and survives a reload. */}
          <Panel className="mb-4 p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--ink-subtle)]">
              Narrow the queue
            </p>
            <FilterForm>
              <SelectFilter
                name="kind"
                label="Kind of work"
                value={filters.kind}
                options={KIND_VALUES.map((kind) => [kind, kindLabel(kind)] as const)}
              />
              <SelectFilter
                name="blocking"
                label="Go-live"
                value={filters.blocking}
                options={[
                  ["yes", "Blocks go-live"],
                  ["no", "Does not block go-live"],
                ]}
              />
              <SelectFilter
                name="investigation"
                label="Investigation"
                value={filters.investigation}
                options={INVESTIGATION_VALUES.map(
                  (state) => [state, INVESTIGATION_LABELS[state]] as const,
                )}
              />
              <TextField name="q" label="Text in title or summary" defaultValue={filters.q} />
            </FilterForm>
            <p className="border-t border-[var(--border)] pt-2 text-sm text-[var(--ink-muted)]">
              {filtered ? (
                <>
                  <span className="font-medium text-[var(--ink)]">
                    Filtered by {applied.join(", ")}
                  </span>
                  : showing {visible.length} of {items.length} decision
                  {items.length === 1 ? "" : "s"}, in the queue&rsquo;s own priority order.{" "}
                  <Link href={`${base}/work`}>Clear the filter</Link>.
                </>
              ) : (
                <>
                  <span className="font-medium text-[var(--ink)]">No filter applied.</span> All{" "}
                  {items.length} decision{items.length === 1 ? "" : "s"} are listed, blocking work
                  first and then by the amount each one concerns.
                </>
              )}
            </p>
          </Panel>

          {visible.length === 0 ? (
            <EmptyState
              title="No work matches this filter."
              hint={
                <>
                  Nothing in this queue matches {applied.join(" and ")}.{" "}
                  <Link href={`${base}/work`}>Clear the filter</Link> to see all {items.length}{" "}
                  decision{items.length === 1 ? "" : "s"}.
                </>
              }
            />
          ) : null}
        </>
      )}

      <Group
        title="Waiting for a decision from someone else"
        description="Proposed corrections do not change anything until they are approved."
        items={approvals}
        base={base}
        runId={runId}
        migrationId={migrationId}
      />

      <Group
        title="Blocking go-live"
        description="Each of these keeps at least one readiness check failing."
        items={blocking}
        base={base}
        runId={runId}
        migrationId={migrationId}
        emphasiseFirst
      />

      <Group
        title="Worth resolving before go-live"
        description="These do not fail a readiness check on their own, and they still represent unfinished work."
        items={rest}
        base={base}
        runId={runId}
        migrationId={migrationId}
      />

      <Panel className="px-3 py-2 text-sm text-[var(--ink-muted)]">
        Every item here is derived from the latest verification run. Resolving one does not tick it
        off by hand: the next run either stops reporting it or does not.{" "}
        <Link href={`${base}/issues`}>See the full finding list</Link> for the underlying detail.
      </Panel>
    </div>
  );
}
