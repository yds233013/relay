import { Timestamp } from "@/components/dates";
import { DataTable } from "@/components/data-table";
import { FilterForm } from "@/components/filters";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function AuditPage(props: PageProps<"/migrations/[migrationId]/audit">) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const filters = { action: param(search.action), entity_type: param(search.entity_type) };
  const cursor = param(search.cursor);
  const [events, verification] = await Promise.all([
    apiGet<Schemas["Page_AuditEventOut_"]>(`/api/v1/migrations/${migrationId}/audit-events`, {
      ...filters,
      cursor,
      limit: 100,
    }),
    apiGet<Schemas["ChainVerificationOut"]>(
      `/api/v1/migrations/${migrationId}/audit-events/verify`,
    ),
  ]);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Audit log"
        description={`Append-only and hash-chained. ${verification.events_checked} events checked.`}
      >
        {verification.valid ? (
          <StatusChip status="pass" label="chain verified" />
        ) : (
          <StatusChip
            status="fail"
            label={`chain broken at ${verification.first_broken_seq}: ${verification.problem}`}
          />
        )}
      </PageHeader>
      <FilterForm>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-[var(--ink-muted)]">Action</span>
          <input
            name="action"
            defaultValue={filters.action ?? ""}
            className="rounded border border-[var(--border-strong)] px-2 py-1"
            placeholder="issue.created"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-[var(--ink-muted)]">Entity type</span>
          <input
            name="entity_type"
            defaultValue={filters.entity_type ?? ""}
            className="rounded border border-[var(--border-strong)] px-2 py-1"
            placeholder="issue"
          />
        </label>
      </FilterForm>
      <DataTable<Schemas["AuditEventOut"]>
        caption="Events in order"
        rows={events.items}
        rowKey={(e) => e.id}
        nextHref={
          events.next_cursor
            ? buildPath(`/migrations/${migrationId}/audit`, {
                ...filters,
                cursor: events.next_cursor,
              })
            : null
        }
        columns={[
          {
            header: "#",
            align: "right",
            cell: (e) => <span className="tabular-nums">{e.migration_seq}</span>,
          },
          { header: "When", cell: (e) => <Timestamp value={e.occurred_at} /> },
          { header: "Actor", cell: (e) => e.actor_type },
          { header: "Action", cell: (e) => <span className="font-mono text-xs">{e.action}</span> },
          { header: "Entity", cell: (e) => <span className="text-xs">{e.entity_type}</span> },
          {
            header: "Change",
            cell: (e) => (
              <details>
                <summary className="cursor-pointer text-xs underline">before / after</summary>
                <pre className="max-w-md overflow-x-auto text-xs">
                  {JSON.stringify({ before: e.before, after: e.after, reason: e.reason }, null, 2)}
                </pre>
              </details>
            ),
          },
        ]}
      />
    </div>
  );
}
