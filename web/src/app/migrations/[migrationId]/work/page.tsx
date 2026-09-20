import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { Callout, EmptyState, PageHeader, Panel, Section } from "@/components/ui";
import { InvestigateAction } from "@/components/investigate-action";
import { WorkItemCard } from "@/components/work-item";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

/**
 * Everything still waiting on a person, so nobody has to go hunting through mappings, validation,
 * reconciliation, issues, entities and approvals to work out what to do next.
 */
export default async function WorkQueuePage(props: PageProps<"/migrations/[migrationId]/work">) {
  const { migrationId } = await props.params;
  const base = `/migrations/${migrationId}`;
  const [queue, overview] = await Promise.all([
    apiGet<Schemas["WorkQueueOut"]>(`/api/v1/migrations/${migrationId}/work-queue`),
    apiGet<Schemas["OverviewOut"]>(`/api/v1/migrations/${migrationId}/overview`),
  ]);
  const items = queue.items;
  const blocking = items.filter((item) => item.blocks.length > 0);
  const rest = items.filter((item) => item.blocks.length === 0);
  const approvals = items.filter((item) => item.kind === "approval");
  const automation = queue.automation;

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Work queue"
        description="Everything the automatic checks could not settle on their own, most consequential first."
        status={
          <span className="text-sm text-[var(--ink-muted)] tabular-nums">
            {items.length} item{items.length === 1 ? "" : "s"}
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
      ) : null}

      {approvals.length > 0 ? (
        <Section
          title="Waiting for a decision from someone else"
          description="Proposed corrections do not change anything until they are approved."
        >
          <div className="space-y-3">
            {approvals.map((item) => (
              <WorkItemCard
                key={item.key}
                item={item}
                base={base}
                runId={overview.run_id ?? null}
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
        </Section>
      ) : null}

      {blocking.filter((item) => item.kind !== "approval").length > 0 ? (
        <Section
          title="Blocking go-live"
          description="Each of these keeps at least one readiness check failing."
        >
          <div className="space-y-3">
            {blocking
              .filter((item) => item.kind !== "approval")
              .map((item, index) => (
                <WorkItemCard
                  key={item.key}
                  item={item}
                  base={base}
                  runId={overview.run_id ?? null}
                  emphasis={index === 0}
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
        </Section>
      ) : null}

      {rest.filter((item) => item.kind !== "approval").length > 0 ? (
        <Section
          title="Worth resolving before go-live"
          description="These do not fail a readiness check on their own, and they still represent unfinished work."
        >
          <div className="space-y-3">
            {rest
              .filter((item) => item.kind !== "approval")
              .map((item) => (
                <WorkItemCard
                  key={item.key}
                  item={item}
                  base={base}
                  runId={overview.run_id ?? null}
                />
              ))}
          </div>
        </Section>
      ) : null}

      <Panel className="px-3 py-2 text-sm text-[var(--ink-muted)]">
        Every item here is derived from the latest verification run. Resolving one does not tick it
        off by hand: the next run either stops reporting it or does not.{" "}
        <Link href={`${base}/issues`}>See the full finding list</Link> for the underlying detail.
      </Panel>
    </div>
  );
}
