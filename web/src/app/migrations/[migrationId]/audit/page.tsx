import { Timestamp } from "@/components/dates";
import { DataTable } from "@/components/data-table";
import { FilterForm } from "@/components/filters";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

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
    <div className="max-w-[1400px]">
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
          <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
            Action
          </span>
          <input
            name="action"
            defaultValue={filters.action ?? ""}
            className="rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 transition-colors hover:border-[var(--ink-muted)]"
            placeholder="issue.created"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
            Entity type
          </span>
          <input
            name="entity_type"
            defaultValue={filters.entity_type ?? ""}
            className="rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 transition-colors hover:border-[var(--ink-muted)]"
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
        // Who did what, when, and what it changed. The hash chain is what makes this trustworthy,
        // but it is not what anyone reads, so the sequence number rides along with the timestamp
        // and the raw dotted action name sits under its plain-English form.
        columns={[
          {
            header: "Who",
            cell: (e) => <span className="font-medium text-[var(--ink)]">{e.actor_type}</span>,
          },
          {
            header: "Did what",
            cell: (e) => (
              <>
                <span className="font-medium text-[var(--ink)]">{humanize(e.action)}</span>
                <span className="mt-0.5 block text-xs text-[var(--ink-muted)]">
                  on a {e.entity_type.replaceAll("_", " ")}
                </span>
                <span className="mt-0.5 block font-mono text-[11px] text-[var(--ink-subtle)]">
                  {e.action}
                </span>
              </>
            ),
          },
          {
            header: "When",
            cell: (e) => (
              <>
                <span className="whitespace-nowrap tabular-nums text-[var(--ink-muted)]">
                  <Timestamp value={e.occurred_at} />
                </span>
                <span className="mt-0.5 block font-mono text-[11px] tabular-nums text-[var(--ink-subtle)]">
                  #{e.migration_seq}
                </span>
              </>
            ),
          },
          {
            header: "Result",
            cell: (e) => (
              <>
                {e.reason ? (
                  <span className="block max-w-md text-[var(--ink-muted)]">{e.reason}</span>
                ) : null}
                <details className={e.reason ? "mt-1" : ""}>
                  <summary className="text-xs text-[var(--ink-muted)]">before / after</summary>
                  <pre className="mt-1 max-w-md overflow-x-auto rounded-[var(--radius-control)] bg-[var(--surface-sunken)] p-2 text-xs">
                    {JSON.stringify({ before: e.before, after: e.after }, null, 2)}
                  </pre>
                </details>
              </>
            ),
          },
        ]}
      />
    </div>
  );
}
